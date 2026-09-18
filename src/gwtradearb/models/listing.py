from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Literal

from gwtradearb.fingerprint import content_fingerprint

SourceName = Literal["decltype", "gwtoolbox"]
Intent = Literal["WTS", "WTB", "WTT"]
PriceUnit = Literal["gold", "ecto", "armbrace"]
QuantityUnit = Literal["each", "stack"]
Confidence = Literal["high", "low"]


@dataclass(frozen=True, slots=True)
class RawMessage:
    """A single public trade-chat line from either HTTP source."""

    source: SourceName
    native_id: str
    timestamp_unix_s: int
    player: str
    message: str
    replaces_id: str | None = None
    content_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.content_fingerprint:
            object.__setattr__(
                self,
                "content_fingerprint",
                content_fingerprint(self.player, self.message),
            )

    def native_key(self) -> tuple[str, str]:
        """Within-source identity: decltype `id`, gwtoolbox `t`."""
        return (self.source, self.native_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Listing:
    """One WTS/WTB atom parsed from a RawMessage.

    A single chat line can yield multiple Listing atoms when it contains
    both WTS and WTB (or multiple `--` separated intents).

    High confidence requires WTS/WTB, a non-empty item, a quantity, and a
    gold price. Ecto/armbrace prices are recorded but never high in Phase 2
    (gold-first; they are not gold-comparable until a later conversion table).
    """

    raw: RawMessage
    intent: Intent | None
    item: str | None
    quantity: int | None
    quantity_unit: QuantityUnit | None
    price_amount: Decimal | None
    price_unit: PriceUnit | None
    parse_confidence: Confidence
    raw_span: str
    reasons: tuple[str, ...] = ()

    @property
    def is_matchable(self) -> bool:
        """Phase 2 preview of later matching: high-confidence gold only."""
        return self.parse_confidence == "high" and self.price_unit == "gold"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.price_amount is not None:
            data["price_amount"] = str(self.price_amount)
        return data
