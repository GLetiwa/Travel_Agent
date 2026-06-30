"""
Flight Research & Recommendation Agent — CLI entry point.
All search/parse/score logic lives in flights.py; this file handles
argument parsing and terminal output only.
"""

import argparse
import sys

from flights import (
    MAX_RESULTS_SHOWN,
    SliceInfo,
    ScoredOffer,
    SearchResult,
    find_best_flights,
)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search and rank flights via the Duffel API."
    )
    parser.add_argument("--from", dest="origin", required=True, metavar="IATA",
                        help="Departure airport code (e.g. NBO)")
    parser.add_argument("--to", dest="destination", required=True, metavar="IATA",
                        help="Arrival airport code (e.g. LHR)")
    parser.add_argument("--depart", required=True, metavar="YYYY-MM-DD",
                        help="Outbound departure date")
    parser.add_argument("--return", dest="return_date", default=None,
                        metavar="YYYY-MM-DD",
                        help="Return date (omit for one-way)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _fmt_duration(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _fmt_arrives(sl: SliceInfo) -> str:
    """Format arrival time with a +N day marker when the date rolls over."""
    day_diff = (sl.arrives_at.date() - sl.departs_at.date()).days
    suffix = f" +{day_diff}" if day_diff > 0 else ""
    return sl.arrives_at.strftime('%H:%M') + suffix


def _print_summary(result: SearchResult) -> None:
    """Two-line header: counts, cheapest, and fastest at a glance."""
    scored = result.scored_offers
    direct_count = sum(1 for s in scored if all(sl.stops == 0 for sl in s.offer.slices))
    cheapest = min(scored, key=lambda s: s.offer.price)
    fastest = min(scored, key=lambda s: s.offer.slices[0].duration_minutes)
    cur = cheapest.offer.currency

    dedup_note = (
        f"  ({result.codeshares_removed} codeshare duplicate(s) hidden)"
        if result.codeshares_removed else ""
    )
    print(f"{len(scored)} unique option(s) · {direct_count} direct{dedup_note}")

    def _airline(s: ScoredOffer) -> str:
        return s.offer.slices[0].airlines[0]

    def _is_direct(s: ScoredOffer) -> str:
        return "direct" if all(sl.stops == 0 for sl in s.offer.slices) else "with stop(s)"

    print(
        f"Cheapest : {cur} {cheapest.offer.price:.2f}  ({_airline(cheapest)}, {_is_direct(cheapest)})\n"
        f"Fastest  : {_fmt_duration(fastest.offer.slices[0].duration_minutes)}"
        f"  ({_airline(fastest)}, {_is_direct(fastest)})"
    )
    print()


def _print_results(scored: list[ScoredOffer]) -> None:
    """Print top MAX_RESULTS_SHOWN ranked offers with reason and warnings."""
    if not scored:
        print("No offers to display.")
        return

    shown = scored[:MAX_RESULTS_SHOWN]
    is_round_trip = len(shown[0].offer.slices) > 1
    slice_labels = ["OUT", "RET"] if is_round_trip else ["   "]

    for rank, s in enumerate(shown, start=1):
        offer = s.offer
        header = "★ #1 — RECOMMENDED" if rank == 1 else f"  #{rank}"
        print(header)
        print(f"   {offer.currency} {offer.price:>8.2f}")

        for i, sl in enumerate(offer.slices):
            label = slice_labels[i] if i < len(slice_labels) else "   "
            stops_str = "direct" if sl.stops == 0 else f"{sl.stops} stop{'s' if sl.stops > 1 else ''}"
            print(
                f"   {label}  {sl.departs_at.strftime('%H:%M')} → {_fmt_arrives(sl)}  |  "
                f"{_fmt_duration(sl.duration_minutes)}  |  "
                f"{stops_str}  |  "
                f"{', '.join(sl.airlines)}"
            )
            if sl.layovers:
                layover_detail = ", ".join(
                    f"{lv.airport} ({_fmt_duration(lv.duration_minutes)})"
                    for lv in sl.layovers
                )
                print(f"        via {layover_detail}")

        bags = []
        if offer.checked_bags:
            bags.append(f"{offer.checked_bags} checked")
        if offer.carry_on_bags:
            bags.append(f"{offer.carry_on_bags} carry-on")
        if bags:
            print(f"   bags: {', '.join(bags)}")

        print(f"   → {s.reason}")
        for flag in s.flags:
            print(f"   ⚠  {flag}")
        print()

    remaining = len(scored) - len(shown)
    if remaining > 0:
        print(f"  ... and {remaining} more option(s) not shown "
              f"(ranked #{len(shown) + 1}–#{len(scored)}).")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    print(f"Searching flights: {args.origin} → {args.destination}")
    print(f"  Depart : {args.depart}")
    if args.return_date:
        print(f"  Return : {args.return_date}")
    print()

    try:
        result = find_best_flights(
            args.origin, args.destination,
            args.depart, args.return_date,
        )
    except RuntimeError as e:
        sys.exit(str(e))

    if result.sandbox_filtered:
        print(f"Note: filtered out {result.sandbox_filtered} sandbox offer(s) "
              f"(Duffel Airways / ZZ — not real flights)\n")

    _print_summary(result)
    _print_results(result.scored_offers)


if __name__ == "__main__":
    main()
