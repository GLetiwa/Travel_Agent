"""
Core flight search pipeline: search → parse → score.
Imported by both main.py (CLI) and app.py (web server).
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

DUFFEL_BASE_URL = "https://api.duffel.com"
DUFFEL_VERSION = "v2"
SANDBOX_CARRIER_CODE = "ZZ"  # Duffel Airways test/demo airline — not a real flight option

# Scoring weights — must sum to 1.0; raise WEIGHT_PRICE to favour cost more
WEIGHT_PRICE = 0.60
WEIGHT_DURATION = 0.40

# Penalty amounts subtracted from the 0–1 base score
PENALTY_EXCESS_STOPS = 0.30   # per stop beyond MAX_PREFERRED_STOPS
PENALTY_LONG_FLIGHT = 0.10    # when total duration exceeds MAX_PREFERRED_HOURS
PENALTY_RED_EYE = 0.10        # red-eye departure, only when alternatives exist

MAX_PREFERRED_STOPS = 1       # flag (but don't exclude) anything above this
MAX_PREFERRED_HOURS = 12      # flag flights longer than this
RED_EYE_END_HOUR = 6          # departure before 06:00 counts as red-eye

MAX_RESULTS_SHOWN = 10        # ranked results printed by CLI by default


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LayoverInfo:
    airport: str          # IATA code of the connection airport
    duration_minutes: int


@dataclass
class SliceInfo:
    """One direction of travel (outbound or return)."""
    origin: str           # IATA
    destination: str      # IATA
    departs_at: datetime  # local departure time
    arrives_at: datetime  # local arrival time
    duration_minutes: int
    stops: int            # 0 = direct, 1 = one connection, etc.
    layovers: list[LayoverInfo] = field(default_factory=list)
    airlines: list[str] = field(default_factory=list)  # unique carrier names


@dataclass
class ParsedOffer:
    offer_id: str
    price: float
    currency: str
    total_duration_minutes: int   # sum across all slices
    slices: list[SliceInfo]
    checked_bags: int             # quantity for first passenger on first segment
    carry_on_bags: int


@dataclass
class ScoredOffer:
    offer: ParsedOffer
    score: float        # higher = better; used only for sorting
    reason: str         # one-line label shown in output
    flags: list[str]    # warnings e.g. "over 12h", "red-eye departure"


@dataclass
class SearchResult:
    """Everything find_best_flights() returns — offers plus metadata for display."""
    scored_offers: list[ScoredOffer]
    sandbox_filtered: int    # sandbox ZZ offers removed before scoring
    codeshares_removed: int  # duplicate codeshare offers removed before scoring


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_iso_duration_minutes(duration: str) -> int:
    """Convert an ISO 8601 duration string like 'PT9H42M' to total minutes."""
    days = int(m.group(1)) if (m := re.search(r'(\d+)D', duration)) else 0
    hours = int(m.group(1)) if (m := re.search(r'(\d+)H', duration)) else 0
    mins = int(m.group(1)) if (m := re.search(r'(\d+)M', duration)) else 0
    return days * 1440 + hours * 60 + mins


def _minutes_between(earlier: str, later: str) -> int:
    """Minutes between two ISO 8601 datetime strings (handles optional timezone offsets)."""
    delta = datetime.fromisoformat(later) - datetime.fromisoformat(earlier)
    return int(delta.total_seconds() / 60)


def _parse_slice(raw_slice: dict) -> SliceInfo:
    segments = raw_slice["segments"]
    first_seg = segments[0]
    last_seg = segments[-1]

    seen: set[str] = set()
    airlines: list[str] = []
    for seg in segments:
        name = seg["marketing_carrier"]["name"]
        if name not in seen:
            seen.add(name)
            airlines.append(name)

    layovers: list[LayoverInfo] = []
    for i in range(len(segments) - 1):
        connection_airport = segments[i]["destination"]["iata_code"]
        gap = _minutes_between(segments[i]["arriving_at"],
                               segments[i + 1]["departing_at"])
        layovers.append(LayoverInfo(airport=connection_airport,
                                    duration_minutes=gap))

    return SliceInfo(
        origin=first_seg["origin"]["iata_code"],
        destination=last_seg["destination"]["iata_code"],
        departs_at=datetime.fromisoformat(first_seg["departing_at"]),
        arrives_at=datetime.fromisoformat(last_seg["arriving_at"]),
        duration_minutes=_parse_iso_duration_minutes(raw_slice["duration"]),
        stops=len(segments) - 1,
        layovers=layovers,
        airlines=airlines,
    )


def _parse_baggage(raw_offer: dict) -> tuple[int, int]:
    """Return (checked_bags, carry_on_bags) from the first segment/passenger."""
    try:
        baggages = raw_offer["slices"][0]["segments"][0]["passengers"][0]["baggages"]
    except (KeyError, IndexError):
        return 0, 0
    checked = sum(b["quantity"] for b in baggages if b["type"] == "checked")
    carry_on = sum(b["quantity"] for b in baggages if b["type"] == "carry_on")
    return checked, carry_on


def parse_offer(raw: dict) -> ParsedOffer:
    """Turn a raw Duffel offer dict into a clean ParsedOffer."""
    slices = [_parse_slice(s) for s in raw["slices"]]
    total_duration = sum(s.duration_minutes for s in slices)
    checked, carry_on = _parse_baggage(raw)

    return ParsedOffer(
        offer_id=raw["id"],
        price=float(raw["total_amount"]),
        currency=raw["total_currency"],
        total_duration_minutes=total_duration,
        slices=slices,
        checked_bags=checked,
        carry_on_bags=carry_on,
    )


def _is_sandbox_offer(raw: dict) -> bool:
    """True if any segment uses the Duffel test carrier (ZZ / Duffel Airways)."""
    for raw_slice in raw.get("slices", []):
        for seg in raw_slice.get("segments", []):
            if seg.get("marketing_carrier", {}).get("iata_code") == SANDBOX_CARRIER_CODE:
                return True
    return False


def parse_offers(raw_offers: list) -> tuple[list[ParsedOffer], int]:
    """Parse real offers; return (parsed_offers, count_of_sandbox_offers_removed)."""
    real = [o for o in raw_offers if not _is_sandbox_offer(o)]
    sandbox_count = len(raw_offers) - len(real)
    return [parse_offer(o) for o in real], sandbox_count


def dedupe_codeshares(offers: list[ParsedOffer]) -> tuple[list[ParsedOffer], int]:
    """Remove duplicate codeshare offers — same physical flight, different marketing airline.

    Two offers are treated as the same flight when all slices share identical
    departure and arrival datetimes. The cheapest version is kept.
    Returns (deduped_offers, removed_count).
    """
    best: dict[tuple, ParsedOffer] = {}
    for offer in offers:
        key = tuple((sl.departs_at, sl.arrives_at) for sl in offer.slices)
        if key not in best or offer.price < best[key].price:
            best[key] = offer
    removed = len(offers) - len(best)
    return list(best.values()), removed


# ---------------------------------------------------------------------------
# Scoring & ranking
# ---------------------------------------------------------------------------

def _is_red_eye(offer: ParsedOffer) -> bool:
    """Outbound slice departs before RED_EYE_END_HOUR (local time)."""
    return offer.slices[0].departs_at.hour < RED_EYE_END_HOUR


def _score_offer(
    offer: ParsedOffer,
    min_price: float, max_price: float,
    min_duration: int, max_duration: int,
    any_non_red_eye: bool,
) -> tuple[float, list[str]]:
    """Return a (score, flags) pair for one offer.

    Score is 0–1 before penalties; higher is better.
    Normalising within the result set means the weights stay stable regardless
    of absolute price levels.
    """
    price_range = max_price - min_price or 1.0
    duration_range = max_duration - min_duration or 1.0

    norm_price = 1.0 - (offer.price - min_price) / price_range
    norm_duration = 1.0 - (offer.total_duration_minutes - min_duration) / duration_range
    score = WEIGHT_PRICE * norm_price + WEIGHT_DURATION * norm_duration

    flags: list[str] = []

    # Check each leg independently — preference is per-leg, not combined
    max_stops = max(s.stops for s in offer.slices)
    if max_stops > MAX_PREFERRED_STOPS:
        score -= PENALTY_EXCESS_STOPS * (max_stops - MAX_PREFERRED_STOPS)
        flags.append(f"{max_stops} stop(s) on one leg — over preferred max of {MAX_PREFERRED_STOPS}")

    if any(s.duration_minutes > MAX_PREFERRED_HOURS * 60 for s in offer.slices):
        score -= PENALTY_LONG_FLIGHT
        flags.append(f"over {MAX_PREFERRED_HOURS}h total travel time")

    # Only penalise red-eye if there are other options — don't punish what can't be avoided
    if _is_red_eye(offer) and any_non_red_eye:
        score -= PENALTY_RED_EYE
        flags.append("red-eye departure")

    return score, flags


def _reason(offer: ParsedOffer, cheapest_id: str, fastest_id: str) -> str:
    """One-line label summarising why this offer ranks where it does."""
    is_direct = all(sl.stops == 0 for sl in offer.slices)
    cheapest = offer.offer_id == cheapest_id
    fastest = offer.offer_id == fastest_id

    if is_direct and cheapest:
        return "cheapest direct flight"
    if is_direct and fastest:
        return "fastest direct flight"
    if cheapest:
        return "cheapest option (with stop(s))"
    if fastest:
        return "fastest itinerary"
    if is_direct:
        return "direct flight"
    return "best balance of price and duration"


def score_offers(offers: list[ParsedOffer]) -> list[ScoredOffer]:
    """Score and rank all parsed offers. Returns sorted list, best first."""
    if not offers:
        return []

    prices = [o.price for o in offers]
    durations = [o.total_duration_minutes for o in offers]
    min_price, max_price = min(prices), max(prices)
    min_duration, max_duration = min(durations), max(durations)
    any_non_red_eye = any(not _is_red_eye(o) for o in offers)

    cheapest_id = min(offers, key=lambda o: o.price).offer_id
    fastest_id = min(offers, key=lambda o: o.total_duration_minutes).offer_id

    result: list[ScoredOffer] = []
    for o in offers:
        raw_score, flags = _score_offer(
            o, min_price, max_price, min_duration, max_duration, any_non_red_eye
        )
        result.append(ScoredOffer(
            offer=o,
            score=raw_score,
            reason=_reason(o, cheapest_id, fastest_id),
            flags=flags,
        ))

    result.sort(key=lambda s: s.score, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Duffel API calls
# ---------------------------------------------------------------------------

def _duffel_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Duffel-Version": DUFFEL_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _create_offer_request(api_key: str, origin: str, destination: str,
                          depart_date: str,
                          return_date: Optional[str] = None) -> str:
    """POST an offer request to Duffel and return the offer_request_id."""
    slices = [{"origin": origin, "destination": destination,
                "departure_date": depart_date}]
    if return_date:
        slices.append({"origin": destination, "destination": origin,
                        "departure_date": return_date})

    payload = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }
    }

    url = f"{DUFFEL_BASE_URL}/air/offer_requests"
    response = requests.post(url, headers=_duffel_headers(api_key),
                             json=payload, timeout=30)

    if not response.ok:
        raise RuntimeError(
            f"Error creating offer request: {response.status_code}\n{response.text}"
        )

    return response.json()["data"]["id"]


def _list_offers(api_key: str, offer_request_id: str) -> list:
    """GET all offers for a given offer_request_id."""
    url = f"{DUFFEL_BASE_URL}/air/offers"
    params = {"offer_request_id": offer_request_id, "sort": "total_amount"}
    response = requests.get(url, headers=_duffel_headers(api_key),
                            params=params, timeout=30)

    if not response.ok:
        raise RuntimeError(
            f"Error fetching offers: {response.status_code}\n{response.text}"
        )

    offers = response.json()["data"]
    if not offers:
        raise RuntimeError(
            "No offers returned for this route and date. Try different dates."
        )

    return offers


def _search_flights(api_key: str, origin: str, destination: str,
                    depart_date: str,
                    return_date: Optional[str] = None) -> list:
    """Search Duffel for flights and return raw offer objects."""
    offer_request_id = _create_offer_request(
        api_key, origin, destination, depart_date, return_date
    )
    return _list_offers(api_key, offer_request_id)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    """Load the Duffel API key from .env; raise RuntimeError if missing."""
    load_dotenv()
    key = os.getenv("DUFFEL_API_KEY")
    if not key:
        raise RuntimeError(
            "DUFFEL_API_KEY not found.\n"
            "Copy .env.example to .env and paste your Duffel API key into it."
        )
    return key


# ---------------------------------------------------------------------------
# Public pipeline entry point
# ---------------------------------------------------------------------------

def find_best_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
) -> SearchResult:
    """Run the full search → parse → score pipeline and return ranked results.

    Raises RuntimeError on API failure, missing API key, or no real offers found.
    """
    api_key = load_api_key()
    raw_offers = _search_flights(api_key, origin, destination, depart_date, return_date)

    offers, sandbox_filtered = parse_offers(raw_offers)
    if not offers:
        raise RuntimeError(
            "No real offers found after filtering sandbox results. "
            "If you're using a test API key, all results may be sandbox-only."
        )

    offers, codeshares_removed = dedupe_codeshares(offers)
    scored = score_offers(offers)

    return SearchResult(
        scored_offers=scored,
        sandbox_filtered=sandbox_filtered,
        codeshares_removed=codeshares_removed,
    )
