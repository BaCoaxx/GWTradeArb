"""Pure display helpers shared by CLI tests and the GUI (no Qt import)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

SOURCE_HOME_URLS = {
    "decltype": "https://kamadan.decltype.org/",
    "gwtoolbox": "https://kamadan.gwtoolbox.com/",
}

SOURCE_LABELS = {
    "decltype": "Decltype",
    "gwtoolbox": "GWToolbox",
}

SCAN_INTERVALS: tuple[tuple[str, int], ...] = (
    ("Manual", 0),
    ("1 min", 60),
    ("5 min", 300),
    ("10 min", 600),
    ("30 min", 1800),
)


def format_gold(amount: Decimal | str | int | None) -> str:
    if amount is None or amount == "":
        return "—"
    try:
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return str(amount)
    if value == value.to_integral_value() and value >= 1000 and value % 1000 == 0:
        return f"{int(value / 1000)}k gold"
    if value == value.to_integral_value():
        return f"{int(value)} gold"
    return f"{value} gold"


def format_detected(unix_s: int | None) -> str:
    if not unix_s:
        return "—"
    return datetime.fromtimestamp(int(unix_s), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def parse_sources(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(data, list):
        return [str(item) for item in data]
    return [str(data)]


def format_sources(raw: str | None) -> str:
    labels = [SOURCE_LABELS.get(name, name) for name in parse_sources(raw)]
    return ", ".join(labels) if labels else "—"


def row_matches_filters(
    row: dict,
    *,
    item_query: str = "",
    source: str = "all",
    min_difference: Decimal | None = None,
) -> bool:
    if item_query:
        needle = item_query.casefold().strip()
        hay = " ".join(
            str(row.get(key) or "")
            for key in ("item_canonical", "seller", "buyer", "wts_item_raw", "wtb_item_raw")
        ).casefold()
        if needle not in hay:
            return False
    if source and source != "all":
        if source not in parse_sources(row.get("sources")):
            return False
    if min_difference is not None:
        try:
            value = Decimal(str(row.get("potential_difference") or "0"))
        except (InvalidOperation, ValueError):
            return False
        if value < min_difference:
            return False
    return True
