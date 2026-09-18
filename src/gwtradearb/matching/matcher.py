"""Deterministic WTS↔WTB matcher.

False positives are worse than misses. No LLM. Gold only. Never automates Guild Wars.

Phase 2 stores `price_amount` as the **parsed price token** for a listing:
  * `WTS shield 50k`            → qty 1, 50000 gold (per item)
  * `WTB ectos 13k/ea`          → qty 1, 13000 gold (per item)
  * `WTB ectos 13k/ea x5`       → qty 5, 13000 gold (per item; /ea)
  * `WTB Ectos 8 for 100k`      → qty 8, 100000 gold (lot for 8)
  * `wts 8 ectos 100k`          → qty 8, 100000 gold (lot for 8)

The matcher converts both sides to a per-item gold figure, then reports
`sell_price` / `buy_price` / `potential_difference` as gold **for the fill
quantity**, not as a promise of executed profit.

Lots are all-or-nothing (an `8 for 100k` line is not split into 1-of-8).
Each-priced lines may partial-fill down to 1.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from decimal import Decimal

from gwtradearb.fingerprint import normalise_player
from gwtradearb.matching.aliases import canonical_item
from gwtradearb.models.listing import Listing, QuantityUnit
from gwtradearb.models.opportunity import Opportunity

PriceBasis = str  # "each" | "lot"

_BUNDLE_HINT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:\d+(?:[.,]\d+)?\s*[eE]\s*/\s*\d+(?:[.,]\d+)?\s*[kK]"
    r"|\d+(?:[.,]\d+)?\s*/\s*\d+(?:[.,]\d+)?\s*[kK]"
    r"|\d+(?:[.,]\d+)?\s*(?:for|=)\s*\d+(?:[.,]\d+)?\s*[kK])\b"
)
_EACH_HINT = re.compile(r"(?i)(?:/\s*)?(?:ea|each)\b")


def price_basis(listing: Listing) -> PriceBasis:
    """How to read Phase 2 `price_amount` relative to `quantity`."""
    span = listing.raw_span or ""
    if _BUNDLE_HINT.search(span):
        return "lot"
    if listing.quantity == 1:
        return "each"
    if _EACH_HINT.search(span):
        return "each"
    return "lot"


def unit_price(listing: Listing) -> Decimal | None:
    """Gold per one `quantity_unit` item, or None if not computable."""
    if listing.price_amount is None or listing.quantity is None or listing.quantity < 1:
        return None
    if price_basis(listing) == "each":
        return listing.price_amount
    return listing.price_amount / Decimal(listing.quantity)


def fill_quantity(wts: Listing, wtb: Listing) -> int | None:
    """Largest overlapping qty both sides can honour without inventing a split lot."""
    if wts.quantity is None or wtb.quantity is None:
        return None
    if wts.quantity < 1 or wtb.quantity < 1:
        return None
    wts_basis = price_basis(wts)
    wtb_basis = price_basis(wtb)
    if wts_basis == "lot" and wtb_basis == "lot":
        return wts.quantity if wts.quantity == wtb.quantity else None
    if wts_basis == "lot" and wtb_basis == "each":
        return wts.quantity if wtb.quantity >= wts.quantity else None
    if wts_basis == "each" and wtb_basis == "lot":
        return wtb.quantity if wts.quantity >= wtb.quantity else None
    return min(wts.quantity, wtb.quantity)


def _quantity_unit(listing: Listing) -> QuantityUnit:
    return listing.quantity_unit or "each"


def _side_key(listing: Listing, item_key: str) -> str:
    """Logical identity of one side: fingerprint + intent + item (cross-source stable)."""
    return (
        f"{listing.raw.content_fingerprint}|"
        f"{listing.intent}|{item_key}|{_quantity_unit(listing)}"
    )


def opportunity_key(wts: Listing, wtb: Listing, item_key: str, fill_qty: int) -> str:
    payload = (
        f"{item_key}|{_quantity_unit(wts)}|{fill_qty}|"
        f"{_side_key(wts, item_key)}|{_side_key(wtb, item_key)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _try_pair(wts: Listing, wtb: Listing, item_key: str) -> Opportunity | None:
    if not wts.is_matchable or not wtb.is_matchable:
        return None
    if wts.intent != "WTS" or wtb.intent != "WTB":
        return None
    if wts.price_unit != "gold" or wtb.price_unit != "gold":
        return None
    if _quantity_unit(wts) != _quantity_unit(wtb):
        return None
    if normalise_player(wts.raw.player) == normalise_player(wtb.raw.player):
        return None
    if wts.raw.content_fingerprint == wtb.raw.content_fingerprint:
        return None

    fill_qty = fill_quantity(wts, wtb)
    if fill_qty is None or fill_qty < 1:
        return None

    wts_unit = unit_price(wts)
    wtb_unit = unit_price(wtb)
    if wts_unit is None or wtb_unit is None:
        return None
    if wts_unit >= wtb_unit:
        return None

    sell_price = wts_unit * Decimal(fill_qty)
    buy_price = wtb_unit * Decimal(fill_qty)
    difference = buy_price - sell_price
    if difference <= 0:
        return None

    sources = tuple(sorted({wts.raw.source, wtb.raw.source}))
    return Opportunity(
        item=item_key,
        quantity=fill_qty,
        quantity_unit=_quantity_unit(wts),
        seller=wts.raw.player,
        buyer=wtb.raw.player,
        wts=wts,
        wtb=wtb,
        sell_price=sell_price,
        buy_price=buy_price,
        potential_difference=difference,
        price_unit="gold",
        opportunity_key=opportunity_key(wts, wtb, item_key, fill_qty),
        wts_timestamp_unix_s=wts.raw.timestamp_unix_s,
        wtb_timestamp_unix_s=wtb.raw.timestamp_unix_s,
        sources=sources,
    )


def match_listings(listings: list[Listing]) -> list[Opportunity]:
    """Return unique gold WTS↔WTB opportunities, freshest first.

    Input may include low-confidence rows; they are ignored.
    """
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if not listing.is_matchable or not listing.item:
            continue
        key = canonical_item(listing.item)
        if not key:
            continue
        grouped[key].append(listing)

    found: list[Opportunity] = []
    for item_key, group in grouped.items():
        sellers = [row for row in group if row.intent == "WTS"]
        buyers = [row for row in group if row.intent == "WTB"]
        for wts in sellers:
            for wtb in buyers:
                opportunity = _try_pair(wts, wtb, item_key)
                if opportunity is not None:
                    found.append(opportunity)

    best: dict[str, Opportunity] = {}
    for opportunity in found:
        previous = best.get(opportunity.opportunity_key)
        if previous is None or opportunity.freshness_unix_s > previous.freshness_unix_s:
            best[opportunity.opportunity_key] = opportunity

    return sorted(
        best.values(),
        key=lambda row: (
            -row.freshness_unix_s,
            -row.potential_difference,
            row.opportunity_key,
        ),
    )
