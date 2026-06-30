"""
Notion API client: exports ranked flight offers to a Notion database.
Uses requests directly, consistent with how the Duffel API is called.
"""

import os
from datetime import date
from typing import Optional

import requests
from dotenv import load_dotenv

NOTION_API_BASE = "https://api.notion.com/v1"
# Notion requires this header on every request — use the latest stable version
NOTION_VERSION = "2022-06-28"


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _fmt_dur(mins: int) -> str:
    return f"{mins // 60}h {mins % 60:02d}m"


def _rich_text(value: str) -> list:
    """Notion's rich_text property format wraps a string in a list."""
    return [{"text": {"content": value}}]


def _build_page_payload(
    offer: dict,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str],
    search_date: str,
    database_id: str,
) -> dict:
    """Build the Notion API payload for one offer (one database row)."""
    airlines = list(dict.fromkeys(
        a for sl in offer["slices"] for a in sl["airlines"]
    ))
    airlines_str = ", ".join(airlines)

    route = f"{origin} → {destination}"
    total_stops = sum(sl["stops"] for sl in offer["slices"])
    duration_str = _fmt_dur(offer["total_duration_minutes"])
    price_str = f"{offer['currency']} {offer['price']:,.0f}"

    # e.g. "NBO→LHR, depart 2026-08-10 / return 2026-08-20" or "NBO→LHR, depart 2026-08-10"
    route_dates = f"{origin}→{destination}, depart {depart_date}"
    if return_date:
        route_dates += f" / return {return_date}"

    return {
        "parent": {"database_id": database_id},
        "properties": {
            "Name":               {"title":     _rich_text(f"#{offer['rank']} · {airlines_str}")},
            "Route":              {"rich_text": _rich_text(route)},
            "Price":              {"rich_text": _rich_text(price_str)},
            "Stops":              {"number":    total_stops},
            "Duration":           {"rich_text": _rich_text(duration_str)},
            "Reason":             {"rich_text": _rich_text(offer["reason"])},
            "Search Date":        {"date":      {"start": search_date}},
            "Search Route+Dates": {"rich_text": _rich_text(route_dates)},
        },
    }


def export_offers_to_notion(
    offers: list,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
) -> int:
    """Export the top 5 offers to the configured Notion database.

    Rows are inserted in reverse rank order (5 → 1) so that Notion's
    default newest-first display shows rank #1 at the top.

    Returns the number of rows created.
    Raises RuntimeError if config is missing or any Notion API call fails.
    """
    load_dotenv()
    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not database_id:
        raise RuntimeError(
            "NOTION_API_KEY and NOTION_DATABASE_ID must be set in .env "
            "(and as environment variables on Render)."
        )

    top5 = offers[:5]
    headers = _notion_headers(api_key)
    url = f"{NOTION_API_BASE}/pages"

    search_date = date.today().isoformat()  # e.g. "2026-06-30"

    # Insert lowest-ranked first so that Notion's newest-first default
    # display puts rank #1 at the top without requiring any manual sorting.
    for offer in reversed(top5):
        payload = _build_page_payload(
            offer, origin, destination, depart_date, return_date, search_date, database_id
        )
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if not resp.ok:
            # Surface enough detail to distinguish a missing-share error from
            # anything else — "object not found" almost always means the
            # integration wasn't shared with this database in Notion.
            raise RuntimeError(
                f"Notion API error for rank {offer['rank']}: "
                f"{resp.status_code} — {resp.text[:300]}"
            )

    return len(top5)
