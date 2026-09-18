"""One scan cycle: fetch, parse, match, persist. Used by CLI and the GUI worker.

Never talks to the Guild Wars client.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gwtradearb.collect import ALL_SOURCES, CollectResult, collect
from gwtradearb.database import open_db, persist_scan
from gwtradearb.matching import match_listings
from gwtradearb.models import Opportunity

LogFn = Callable[[str], None]

SOURCE_LABELS = {
    "decltype": "Decltype",
    "gwtoolbox": "GWToolbox",
}


def _stamp(message: str) -> str:
    return f"{datetime.now().strftime('%H:%M:%S')} - {message}"


@dataclass
class ScanCycleResult:
    collect: CollectResult
    opportunities: list[Opportunity]
    persist: dict
    source_online: dict[str, bool] = field(default_factory=dict)
    source_counts: dict[str, int] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)


def run_scan_cycle(
    db_path: str | Path,
    *,
    sources: tuple[str, ...] = ALL_SOURCES,
    query: str | None = None,
    log: LogFn | None = None,
) -> ScanCycleResult:
    lines: list[str] = []

    def emit(message: str) -> None:
        text = _stamp(message)
        lines.append(text)
        if log is not None:
            log(text)

    emit("Scan started")
    started = int(time.time())
    result = collect(sources=sources, query=query)
    finished = int(time.time())

    counts = Counter(message.source for message in result.messages)
    source_online: dict[str, bool] = {}
    source_counts: dict[str, int] = {}
    for source in sources:
        label = SOURCE_LABELS.get(source, source)
        if source in result.fetched_from:
            n = int(counts.get(source, 0))
            source_online[source] = True
            source_counts[source] = n
            emit(f"{label}: {n} listings")
        else:
            source_online[source] = False
            source_counts[source] = 0
            detail = next((err for err in result.errors if err.startswith(source)), "offline")
            emit(f"{label}: Offline ({detail})")

    opportunities = match_listings(result.listings)
    emit(f"{len(opportunities)} potential opportunities")

    with open_db(db_path) as conn:
        persist = persist_scan(
            conn,
            listings=result.listings,
            opportunities=opportunities,
            requested_sources=sources,
            fetched_from=result.fetched_from,
            message_count=len(result.messages),
            errors=result.errors,
            query=query,
            started_at_unix_s=started,
            finished_at_unix_s=finished,
        )
    persist["db_path"] = str(db_path)
    emit("Scan complete")
    return ScanCycleResult(
        collect=result,
        opportunities=opportunities,
        persist=persist,
        source_online=source_online,
        source_counts=source_counts,
        log_lines=lines,
    )
