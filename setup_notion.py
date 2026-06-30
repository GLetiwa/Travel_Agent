"""
One-time setup script: configures the Notion database columns for flight exports.

Run once from the terminal:
    python3 setup_notion.py

Safe to re-run — Notion updates existing properties and ignores ones that
haven't changed, so running it twice won't duplicate anything.
"""

import os
import sys

import requests
from dotenv import load_dotenv

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def main() -> None:
    load_dotenv()
    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not database_id:
        print("ERROR: NOTION_API_KEY and NOTION_DATABASE_ID must be set in .env")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    properties = {
        # Columns to remove (set to null deletes them)
        "Rank":     None,
        "Airline":  None,
        "Currency": None,

        # Columns to keep or create
        # Price was previously a number — redefining as rich_text to include currency
        "Route":    {"rich_text": {}},
        "Price":    {"rich_text": {}},
        "Stops":    {"number":    {"format": "number"}},
        "Duration": {"rich_text": {}},
        "Reason":   {"rich_text": {}},
    }

    print(f"Patching database {database_id} …")
    resp = requests.patch(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=headers,
        json={"properties": properties},
        timeout=15,
    )

    if not resp.ok:
        print(f"ERROR {resp.status_code}: {resp.text[:400]}")
        sys.exit(1)

    print("Done.")
    print("  Removed:  Rank, Airline, Currency")
    print("  Kept/set: Route, Price, Stops, Duration, Reason")
    print()
    print("Note: drag 'Route' to the first column in Notion's UI —")
    print("column order can't be set via the API.")


if __name__ == "__main__":
    main()
