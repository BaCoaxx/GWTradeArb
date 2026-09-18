"""Smoke-test CLI: fetch public JSON, parse listings, print a summary.

Never automates Guild Wars, never sends whispers, never stores credentials.
"""

from __future__ import annotations

import argparse
import json
import sys

from gwtradearb import __version__
from gwtradearb.collect import ALL_SOURCES, collect
from gwtradearb.models import Listing


def _format_listing(listing: Listing) -> str:
    qty = listing.quantity if listing.quantity is not None else "?"
    unit = listing.quantity_unit or ""
    price = (
        f"{listing.price_amount} {listing.price_unit}"
        if listing.price_amount is not None and listing.price_unit
        else "no-price"
    )
    item = listing.item or "(no item)"
    reasons = f" [{', '.join(listing.reasons)}]" if listing.reasons else ""
    return (
        f"[{listing.parse_confidence:<4}] {listing.raw.source:<10} "
        f"{listing.intent or '----'}  {item}  x{qty} {unit}  {price}  "
        f"| {listing.raw_span}{reasons}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwtradearb",
        description=(
            "Phase 2 smoke tool: fetch Kamadan public trade JSON and parse "
            "WTS/WTB listing atoms. Does not interact with Guild Wars."
        ),
    )
    parser.add_argument(
        "--source",
        choices=("decltype", "gwtoolbox", "both"),
        default="both",
        help="Which public HTTP source to query (default: both).",
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Use the search helper instead of the live feed.",
    )
    parser.add_argument(
        "--high-only",
        action="store_true",
        help="Print only high-confidence gold listings.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Dump listings as JSON.",
    )
    parser.add_argument("--version", action="version", version=f"GWTradeArb {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sources = ALL_SOURCES if args.source == "both" else (args.source,)
    result = collect(sources=sources, query=args.search)

    for err in result.errors:
        print(f"error: {err}", file=sys.stderr)

    listings = result.high_listings if args.high_only else result.listings
    high = len(result.high_listings)
    low = len(result.listings) - high

    if args.as_json:
        payload = {
            "fetched_from": result.fetched_from,
            "message_count": len(result.messages),
            "high": high,
            "low": low,
            "errors": result.errors,
            "listings": [row.to_dict() for row in listings],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            f"sources={','.join(result.fetched_from) or 'none'}  "
            f"messages={len(result.messages)}  listings={len(result.listings)} "
            f"(high={high} low={low})"
        )
        for listing in listings:
            print(_format_listing(listing))
        if not listings:
            print("no listings to display")

    # Partial success is still success; total failure (no source worked) is an error.
    if not result.fetched_from:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
