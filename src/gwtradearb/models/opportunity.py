"""Phase 3 opportunity: a comparable WTS/WTB pair.

`potential_difference` is a spread on public chat prices, not guaranteed
profit and not an executed trade. Listings vanish; the user must still
whisper and trade by hand in Guild Wars. This package never automates that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from gwtradearb.models.listing import Listing, QuantityUnit


@dataclass(frozen=True, slots=True)
class Opportunity:
    """One gold WTS↔WTB pair that passed the Phase 3 matcher.

    Prices (`sell_price`, `buy_price`, `potential_difference`) are gold for
    `quantity` items (the fill lot), not per-unit quotes.
    """

    item: str
    quantity: int
    quantity_unit: QuantityUnit
    seller: str
    buyer: str
    wts: Listing
    wtb: Listing
    sell_price: Decimal
    buy_price: Decimal
    potential_difference: Decimal
    price_unit: Literal["gold"]
    opportunity_key: str
    wts_timestamp_unix_s: int
    wtb_timestamp_unix_s: int
    sources: tuple[str, ...]

    @property
    def freshness_unix_s(self) -> int:
        """Most recent timestamp on either side; used to rank fresher pairs first."""
        return max(self.wts_timestamp_unix_s, self.wtb_timestamp_unix_s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "quantity": self.quantity,
            "quantity_unit": self.quantity_unit,
            "seller": self.seller,
            "buyer": self.buyer,
            "sell_price": str(self.sell_price),
            "buy_price": str(self.buy_price),
            "potential_difference": str(self.potential_difference),
            "price_unit": self.price_unit,
            "opportunity_key": self.opportunity_key,
            "wts_timestamp_unix_s": self.wts_timestamp_unix_s,
            "wtb_timestamp_unix_s": self.wtb_timestamp_unix_s,
            "freshness_unix_s": self.freshness_unix_s,
            "sources": list(self.sources),
            "wts_ref": _listing_ref(self.wts),
            "wtb_ref": _listing_ref(self.wtb),
        }


def _listing_ref(listing: Listing) -> dict[str, Any]:
    return {
        "source": listing.raw.source,
        "native_id": listing.raw.native_id,
        "player": listing.raw.player,
        "intent": listing.intent,
        "item": listing.item,
        "quantity": listing.quantity,
        "price_amount": str(listing.price_amount) if listing.price_amount is not None else None,
        "price_unit": listing.price_unit,
        "raw_span": listing.raw_span,
        "timestamp_unix_s": listing.raw.timestamp_unix_s,
        "content_fingerprint": listing.raw.content_fingerprint,
    }
