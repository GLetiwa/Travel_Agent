"""
Notion API client: exports ranked flight offers to a Notion database.
Uses requests directly, consistent with how the Duffel API is called.
"""

import os
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


def _para(text: str) -> dict:
    """Build a Notion paragraph block from a plain text string."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _build_page_payload(
    offer: dict,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str],
    database_id: str,
) -> dict:
    """Build the Notion API payload for one offer (one database row)."""
    # Collect unique airline names across all slices (preserving order)
    airlines = list(dict.fromkeys(
        a for sl in offer["slices"] for a in sl["airlines"]
    ))
    airlines_str = ", ".join(airlines)

    price_str = f"{offer['currency']} {offer['price']:,.0f}"
    route = f"{origin} → {destination}"
    dates = depart_date + (f" / {return_date}" if return_date else "")

    is_direct = all(sl["stops"] == 0 for sl in offer["slices"])
    stops_str = "Direct" if is_direct else f"{offer['slices'][0]['stops']} stop(s)"
    duration_str = _fmt_dur(offer["total_duration_minutes"])

    # Row title: rank + airline + price + route — scannable at a glance
    title = f"#{offer['rank']} · {airlines_str} · {price_str} · {route}"

    body_lines = [
        f"Route: {route}  |  Dates: {dates}",
        f"Stops: {stops_str}  |  Duration: {duration_str}",
        f"Reason: {offer['reason']}",
    ]
    if offer.get("flags"):
        body_lines.append("Flags: " + "; ".join(offer["flags"]))

    return {
        "parent": {"database_id": database_id},
        "properties": {
            # "Name" is the default title property present in every Notion database
            "Name": {
                "title": [{"text": {"content": title}}]
            }
        },
        "children": [_para(line) for line in body_lines],
    }


def export_offers_to_notion(
    offers: list,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
) -> int:
    """Export the top 5 offers to the configured Notion database.

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

    for offer in top5:
        payload = _build_page_payload(
            offer, origin, destination, depart_date, return_date, database_id
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
