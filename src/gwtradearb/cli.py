"""CLI: fetch, parse, match, and persist. Never automates Guild Wars.

`potential_difference` is a chat-price spread, not executed profit.
The local SQLite file stores public trade-chat metadata only — no credentials
and no paid/received amounts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from gwtradearb import __version__
from gwtradearb.collect import ALL_SOURCES, collect
from gwtradearb.database import (
    MAX_MATCH_LOOKBACK_HOURS,
    MIN_MATCH_LOOKBACK_HOURS,
    default_db_path,
    listings_in_lookback_window,
    list_opportunities,
    open_db,
    persist_scan,
    set_match_lookback_hours,
    set_status,
    stats,
)
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


def _format_stored_opportunity(row) -> str:
    return (
        f"[{row['status']:<9}] +{row['potential_difference']} gold  "
        f"{row['item_canonical']} x{row['quantity']} {row['quantity_unit']}  "
        f"{row['seller']} → {row['buyer']}  "
        f"key={row['opportunity_key'][:12]}"
    )


def _format_stats(payload: dict) -> str:
    return (
        f"scans={payload['scans']}  listings={payload['listings']} "
        f"(last_scan={payload['listings_last_scan']})\n"
        f"opportunities={payload['opportunities']}  "
        f"new={payload['new']} traded={payload['traded']} "
        f"dismissed={payload['dismissed']} expired={payload['expired']}"
    )


def _parse_lookback_hours(value: str) -> int:
    try:
        hours = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lookback hours must be an integer") from exc
    if hours < MIN_MATCH_LOOKBACK_HOURS:
        raise argparse.ArgumentTypeError(
            f"lookback must be at least {MIN_MATCH_LOOKBACK_HOURS} hours (got {hours})"
        )
    if hours > MAX_MATCH_LOOKBACK_HOURS:
        raise argparse.ArgumentTypeError(
            f"lookback must be at most {MAX_MATCH_LOOKBACK_HOURS} hours (got {hours})"
        )
    return hours


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwtradearb",
        description=(
            "Fetch Kamadan public trade JSON, parse WTS/WTB listing atoms, "
            "match gold opportunities, and optionally persist them locally. "
            "Does not interact with Guild Wars."
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
        help="After parsing, run the WTS/WTB matcher and print opportunities.",
    )
    parser.add_argument(
        "--listings",
        action="store_true",
        help="With --match/--scan, also print listing atoms.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist listings and opportunities to the local SQLite file.",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Fetch, parse, match, and save (implies --match --save).",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="SQLite file (default: platform user-data dir, or GWTRADEARB_DB).",
    )
    parser.add_argument(
        "--lookback-hours",
        type=_parse_lookback_hours,
        metavar="HOURS",
        help=(
            "Match listings stored in local SQLite whose chat timestamp is "
            f"within this many hours (default {MIN_MATCH_LOOKBACK_HOURS}, "
            f"minimum {MIN_MATCH_LOOKBACK_HOURS}, maximum {MAX_MATCH_LOOKBACK_HOURS}). "
            "Live APIs are not paginated; older rows come from the local DB. "
            "Stored in settings and used by Scan Now / auto-scan."
        ),
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print DB counts (no profit total). Does not fetch unless --scan.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List persisted opportunities (does not fetch). Filter with --status.",
    )
    parser.add_argument(
        "--status",
        dest="list_status",
        choices=("new", "traded", "dismissed", "expired", "all"),
        default=None,
        help="Status filter for --list (default: new).",
    )
    parser.add_argument(
        "--mark",
        nargs=2,
        metavar=("KEY", "STATUS"),
        help="Set an opportunity status (traded, dismissed, new, expired). Prefix ok.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Dump output as JSON.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the desktop UI (default when no other action flags are given).",
    )
    parser.add_argument("--version", action="version", version=f"GWTradeArb {__version__}")
    return parser


def _wants_gui(args: argparse.Namespace) -> bool:
    if args.gui:
        return True
    cli_action = any(
        (
            args.scan,
            args.save,
            args.match,
            args.search,
            args.high_only,
            args.listings,
            args.stats,
            args.list,
            args.mark is not None,
            args.as_json,
        )
    )
    return not cli_action


def _should_fetch(args: argparse.Namespace) -> bool:
    if args.scan or args.save or args.match or args.search:
        return True
    reading = args.stats or args.list or args.mark is not None
    return not reading


def _list_filter(args: argparse.Namespace) -> str | None:
    if not args.list:
        return None
    return args.list_status or "new"


def _configure_stdio() -> None:
    """Frozen Windows consoles default to cp1252; keep CLI output from crashing."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            continue


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    db_path = args.db or default_db_path()

    if _wants_gui(args):
        try:
            from gwtradearb.ui.window import run_gui
        except ImportError:
            print(
                "PySide6 is required for the GUI. Install with: pip install PySide6",
                file=sys.stderr,
            )
            return 2
        if args.lookback_hours is not None:
            with open_db(db_path) as conn:
                set_match_lookback_hours(conn, args.lookback_hours)
        return run_gui(db_path)

    now = time.time()
    now_s = int(now)
    payload: dict = {}
    exit_code = 0

    if args.mark:
        key, status = args.mark
        try:
            with open_db(db_path) as conn:
                resolved = set_status(conn, key, status, now_unix_s=now_s)
        except (KeyError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        payload["marked"] = {"opportunity_key": resolved, "status": status}
        if not args.as_json:
            print(f"marked {resolved[:12]}… → {status}")

    if _should_fetch(args):
        sources = ALL_SOURCES if args.source == "both" else (args.source,)
        started = int(time.time())
        result = collect(sources=sources, query=args.search)
        finished = int(time.time())
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)

        do_match = args.match or args.save or args.scan
        listings = result.high_listings if args.high_only else result.listings
        high = len(result.high_listings)
        low = len(result.listings) - high
        show_listings = (not do_match) or args.listings

        saved = None
        opportunities: list[Opportunity] = []
        lookback_hours = None
        lookback_listings = None
        if args.save or args.scan:
            with open_db(db_path) as conn:
                if args.lookback_hours is not None:
                    set_match_lookback_hours(conn, args.lookback_hours)
                saved = persist_scan(
                    conn,
                    listings=result.listings,
                    requested_sources=sources,
                    fetched_from=result.fetched_from,
                    message_count=len(result.messages),
                    errors=result.errors,
                    query=args.search,
                    started_at_unix_s=started,
                    finished_at_unix_s=finished,
                    lookback_hours=args.lookback_hours,
                )
                saved["db_path"] = str(db_path)
            opportunities = saved.pop("matched_opportunities", []) or []
            lookback_hours = saved.get("lookback_hours")
            lookback_listings = saved.get("lookback_listings")
        elif do_match:
            if args.lookback_hours is not None:
                with open_db(db_path) as conn:
                    hours = set_match_lookback_hours(conn, args.lookback_hours)
                    window = listings_in_lookback_window(
                        conn,
                        now_unix_s=finished,
                        lookback_hours=hours,
                        extra=result.listings,
                    )
                    opportunities = match_listings(window)
                    lookback_hours = hours
                    lookback_listings = len(window)
            else:
                opportunities = match_listings(result.listings)

        if args.as_json:
            payload.update(
                {
                    "fetched_from": result.fetched_from,
                    "message_count": len(result.messages),
                    "high": high,
                    "low": low,
                    "errors": result.errors,
                    "db_path": str(db_path) if saved else None,
                    "saved": saved,
                    "lookback_hours": lookback_hours,
                    "lookback_listings": lookback_listings,
                }
            )
            if show_listings:
                payload["listings"] = [row.to_dict() for row in listings]
            if do_match:
                payload["opportunities"] = [row.to_dict() for row in opportunities]
                payload["opportunity_count"] = len(opportunities)
        else:
            summary = (
                f"sources={','.join(result.fetched_from) or 'none'}  "
                f"messages={len(result.messages)}  listings={len(result.listings)} "
                f"(high={high} low={low})"
            )
            if do_match:
                summary += f"  opportunities={len(opportunities)}"
            if lookback_hours is not None:
                summary += f"  lookback={lookback_hours}h"
                if lookback_listings is not None:
                    summary += f"  stored={lookback_listings}"
            if saved:
                summary += f"  saved={db_path}"
                if saved["expired"]:
                    summary += f"  expired={saved['expired']}"
            print(summary)
            if show_listings:
                for listing in listings:
                    print(_format_listing(listing))
                if not listings:
                    print("no listings to display")
            if do_match:
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
            exit_code = 1

    if _list_filter(args) is not None or args.stats:
        with open_db(db_path) as conn:
            if args.stats:
                payload["stats"] = stats(conn)
                if not args.as_json:
                    print(_format_stats(payload["stats"]))
            listed_status = _list_filter(args)
            if listed_status is not None:
                rows = list_opportunities(conn, listed_status)
                payload["listed"] = [dict(row) for row in rows]
                payload["list_status"] = listed_status
                if not args.as_json:
                    if not rows:
                        print(f"no {listed_status} opportunities in {db_path}")
                    for row in rows:
                        print(_format_stored_opportunity(row))

    if args.as_json:
        if "db_path" not in payload:
            payload["db_path"] = str(db_path)
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
