# Flight Research & Recommendation Agent

Searches flights for a route you specify, scores the results against your
preferences, and prints a ranked recommendation. **You book manually** —
this tool never creates a booking.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then paste your Duffel API key into .env
```

Get a free Duffel API key at https://duffel.com — sandbox/test mode is enough
to run this tool.

## Usage

```bash
# One-way
python main.py --from NBO --to LHR --depart 2026-08-10

# Round-trip
python main.py --from NBO --to LHR --depart 2026-08-10 --return 2026-08-20
```

## Data source

[Duffel API](https://duffel.com/docs) — flight search only (read-only).
