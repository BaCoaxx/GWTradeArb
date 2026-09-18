"""Smoke-test CLI: fetch public JSON, parse listings, optionally match.

Never automates Guild Wars, never sends whispers, never stores credentials.
Listings can vanish; `potential_difference` is not executed profit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from gwtradearb import __version__
from gwtradearb.collect import ALL_SOURCES, collect
from gwtradearb.matching import match_listings
from gwtradearb.models import Listing, Opportunity


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


def _age_label(timestamp_unix_s: int, now: float) -> str:
    seconds = max(0, int(now - timestamp_unix_s))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _format_opportunity(opportunity: Opportunity, *, now: float) -> str:
    wts_age = _age_label(opportunity.wts_timestamp_unix_s, now)
    wtb_age = _age_label(opportunity.wtb_timestamp_unix_s, now)
    return (
        f"+{opportunity.potential_difference} gold  {opportunity.item}  "
        f"x{opportunity.quantity} {opportunity.quantity_unit}  "
        f"sell {opportunity.sell_price} / buy {opportunity.buy_price}\n"
        f"  WTS {opportunity.seller} ({opportunity.wts.raw.source} {wts_age})  "
        f"| {opportunity.wts.raw_span}\n"
        f"  WTB {opportunity.buyer} ({opportunity.wtb.raw.source} {wtb_age})  "
        f"| {opportunity.wtb.raw_span}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwtradearb",
        description=(
            "Fetch Kamadan public trade JSON, parse WTS/WTB listing atoms, "
            "and optionally match gold opportunities. Does not interact with Guild Wars."
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
        help="When printing listings, show only high-confidence gold rows. "
        "Matching always uses high-confidence gold only.",
    )
    parser.add_argument(
        "--match",
        action="store_true",
        help="After parsing, run the WTS↔WTB matcher and print opportunities "
        "instead of (or as well as) listing atoms.",
    )
    parser.add_argument(
        "--listings",
        action="store_true",
        help="With --match, also print listing atoms.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Dump output as JSON.",
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
    opportunities = match_listings(result.listings) if args.match else []
    now = time.time()

    show_listings = (not args.match) or args.listings

    if args.as_json:
        payload = {
            "fetched_from": result.fetched_from,
            "message_count": len(result.messages),
            "high": high,
            "low": low,
            "errors": result.errors,
        }
        if show_listings:
            payload["listings"] = [row.to_dict() for row in listings]
        if args.match:
            payload["opportunities"] = [row.to_dict() for row in opportunities]
            payload["opportunity_count"] = len(opportunities)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        summary = (
            f"sources={','.join(result.fetched_from) or 'none'}  "
            f"messages={len(result.messages)}  listings={len(result.listings)} "
            f"(high={high} low={low})"
        )
        if args.match:
            summary += f"  opportunities={len(opportunities)}"
        print(summary)
        if show_listings:
            for listing in listings:
                print(_format_listing(listing))
            if not listings:
                print("no listings to display")
        if args.match:
            if show_listings:
                print("--- opportunities ---")
            for opportunity in opportunities:
                print(_format_opportunity(opportunity, now=now))
            if not opportunities:
                print(
                    "no opportunities "
                    "(need a high-confidence gold WTS cheaper than a WTB for the same item)"
                )
            else:
                print(
                    "potential_difference is a chat-price spread, not guaranteed profit. "
                    "Execute trades manually; listings may vanish."
                )

    if not result.fetched_from:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
