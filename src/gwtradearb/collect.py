"""One-shot fetch + parse pipeline. One failing source does not abort the other."""

from __future__ import annotations

from dataclasses import dataclass, field

from gwtradearb.models import Listing, RawMessage
from gwtradearb.fingerprint import dedupe_by_native_id
from gwtradearb.parsing.parser import parse_messages
from gwtradearb.scrapers.decltype import fetch_live as decltype_live
from gwtradearb.scrapers.decltype import search as decltype_search
from gwtradearb.scrapers.gwtoolbox import fetch_live as gwtoolbox_live
from gwtradearb.scrapers.gwtoolbox import search as gwtoolbox_search
from gwtradearb.scrapers.http import SourceFetchError

ALL_SOURCES = ("decltype", "gwtoolbox")


@dataclass
class CollectResult:
    messages: list[RawMessage] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_from: list[str] = field(default_factory=list)

    @property
    def high_listings(self) -> list[Listing]:
        return [row for row in self.listings if row.parse_confidence == "high"]


def collect(
    *,
    sources: tuple[str, ...] = ALL_SOURCES,
    query: str | None = None,
) -> CollectResult:
    result = CollectResult()
    buckets: list[RawMessage] = []

    for source in sources:
        try:
            if source == "decltype":
                rows = decltype_search(query) if query else decltype_live()
            elif source == "gwtoolbox":
                rows = gwtoolbox_search(query) if query else gwtoolbox_live()
            else:
                result.errors.append(f"{source}: unknown source")
                continue
        except SourceFetchError as exc:
            result.errors.append(str(exc))
            continue
        buckets.extend(rows)
        result.fetched_from.append(source)

    result.messages = dedupe_by_native_id(buckets)
    result.listings = parse_messages(result.messages)
    return result
