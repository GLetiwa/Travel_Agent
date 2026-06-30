"""
One-time setup script: adds the required columns to your Notion database.

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

    # These properties map to columns in the Notion database table.
    # "Name" (title) already exists in every new database — we don't include it here.
    # Notion's PATCH endpoint adds properties that don't exist and updates ones that do.
    new_properties = {
        "Rank":     {"number":    {"format": "number"}},
        "Airline":  {"rich_text": {}},
        "Price":    {"number":    {"format": "number"}},
        "Currency": {"rich_text": {}},
        "Route":    {"rich_text": {}},
        "Stops":    {"number":    {"format": "number"}},
        "Duration": {"rich_text": {}},
        "Reason":   {"rich_text": {}},
    }

    print(f"Patching database {database_id} …")
    resp = requests.patch(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=headers,
        json={"properties": new_properties},
        timeout=15,
    )

    if not resp.ok:
        print(f"ERROR {resp.status_code}: {resp.text[:400]}")
        sys.exit(1)

    added = list(new_properties.keys())
    print(f"Done. Columns added/confirmed: {', '.join(added)}")


if __name__ == "__main__":
    main()
