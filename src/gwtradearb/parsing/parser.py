"""Deterministic gold-first Kamadan trade-line parser.

No LLM. Prefer fewer high-confidence listings over many guesses.

High confidence (later matchable) requires ALL of:
  * intent is WTS or WTB (never WTT)
  * a non-empty item string
  * a quantity (default 1 when a single price is present)
  * exactly one gold price (`Nk`, `Ng`)
Ecto (`e`) and armbrace (`a`) amounts are extracted and tagged as those units
but are never high-confidence in Phase 2 — they are not gold-comparable yet.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from gwtradearb.models import Intent, Listing, PriceUnit, QuantityUnit, RawMessage

_DUMMY_RAW = RawMessage(
    source="decltype",
    native_id="synthetic",
    timestamp_unix_s=0,
    player="synthetic",
    message="",
)

INTENT_RE = re.compile(r"\b(WTS|WTB|WTT)\b", re.IGNORECASE)
NUMBER = r"(\d+(?:[.,]\d+)?)"

# Bundle rates: "8 for 100k", "7=100k", "7for100k", "8e/100k", "8/100k"
BUNDLE_E_SLASH_K = re.compile(
    rf"(?i)(?<![A-Za-z0-9]){NUMBER}\s*[eE]\s*/\s*{NUMBER}\s*[kK]\b"
)
BUNDLE_SLASH_K = re.compile(
    rf"(?i)(?<![A-Za-z0-9]){NUMBER}\s*/\s*{NUMBER}\s*[kK]\b"
)
BUNDLE_FOR_OR_EQ_K = re.compile(
    rf"(?i)(?<![A-Za-z0-9]){NUMBER}\s*(?:for|=)\s*{NUMBER}\s*[kK]\b"
)
GOLD_K_RE = re.compile(rf"(?<![A-Za-z0-9]){NUMBER}\s*[kK]\b")
GOLD_G_RE = re.compile(rf"(?<![A-Za-z0-9]){NUMBER}\s*[gG]\b")
ECTO_RE = re.compile(rf"(?<![A-Za-z0-9]){NUMBER}\s*[eE]\b")
ARM_RE = re.compile(rf"(?<![A-Za-z0-9]){NUMBER}\s*[aA]\b")

QTY_PAREN_X = re.compile(r"\(\s*(\d+)\s*[xX]\s*\)")
QTY_X_PREFIX = re.compile(r"(?<![A-Za-z0-9])[xX]\s*(\d+)\b")
QTY_X_SUFFIX = re.compile(r"(?<![A-Za-z0-9])(\d+)\s*[xX]\b")
LEADING_QTY = re.compile(rf"^\s*{NUMBER}(?=\s+[A-Za-z*])")

STACK_RE = re.compile(r"(?i)(?:/\s*)?\b(?:stacks?|stks?)\b")
EACH_RE = re.compile(r"(?i)(?:/\s*)?\b(?:ea|each)\b")

NOISE_RE = re.compile(
    r"""(?ix)
    \b(
        pm(?:\s*me)?
        | pst
        | wsp(?:\s*me)?
        | whisper(?:\s*me)?
        | open\s+trade
        | trade\s+me
        | trade\s+directly
        | obo
        | please
        | pls+
        | offers?
        | your\s+price
        | wsp
        | for
        | or
        | need
    )\b
    """
)
JUNK_RE = re.compile(r"[*~]+")
EMPTY_PARENS_RE = re.compile(r"\(\s*\)")
MULTI_SPACE = re.compile(r"\s+")
EDGE_PUNCT = re.compile(r"^[\s\-–—:,;/|+.]+|[\s\-–—:,;/|+.]+$")


class _PriceHit(NamedTuple):
    start: int
    end: int
    amount: Decimal
    unit: PriceUnit


def _parse_number(raw: str) -> Decimal:
    # Kamadan uses comma as a decimal separator ("12,5k"), not thousands.
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(raw) from exc


def _maybe_integral(amount: Decimal) -> Decimal:
    integral = amount.to_integral_value()
    if amount == integral:
        return Decimal(int(integral))
    return amount


def _normalise_text(message: str) -> str:
    text = message.replace("\u2014", "-").replace("\u2013", "-").replace("\u2010", "-")
    text = text.replace("\u2212", "-")
    return MULTI_SPACE.sub(" ", text).strip()


def _split_segments(message: str) -> list[tuple[Intent | None, str]]:
    """Split a chat line on WTS/WTB/WTT and on ` -- ` (inherit prior intent)."""
    text = _normalise_text(message)
    if not text:
        return []
    matches = list(INTENT_RE.finditer(text))
    if not matches:
        return [(None, text)]

    segments: list[tuple[Intent | None, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[match.start() : end]
        intent = match.group(1).upper()
        body = chunk[match.end() - match.start() :].strip()
        body = body.lstrip(":/|").strip()
        pieces = re.split(r"\s+--\s+", body)
        first = True
        for piece in pieces:
            piece = piece.strip(" -/|")
            if not piece:
                continue
            # A `--` piece that itself starts with an intent is already a later match.
            if not first and INTENT_RE.match(piece):
                continue
            segments.append((intent, piece))  # type: ignore[arg-type]
            first = False
    return segments


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


def _find_bundle_gold(span: str) -> tuple[int | None, _PriceHit | None, str]:
    for pattern in (BUNDLE_E_SLASH_K, BUNDLE_SLASH_K, BUNDLE_FOR_OR_EQ_K):
        match = pattern.search(span)
        if not match:
            continue
        qty = int(_parse_number(match.group(1)))
        gold = _maybe_integral(_parse_number(match.group(2)) * Decimal(1000))
        hit = _PriceHit(match.start(), match.end(), gold, "gold")
        return qty, hit, _blank(span, match.start(), match.end())
    return None, None, span


def _collect_unit_prices(span: str, pattern: re.Pattern[str], unit: PriceUnit, scale: Decimal) -> list[_PriceHit]:
    hits: list[_PriceHit] = []
    for match in pattern.finditer(span):
        amount = _maybe_integral(_parse_number(match.group(1)) * scale)
        hits.append(_PriceHit(match.start(), match.end(), amount, unit))
    return hits


def _extract_prices(span: str) -> tuple[list[_PriceHit], str]:
    """Return remaining prices after bundle gold is peeled off."""
    hits: list[_PriceHit] = []
    hits.extend(_collect_unit_prices(span, GOLD_K_RE, "gold", Decimal(1000)))
    hits.extend(_collect_unit_prices(span, GOLD_G_RE, "gold", Decimal(1)))
    hits.extend(_collect_unit_prices(span, ECTO_RE, "ecto", Decimal(1)))
    hits.extend(_collect_unit_prices(span, ARM_RE, "armbrace", Decimal(1)))
    hits.sort(key=lambda h: h.start)

    # Overlapping matches: prefer the longest (e.g. drop `8e` when `8e/100k` already gone).
    filtered: list[_PriceHit] = []
    for hit in hits:
        if any(hit.start < kept.end and hit.end > kept.start for kept in filtered):
            continue
        # `30e/ea`: ecto `30e` is wanted; do not also treat stray letters as prices.
        filtered.append(hit)

    remaining = span
    for hit in sorted(filtered, key=lambda h: h.start, reverse=True):
        remaining = _blank(remaining, hit.start, hit.end)
    return filtered, remaining


def _extract_quantity_markers(span: str) -> tuple[int | None, QuantityUnit | None, str, bool]:
    """Pull x2 / (5x) / leading count / /ea / /stack. Returns (qty, unit, rest, had_each)."""
    rest = span
    qty: int | None = None
    unit: QuantityUnit | None = None
    had_each = False

    def take(pattern: re.Pattern[str], group: int = 1) -> int | None:
        nonlocal rest
        match = pattern.search(rest)
        if not match:
            return None
        value = int(match.group(group))
        rest = _blank(rest, match.start(), match.end())
        return value

    paren = take(QTY_PAREN_X)
    prefix = take(QTY_X_PREFIX)
    suffix = take(QTY_X_SUFFIX)

    stack_match = STACK_RE.search(rest)
    if stack_match:
        unit = "stack"
        rest = _blank(rest, stack_match.start(), stack_match.end())

    each_match = EACH_RE.search(rest)
    if each_match:
        had_each = True
        unit = unit or "each"
        rest = _blank(rest, each_match.start(), each_match.end())

    leading_match = LEADING_QTY.search(rest)
    leading: int | None = None
    if leading_match:
        leading_num = _parse_number(leading_match.group(1))
        if leading_num == leading_num.to_integral_value() and leading_num >= 1:
            leading = int(leading_num)
            rest = _blank(rest, leading_match.start(), leading_match.end())

    # Prefer explicit deal size (leading count, e.g. "8 ectos") over a trailing (5x) lot marker.
    for candidate in (leading, prefix, suffix, paren):
        if candidate is not None and candidate >= 1:
            qty = candidate
            break

    return qty, unit, rest, had_each


def _clean_item(text: str) -> str | None:
    cleaned = NOISE_RE.sub(" ", text)
    cleaned = EMPTY_PARENS_RE.sub(" ", cleaned)
    cleaned = JUNK_RE.sub(" ", cleaned)
    cleaned = MULTI_SPACE.sub(" ", cleaned)
    cleaned = EDGE_PUNCT.sub("", cleaned)
    cleaned = MULTI_SPACE.sub(" ", cleaned).strip()
    if len(cleaned) < 2:
        return None
    if INTENT_RE.fullmatch(cleaned):
        return None
    return cleaned


def _confidence_and_reasons(
    *,
    intent: Intent | None,
    item: str | None,
    quantity: int | None,
    price_amount: Decimal | None,
    price_unit: PriceUnit | None,
    extra_prices: int,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if intent is None:
        reasons.append("no_intent")
    elif intent == "WTT":
        reasons.append("wtt_not_matchable")
    if not item:
        reasons.append("missing_item")
    if quantity is None or quantity < 1:
        reasons.append("missing_quantity")
    if price_amount is None or price_unit is None:
        reasons.append("missing_price")
    elif price_unit != "gold":
        reasons.append("non_gold_price")
    if extra_prices:
        reasons.append("multiple_prices")

    high = (
        intent in {"WTS", "WTB"}
        and item is not None
        and quantity is not None
        and quantity >= 1
        and price_amount is not None
        and price_unit == "gold"
        and extra_prices == 0
    )
    return ("high" if high else "low"), tuple(reasons)


def _parse_span(raw: RawMessage, intent: Intent | None, span: str) -> Listing | None:
    if not span.strip():
        return None

    bundle_qty, bundle_price, after_bundle = _find_bundle_gold(span)
    prices, after_prices = _extract_prices(after_bundle)
    extra_prices = 0
    price_amount: Decimal | None = None
    price_unit: PriceUnit | None = None

    if bundle_price is not None:
        # Gold bundle wins. Ignore leftover e/a decorations such as "(120e)".
        # A second gold figure in the same span is ambiguous.
        price_amount = bundle_price.amount
        price_unit = "gold"
        extra_prices = sum(1 for hit in prices if hit.unit == "gold")
    elif len(prices) == 1:
        price_amount = prices[0].amount
        price_unit = prices[0].unit
    elif len(prices) > 1:
        # Same-intent grocery list: do not pick a winner.
        extra_prices = len(prices)

    qty, qty_unit, after_qty, _had_each = _extract_quantity_markers(after_prices)
    if bundle_qty is not None:
        # Bundle size is the comparable quantity ("8 for 100k"); (5x) is a lot count.
        qty = bundle_qty

    if qty is None and price_amount is not None:
        qty = 1
        qty_unit = qty_unit or "each"
    elif qty is not None:
        qty_unit = qty_unit or "each"

    item = _clean_item(after_qty)
    confidence, reasons = _confidence_and_reasons(
        intent=intent,
        item=item,
        quantity=qty,
        price_amount=price_amount,
        price_unit=price_unit,
        extra_prices=extra_prices,
    )

    if intent is None and item is None and price_amount is None:
        return None

    # Pure chatter with no trade intent is not a listing atom.
    if intent is None:
        return None

    return Listing(
        raw=raw,
        intent=intent,
        item=item,
        quantity=qty,
        quantity_unit=qty_unit,
        price_amount=price_amount,
        price_unit=price_unit,
        parse_confidence=confidence,
        raw_span=span,
        reasons=reasons,
    )


def parse_message(raw: RawMessage) -> list[Listing]:
    """Parse one public chat line into zero or more listing atoms."""
    listings: list[Listing] = []
    for intent, span in _split_segments(raw.message):
        listing = _parse_span(raw, intent, span)
        if listing is not None:
            listings.append(listing)
    return listings


def parse_text(message: str, *, player: str = "synthetic") -> list[Listing]:
    """Test helper: parse a raw chat string without an HTTP payload."""
    raw = RawMessage(
        source=_DUMMY_RAW.source,
        native_id=_DUMMY_RAW.native_id,
        timestamp_unix_s=_DUMMY_RAW.timestamp_unix_s,
        player=player,
        message=message,
    )
    return parse_message(raw)


def parse_messages(messages: list[RawMessage]) -> list[Listing]:
    listings: list[Listing] = []
    for raw in messages:
        listings.extend(parse_message(raw))
    return listings
