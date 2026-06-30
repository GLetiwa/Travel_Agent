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

# Airline tier definitions — ranking priority: Tier 1 > Tier 2 > Tier 3 (everyone else)
TIER1_AIRLINES = {"United Airlines", "American Airlines"}
TIER2_AIRLINES = {"British Airways", "Air France"}

# Thresholds used only for display flags, not for ranking
MAX_PREFERRED_STOPS = 1   # flag anything above this
MAX_PREFERRED_HOURS = 12  # flag legs longer than this
RED_EYE_END_HOUR = 6      # departure before 06:00 counts as red-eye

MAX_RESULTS_SHOWN = 10    # ranked results printed by CLI by default


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


def _airline_tier(airlines: list[str]) -> int:
    """Return the best tier (1, 2, or 3) represented in a list of airline names."""
    if any(a in TIER1_AIRLINES for a in airlines):
        return 1
    if any(a in TIER2_AIRLINES for a in airlines):
        return 2
    return 3


def _compute_flags(offer: ParsedOffer, any_non_red_eye: bool) -> list[str]:
    """Return display-only warning flags. These do not affect ranking."""
    flags: list[str] = []
    max_stops = max(s.stops for s in offer.slices)
    if max_stops > MAX_PREFERRED_STOPS:
        flags.append(f"{max_stops} stop(s) on one leg — over preferred max of {MAX_PREFERRED_STOPS}")
    if any(s.duration_minutes > MAX_PREFERRED_HOURS * 60 for s in offer.slices):
        flags.append(f"over {MAX_PREFERRED_HOURS}h total travel time")
    # Only flag red-eye when alternatives exist — don't penalise what can't be avoided
    if _is_red_eye(offer) and any_non_red_eye:
        flags.append("red-eye departure")
    return flags


def _reason(offer: ParsedOffer, cheapest_id: str) -> str:
    """One-line label explaining why this offer ranked where it did."""
    all_airlines = [a for sl in offer.slices for a in sl.airlines]
    tier = _airline_tier(all_airlines)
    is_direct = all(sl.stops == 0 for sl in offer.slices)
    is_cheapest = offer.offer_id == cheapest_id

    tier_label = {1: "Tier 1 airline", 2: "Tier 2 airline"}.get(tier)

    parts: list[str] = []
    if tier_label:
        parts.append(tier_label)
    parts.append("direct" if is_direct else "with stop(s)")
    if is_cheapest:
        parts.append("lowest price")

    return " · ".join(parts)


def score_offers(offers: list[ParsedOffer]) -> list[ScoredOffer]:
    """Rank offers using a strict tiered/lexicographic sort.

    Priority order (never blended into a single score):
      1. Airline tier (Tier 1 > Tier 2 > Tier 3)
      2. Directness within the same tier (direct always beats indirect)
      3. Price within the same tier + directness (lower is better)
    """
    if not offers:
        return []

    any_non_red_eye = any(not _is_red_eye(o) for o in offers)
    cheapest_id = min(offers, key=lambda o: o.price).offer_id

    result: list[ScoredOffer] = []
    for o in offers:
        flags = _compute_flags(o, any_non_red_eye)
        result.append(ScoredOffer(
            offer=o,
            score=0.0,  # not used for ranking — kept for API compatibility
            reason=_reason(o, cheapest_id),
            flags=flags,
        ))

    def sort_key(s: ScoredOffer) -> tuple:
        all_airlines = [a for sl in s.offer.slices for a in sl.airlines]
        tier = _airline_tier(all_airlines)
        # True sorts after False, so is_indirect=False (direct) ranks first
        is_indirect = any(sl.stops > 0 for sl in s.offer.slices)
        return (tier, is_indirect, s.offer.price)

    result.sort(key=sort_key)
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


def search_places(api_key: str, query: str) -> list:
    """Query Duffel's places/suggestions endpoint and return a flat list of airports.

    Cities with multiple airports (e.g. London) are expanded so each airport
    appears as its own entry. Results are deduplicated by IATA code since Duffel
    sometimes returns the same airport as both a city child and a standalone entry.

    Returns a list of dicts: {name, iata_code, city_name}.
    """
    url = f"{DUFFEL_BASE_URL}/places/suggestions"
    response = requests.get(url, headers=_duffel_headers(api_key),
                            params={"query": query}, timeout=10)

    if not response.ok:
        raise RuntimeError(
            f"Places lookup failed: {response.status_code}\n{response.text}"
        )

    seen: set[str] = set()
    results: list[dict] = []

    for place in response.json().get("data", []):
        ptype = place.get("type")

        if ptype == "city":
            # Expand city into its individual airports
            for airport in (place.get("airports") or []):
                code = airport.get("iata_code", "")
                if code and code not in seen:
                    seen.add(code)
                    results.append({
                        "name": airport.get("name", ""),
                        "iata_code": code,
                        "city_name": place.get("name", ""),
                    })
        elif ptype == "airport":
            code = place.get("iata_code", "")
            if code and code not in seen:
                seen.add(code)
                results.append({
                    "name": place.get("name", ""),
                    "iata_code": code,
                    "city_name": place.get("city_name") or "",
                })

    return results


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
