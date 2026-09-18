"""Local SQLite persistence. No server, no credentials, no profit ledger.

Never delete opportunities; status changes are appended to a history table
without paid/received amounts. DB files are local and gitignored.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from gwtradearb.matching.aliases import canonical_item
from gwtradearb.models.listing import Listing, RawMessage
from gwtradearb.models.opportunity import Opportunity

SCHEMA_VERSION = 1

STATUSES = ("new", "traded", "dismissed", "expired")

DEFAULT_MATCH_LOOKBACK_HOURS = 12
MIN_MATCH_LOOKBACK_HOURS = 12
MAX_MATCH_LOOKBACK_HOURS = 720  # 30 days; matches the retention_days placeholder

DEFAULT_SETTINGS = {
    "scan_interval_seconds": "0",
    "retention_days": "30",
    "expire_absent_on_complete_scan": "1",
    "match_lookback_hours": str(DEFAULT_MATCH_LOOKBACK_HOURS),
    "ui_theme": "system",
    "ui_window_width": "900",
    "ui_window_height": "600",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    listing_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    native_id TEXT NOT NULL,
    player TEXT NOT NULL,
    intent TEXT,
    item_raw TEXT,
    item_canonical TEXT,
    quantity INTEGER,
    quantity_unit TEXT,
    price_amount TEXT,
    price_unit TEXT,
    parse_confidence TEXT NOT NULL,
    original_message TEXT NOT NULL,
    raw_span TEXT NOT NULL,
    timestamp_unix_s INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    replaces_id TEXT,
    reasons TEXT NOT NULL DEFAULT '[]',
    first_seen_unix_s INTEGER NOT NULL,
    last_seen_unix_s INTEGER NOT NULL,
    seen_in_last_scan INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_listings_source_native
    ON listings(source, native_id);
CREATE INDEX IF NOT EXISTS idx_listings_canonical
    ON listings(item_canonical, intent);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen
    ON listings(last_seen_unix_s);
CREATE INDEX IF NOT EXISTS idx_listings_timestamp
    ON listings(timestamp_unix_s);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_key TEXT PRIMARY KEY,
    item_canonical TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    quantity_unit TEXT NOT NULL,
    seller TEXT NOT NULL,
    buyer TEXT NOT NULL,
    wts_listing_key TEXT NOT NULL,
    wtb_listing_key TEXT NOT NULL,
    sell_price TEXT NOT NULL,
    buy_price TEXT NOT NULL,
    potential_difference TEXT NOT NULL,
    price_unit TEXT NOT NULL DEFAULT 'gold',
    wts_timestamp_unix_s INTEGER NOT NULL,
    wtb_timestamp_unix_s INTEGER NOT NULL,
    sources TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    detected_at_unix_s INTEGER NOT NULL,
    updated_at_unix_s INTEGER NOT NULL,
    last_seen_unix_s INTEGER NOT NULL,
    FOREIGN KEY (wts_listing_key) REFERENCES listings(listing_key),
    FOREIGN KEY (wtb_listing_key) REFERENCES listings(listing_key)
);

CREATE INDEX IF NOT EXISTS idx_opportunities_status
    ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_item
    ON opportunities(item_canonical);

CREATE TABLE IF NOT EXISTS opportunity_status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_key TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at_unix_s INTEGER NOT NULL,
    FOREIGN KEY (opportunity_key) REFERENCES opportunities(opportunity_key)
);

CREATE INDEX IF NOT EXISTS idx_status_events_key
    ON opportunity_status_events(opportunity_key);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_unix_s INTEGER NOT NULL,
    finished_at_unix_s INTEGER,
    sources TEXT,
    query TEXT,
    message_count INTEGER,
    listing_count INTEGER,
    high_count INTEGER,
    opportunity_count INTEGER,
    expired_count INTEGER,
    error_count INTEGER,
    errors TEXT,
    complete INTEGER NOT NULL DEFAULT 0
);
"""


def default_db_path() -> Path:
    """Local DB path. Override with GWTRADEARB_DB.

    Default: platform user-data dir (`~/.local/share/gwtradearb/` on Linux).
    `GWTRADEARB_DB_LOCAL=1` uses `./data/gwtradearb.sqlite` instead.
    """
    override = os.environ.get("GWTRADEARB_DB")
    if override:
        return Path(override).expanduser()
    if os.environ.get("GWTRADEARB_DB_LOCAL") == "1":
        return Path("data") / "gwtradearb.sqlite"
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "gwtradearb"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "gwtradearb"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = Path(xdg) / "gwtradearb" if xdg else Path.home() / ".local" / "share" / "gwtradearb"
    return root / "gwtradearb.sqlite"


def listing_key(listing: Listing) -> str:
    """Stable within-source atom id (not the canonical item, so alias updates do not fork rows)."""
    payload = (
        f"{listing.raw.source}|{listing.raw.native_id}|{listing.intent or ''}|"
        f"{listing.raw_span}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    # Always seed newly added keys; never overwrite values the user already set.
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {current} is newer than this app ({SCHEMA_VERSION})"
        )


@contextmanager
def open_db(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def normalize_match_lookback_hours(
    value: Any,
    *,
    default: int = DEFAULT_MATCH_LOOKBACK_HOURS,
) -> int:
    """Clamp a lookback setting to [MIN, MAX] hours. Invalid values use default."""
    try:
        hours = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        hours = default
    if hours < MIN_MATCH_LOOKBACK_HOURS:
        return MIN_MATCH_LOOKBACK_HOURS
    if hours > MAX_MATCH_LOOKBACK_HOURS:
        return MAX_MATCH_LOOKBACK_HOURS
    return hours


def get_match_lookback_hours(conn: sqlite3.Connection) -> int:
    raw = get_setting(
        conn, "match_lookback_hours", str(DEFAULT_MATCH_LOOKBACK_HOURS)
    )
    return normalize_match_lookback_hours(raw)


def set_match_lookback_hours(conn: sqlite3.Connection, hours: int | str) -> int:
    normalised = normalize_match_lookback_hours(hours)
    set_setting(conn, "match_lookback_hours", str(normalised))
    return normalised


def lookback_cutoff_unix_s(
    now_unix_s: int,
    lookback_hours: int | None = None,
) -> int:
    hours = (
        DEFAULT_MATCH_LOOKBACK_HOURS
        if lookback_hours is None
        else normalize_match_lookback_hours(lookback_hours)
    )
    return int(now_unix_s) - hours * 3600


def upsert_listings(
    conn: sqlite3.Connection,
    listings: Sequence[Listing],
    *,
    now_unix_s: int,
    reset_seen: bool = True,
) -> int:
    if reset_seen:
        conn.execute("UPDATE listings SET seen_in_last_scan = 0")
    for listing in listings:
        key = listing_key(listing)
        item_raw = listing.item
        item_canon = canonical_item(listing.item)
        reasons = json.dumps(list(listing.reasons), ensure_ascii=False)
        price = str(listing.price_amount) if listing.price_amount is not None else None
        conn.execute(
            """
            INSERT INTO listings (
                listing_key, source, native_id, player, intent, item_raw, item_canonical,
                quantity, quantity_unit, price_amount, price_unit, parse_confidence,
                original_message, raw_span, timestamp_unix_s, fingerprint, replaces_id,
                reasons, first_seen_unix_s, last_seen_unix_s, seen_in_last_scan
            ) VALUES (
                :listing_key, :source, :native_id, :player, :intent, :item_raw, :item_canonical,
                :quantity, :quantity_unit, :price_amount, :price_unit, :parse_confidence,
                :original_message, :raw_span, :timestamp_unix_s, :fingerprint, :replaces_id,
                :reasons, :now, :now, 1
            )
            ON CONFLICT(listing_key) DO UPDATE SET
                player = excluded.player,
                item_raw = excluded.item_raw,
                item_canonical = excluded.item_canonical,
                quantity = excluded.quantity,
                quantity_unit = excluded.quantity_unit,
                price_amount = excluded.price_amount,
                price_unit = excluded.price_unit,
                parse_confidence = excluded.parse_confidence,
                original_message = excluded.original_message,
                timestamp_unix_s = excluded.timestamp_unix_s,
                fingerprint = excluded.fingerprint,
                replaces_id = excluded.replaces_id,
                reasons = excluded.reasons,
                last_seen_unix_s = excluded.last_seen_unix_s,
                seen_in_last_scan = 1
            """,
            {
                "listing_key": key,
                "source": listing.raw.source,
                "native_id": listing.raw.native_id,
                "player": listing.raw.player,
                "intent": listing.intent,
                "item_raw": item_raw,
                "item_canonical": item_canon,
                "quantity": listing.quantity,
                "quantity_unit": listing.quantity_unit,
                "price_amount": price,
                "price_unit": listing.price_unit,
                "parse_confidence": listing.parse_confidence,
                "original_message": listing.raw.message,
                "raw_span": listing.raw_span,
                "timestamp_unix_s": listing.raw.timestamp_unix_s,
                "fingerprint": listing.raw.content_fingerprint,
                "replaces_id": listing.raw.replaces_id,
                "reasons": reasons,
                "now": now_unix_s,
            },
        )
    return len(listings)


def _record_status_event(
    conn: sqlite3.Connection,
    opportunity_key: str,
    old_status: str | None,
    new_status: str,
    *,
    now_unix_s: int,
) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_status_events (
            opportunity_key, old_status, new_status, changed_at_unix_s
        ) VALUES (?, ?, ?, ?)
        """,
        (opportunity_key, old_status, new_status, now_unix_s),
    )


def upsert_opportunities(
    conn: sqlite3.Connection,
    opportunities: Sequence[Opportunity],
    *,
    now_unix_s: int,
) -> list[str]:
    keys: list[str] = []
    for opportunity in opportunities:
        key = opportunity.opportunity_key
        keys.append(key)
        wts_key = listing_key(opportunity.wts)
        wtb_key = listing_key(opportunity.wtb)
        sources = json.dumps(list(opportunity.sources), ensure_ascii=False)
        existing = conn.execute(
            "SELECT status FROM opportunities WHERE opportunity_key = ?",
            (key,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO opportunities (
                    opportunity_key, item_canonical, quantity, quantity_unit, seller, buyer,
                    wts_listing_key, wtb_listing_key, sell_price, buy_price, potential_difference,
                    price_unit, wts_timestamp_unix_s, wtb_timestamp_unix_s, sources, status,
                    detected_at_unix_s, updated_at_unix_s, last_seen_unix_s
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?
                )
                """,
                (
                    key,
                    opportunity.item,
                    opportunity.quantity,
                    opportunity.quantity_unit,
                    opportunity.seller,
                    opportunity.buyer,
                    wts_key,
                    wtb_key,
                    str(opportunity.sell_price),
                    str(opportunity.buy_price),
                    str(opportunity.potential_difference),
                    opportunity.price_unit,
                    opportunity.wts_timestamp_unix_s,
                    opportunity.wtb_timestamp_unix_s,
                    sources,
                    now_unix_s,
                    now_unix_s,
                    now_unix_s,
                ),
            )
            _record_status_event(conn, key, None, "new", now_unix_s=now_unix_s)
            continue

        old_status = str(existing["status"])
        new_status = "new" if old_status == "expired" else old_status
        conn.execute(
            """
            UPDATE opportunities SET
                item_canonical = ?, quantity = ?, quantity_unit = ?,
                seller = ?, buyer = ?,
                wts_listing_key = ?, wtb_listing_key = ?,
                sell_price = ?, buy_price = ?, potential_difference = ?,
                price_unit = ?, wts_timestamp_unix_s = ?, wtb_timestamp_unix_s = ?,
                sources = ?, last_seen_unix_s = ?, updated_at_unix_s = ?,
                status = ?
            WHERE opportunity_key = ?
            """,
            (
                opportunity.item,
                opportunity.quantity,
                opportunity.quantity_unit,
                opportunity.seller,
                opportunity.buyer,
                wts_key,
                wtb_key,
                str(opportunity.sell_price),
                str(opportunity.buy_price),
                str(opportunity.potential_difference),
                opportunity.price_unit,
                opportunity.wts_timestamp_unix_s,
                opportunity.wtb_timestamp_unix_s,
                sources,
                now_unix_s,
                now_unix_s,
                new_status,
                key,
            ),
        )
        if new_status != old_status:
            _record_status_event(conn, key, old_status, new_status, now_unix_s=now_unix_s)
    return keys


def set_status(
    conn: sqlite3.Connection,
    opportunity_key: str,
    status: str,
    *,
    now_unix_s: int,
) -> str:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    resolved = resolve_opportunity_key(conn, opportunity_key)
    row = conn.execute(
        "SELECT status FROM opportunities WHERE opportunity_key = ?",
        (resolved,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown opportunity_key {opportunity_key!r}")
    old = str(row["status"])
    if old == status:
        return resolved
    conn.execute(
        """
        UPDATE opportunities
        SET status = ?, updated_at_unix_s = ?
        WHERE opportunity_key = ?
        """,
        (status, now_unix_s, resolved),
    )
    _record_status_event(conn, resolved, old, status, now_unix_s=now_unix_s)
    return resolved


def resolve_opportunity_key(conn: sqlite3.Connection, prefix: str) -> str:
    text = prefix.strip().lower()
    if not text:
        raise KeyError("empty opportunity key")
    exact = conn.execute(
        "SELECT opportunity_key FROM opportunities WHERE opportunity_key = ?",
        (text,),
    ).fetchone()
    if exact:
        return str(exact["opportunity_key"])
    rows = conn.execute(
        "SELECT opportunity_key FROM opportunities WHERE opportunity_key LIKE ?",
        (text + "%",),
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0]["opportunity_key"])
    if not rows:
        raise KeyError(f"unknown opportunity_key {prefix!r}")
    raise KeyError(f"ambiguous opportunity_key prefix {prefix!r} ({len(rows)} matches)")


def expire_absent_opportunities(
    conn: sqlite3.Connection,
    *,
    seen_keys: Iterable[str],
    now_unix_s: int,
    complete: bool,
) -> int:
    """Mark `new` opportunities expired when a complete scan no longer contains them.

    Partial scans (a source failed) never expire rows. History is never deleted.
    """
    if not complete:
        return 0
    flag = get_setting(conn, "expire_absent_on_complete_scan", "1")
    if flag not in {"1", "true", "yes"}:
        return 0
    present = set(seen_keys)
    rows = conn.execute(
        "SELECT opportunity_key FROM opportunities WHERE status = 'new'"
    ).fetchall()
    expired = 0
    for row in rows:
        key = str(row["opportunity_key"])
        if key not in present:
            set_status(conn, key, "expired", now_unix_s=now_unix_s)
            expired += 1
    return expired


def start_scan(
    conn: sqlite3.Connection,
    *,
    started_at_unix_s: int,
    sources: Sequence[str],
    query: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO scans (started_at_unix_s, sources, query)
        VALUES (?, ?, ?)
        """,
        (started_at_unix_s, json.dumps(list(sources)), query),
    )
    return int(cur.lastrowid)


def finish_scan(
    conn: sqlite3.Connection,
    scan_id: int,
    *,
    finished_at_unix_s: int,
    message_count: int,
    listing_count: int,
    high_count: int,
    opportunity_count: int,
    expired_count: int,
    errors: Sequence[str],
    complete: bool,
) -> None:
    conn.execute(
        """
        UPDATE scans SET
            finished_at_unix_s = ?,
            message_count = ?,
            listing_count = ?,
            high_count = ?,
            opportunity_count = ?,
            expired_count = ?,
            error_count = ?,
            errors = ?,
            complete = ?
        WHERE id = ?
        """,
        (
            finished_at_unix_s,
            message_count,
            listing_count,
            high_count,
            opportunity_count,
            expired_count,
            len(errors),
            json.dumps(list(errors), ensure_ascii=False),
            1 if complete else 0,
            scan_id,
        ),
    )


def persist_scan(
    conn: sqlite3.Connection,
    *,
    listings: Sequence[Listing],
    opportunities: Sequence[Opportunity] | None = None,
    requested_sources: Sequence[str],
    fetched_from: Sequence[str],
    message_count: int,
    errors: Sequence[str],
    query: str | None,
    started_at_unix_s: int,
    finished_at_unix_s: int,
    lookback_hours: int | None = None,
) -> dict[str, Any]:
    """Upsert a scan's listings and opportunities. Never deletes history.

    When ``opportunities`` is omitted, listings are rematched from local SQLite
    using ``match_lookback_hours`` (default 12h). Live feeds are not paginated;
    older rows already stored in this DB stay eligible until they age out.
    """
    from gwtradearb.matching import match_listings

    scan_id = start_scan(
        conn,
        started_at_unix_s=started_at_unix_s,
        sources=fetched_from,
        query=query,
    )
    complete = bool(fetched_from) and set(fetched_from) >= set(requested_sources)
    reset_seen = bool(fetched_from)
    upsert_listings(
        conn,
        listings,
        now_unix_s=finished_at_unix_s,
        reset_seen=reset_seen,
    )
    hours = (
        get_match_lookback_hours(conn)
        if lookback_hours is None
        else normalize_match_lookback_hours(lookback_hours)
    )
    window = listings_in_lookback_window(
        conn,
        now_unix_s=finished_at_unix_s,
        lookback_hours=hours,
        extra=listings,
    )
    if opportunities is None:
        opportunities = match_listings(window)
    seen_keys = upsert_opportunities(conn, opportunities, now_unix_s=finished_at_unix_s)
    expired = expire_absent_opportunities(
        conn,
        seen_keys=seen_keys,
        now_unix_s=finished_at_unix_s,
        complete=complete,
    )
    high_count = sum(1 for row in listings if row.parse_confidence == "high")
    finish_scan(
        conn,
        scan_id,
        finished_at_unix_s=finished_at_unix_s,
        message_count=message_count,
        listing_count=len(listings),
        high_count=high_count,
        opportunity_count=len(opportunities),
        expired_count=expired,
        errors=errors,
        complete=complete,
    )
    return {
        "scan_id": scan_id,
        "listings": len(listings),
        "opportunities": len(opportunities),
        "expired": expired,
        "complete": complete,
        "db_path": None,
        "matched_opportunities": list(opportunities),
        "lookback_hours": hours,
        "lookback_listings": len(window),
    }


def get_listing(conn: sqlite3.Connection, listing_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM listings WHERE listing_key = ?",
        (listing_key,),
    ).fetchone()


def list_opportunity_details(
    conn: sqlite3.Connection,
    status: str | None = "new",
) -> list[dict[str, Any]]:
    """Opportunities joined with both original listing rows for the UI detail pane."""
    sql = """
        SELECT
            o.*,
            wts.original_message AS wts_message,
            wts.raw_span AS wts_span,
            wts.source AS wts_source,
            wts.native_id AS wts_native_id,
            wts.player AS wts_player,
            wts.timestamp_unix_s AS wts_listing_ts,
            wts.item_raw AS wts_item_raw,
            wts.price_amount AS wts_listing_price,
            wts.price_unit AS wts_listing_unit,
            wts.quantity AS wts_listing_qty,
            wtb.original_message AS wtb_message,
            wtb.raw_span AS wtb_span,
            wtb.source AS wtb_source,
            wtb.native_id AS wtb_native_id,
            wtb.player AS wtb_player,
            wtb.timestamp_unix_s AS wtb_listing_ts,
            wtb.item_raw AS wtb_item_raw,
            wtb.price_amount AS wtb_listing_price,
            wtb.price_unit AS wtb_listing_unit,
            wtb.quantity AS wtb_listing_qty
        FROM opportunities o
        LEFT JOIN listings wts ON wts.listing_key = o.wts_listing_key
        LEFT JOIN listings wtb ON wtb.listing_key = o.wtb_listing_key
    """
    params: tuple = ()
    if status not in (None, "all"):
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES} or 'all'")
        sql += " WHERE o.status = ?"
        params = (status,)
    sql += " ORDER BY o.detected_at_unix_s DESC, o.opportunity_key"
    return [dict(row) for row in conn.execute(sql, params)]


def list_opportunities(
    conn: sqlite3.Connection,
    status: str | None = "new",
) -> list[sqlite3.Row]:
    if status is None or status == "all":
        return list(
            conn.execute(
                "SELECT * FROM opportunities ORDER BY last_seen_unix_s DESC, opportunity_key"
            )
        )
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES} or 'all'")
    return list(
        conn.execute(
            """
            SELECT * FROM opportunities
            WHERE status = ?
            ORDER BY last_seen_unix_s DESC, opportunity_key
            """,
            (status,),
        )
    )


def status_history(conn: sqlite3.Connection, opportunity_key: str) -> list[sqlite3.Row]:
    resolved = resolve_opportunity_key(conn, opportunity_key)
    return list(
        conn.execute(
            """
            SELECT * FROM opportunity_status_events
            WHERE opportunity_key = ?
            ORDER BY id
            """,
            (resolved,),
        )
    )


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def _count(sql: str, params: tuple = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    last = conn.execute(
        "SELECT started_at_unix_s, finished_at_unix_s, complete FROM scans "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    by_status = {
        name: _count("SELECT COUNT(*) FROM opportunities WHERE status = ?", (name,))
        for name in STATUSES
    }
    return {
        "listings": _count("SELECT COUNT(*) FROM listings"),
        "listings_last_scan": _count(
            "SELECT COUNT(*) FROM listings WHERE seen_in_last_scan = 1"
        ),
        "opportunities": _count("SELECT COUNT(*) FROM opportunities"),
        "new": by_status["new"],
        "traded": by_status["traded"],
        "dismissed": by_status["dismissed"],
        "expired": by_status["expired"],
        "scans": _count("SELECT COUNT(*) FROM scans"),
        "last_scan_started_unix_s": last["started_at_unix_s"] if last else None,
        "last_scan_finished_unix_s": last["finished_at_unix_s"] if last else None,
        "last_scan_complete": bool(last["complete"]) if last else None,
    }


def _listing_from_row(row: sqlite3.Row) -> Listing:
    reasons = tuple(json.loads(row["reasons"] or "[]"))
    price = Decimal(row["price_amount"]) if row["price_amount"] is not None else None
    raw = RawMessage(
        source=row["source"],
        native_id=row["native_id"],
        timestamp_unix_s=int(row["timestamp_unix_s"]),
        player=row["player"],
        message=row["original_message"],
        replaces_id=row["replaces_id"],
        content_fingerprint=row["fingerprint"],
    )
    return Listing(
        raw=raw,
        intent=row["intent"],
        item=row["item_raw"],
        quantity=row["quantity"],
        quantity_unit=row["quantity_unit"],
        price_amount=price,
        price_unit=row["price_unit"],
        parse_confidence=row["parse_confidence"],
        raw_span=row["raw_span"],
        reasons=reasons,
    )


def load_listings(
    conn: sqlite3.Connection,
    *,
    last_scan_only: bool = False,
    since_unix_s: int | None = None,
) -> list[Listing]:
    """Rehydrate Listing atoms (for tests, lookback matching, later UI)."""
    clauses: list[str] = []
    params: list[Any] = []
    if last_scan_only:
        clauses.append("seen_in_last_scan = 1")
    if since_unix_s is not None:
        clauses.append("timestamp_unix_s >= ?")
        params.append(int(since_unix_s))
    sql = "SELECT * FROM listings"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY timestamp_unix_s DESC"
    return [_listing_from_row(row) for row in conn.execute(sql, params)]


def listings_in_lookback_window(
    conn: sqlite3.Connection,
    *,
    now_unix_s: int,
    lookback_hours: int | None = None,
    extra: Sequence[Listing] = (),
) -> list[Listing]:
    """Listings to rematch: SQLite history in the lookback window, plus extras.

    Stored rows are eligible when their chat ``timestamp_unix_s`` is within the
    window (not ``last_seen``). That keeps lines that scrolled off the live
    page but are still recent, and skips ancient history.

    ``extra`` is the current scrape: those atoms always participate (they are
    live right now) and win on ``listing_key`` collisions. Search APIs are not
    used to backfill the window.
    """
    hours = (
        get_match_lookback_hours(conn)
        if lookback_hours is None
        else normalize_match_lookback_hours(lookback_hours)
    )
    cutoff = lookback_cutoff_unix_s(now_unix_s, hours)
    combined: dict[str, Listing] = {}
    for listing in load_listings(conn, since_unix_s=cutoff):
        combined[listing_key(listing)] = listing
    for listing in extra:
        combined[listing_key(listing)] = listing
    return list(combined.values())
