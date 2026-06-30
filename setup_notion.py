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
        # Core flight columns
        "Route":              {"rich_text": {}},
        "Price":              {"rich_text": {}},
        "Stops":              {"number":    {"format": "number"}},
        "Duration":           {"rich_text": {}},
        "Reason":             {"rich_text": {}},
        # Search identity columns (Phase 5A) — lets you trace which search produced each row
        "Search Date":        {"date":      {}},
        "Search Route+Dates": {"rich_text": {}},
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

    print("Done. Columns confirmed:")
    for name in properties:
        print(f"  • {name}")
    print()
    print("Tip: drag 'Route' to the first column in Notion's UI if needed —")
    print("column order can't be set via the API.")


if __name__ == "__main__":
    main()
