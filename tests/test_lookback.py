from __future__ import annotations

from unittest.mock import patch

from gwtradearb.collect import CollectResult
from gwtradearb.database import (
    DEFAULT_MATCH_LOOKBACK_HOURS,
    MAX_MATCH_LOOKBACK_HOURS,
    MIN_MATCH_LOOKBACK_HOURS,
    get_match_lookback_hours,
    listings_in_lookback_window,
    list_opportunities,
    load_listings,
    open_db,
    persist_scan,
    set_match_lookback_hours,
    set_setting,
)
from gwtradearb.matching import match_listings
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message
from gwtradearb.scan import run_scan_cycle

NOW = 1_800_000_000


def _listing(
    message: str,
    *,
    player: str,
    native_id: str,
    timestamp_unix_s: int,
    source: str = "decltype",
):
    rows = parse_message(
        RawMessage(
            source=source,  # type: ignore[arg-type]
            native_id=native_id,
            timestamp_unix_s=timestamp_unix_s,
            player=player,
            message=message,
        )
    )
    high = [row for row in rows if row.parse_confidence == "high"]
    assert high, message
    return high[0]


def _ecto_pair(*, wts_ts: int, wtb_ts: int):
    wts = _listing(
        "WTS ecto 12k ea",
        player="Ann",
        native_id="s-ecto",
        timestamp_unix_s=wts_ts,
    )
    wtb = _listing(
        "WTB ecto 13k ea",
        player="Bob",
        native_id="b-ecto",
        timestamp_unix_s=wtb_ts,
    )
    return wts, wtb


def _persist(
    conn,
    listings,
    *,
    finished_at_unix_s: int,
    opportunities=None,
    lookback_hours=None,
    complete_sources: bool = True,
):
    sources = ("decltype", "gwtoolbox") if complete_sources else ("decltype",)
    fetched = sources
    return persist_scan(
        conn,
        listings=listings,
        opportunities=opportunities,
        requested_sources=sources,
        fetched_from=fetched,
        message_count=len(listings),
        errors=[],
        query=None,
        started_at_unix_s=finished_at_unix_s - 1,
        finished_at_unix_s=finished_at_unix_s,
        lookback_hours=lookback_hours,
    )


def test_existing_db_seeds_lookback_setting(tmp_path):
    db = tmp_path / "t.sqlite"
    with open_db(db) as conn:
        conn.execute("DELETE FROM settings WHERE key = 'match_lookback_hours'")
    with open_db(db) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'match_lookback_hours'"
        ).fetchone()
        assert row["value"] == "12"
        assert get_match_lookback_hours(conn) == 12


def test_default_match_lookback_is_12_hours(tmp_path):
    with open_db(tmp_path / "t.sqlite") as conn:
        assert DEFAULT_MATCH_LOOKBACK_HOURS == 12
        assert MIN_MATCH_LOOKBACK_HOURS == 12
        assert get_match_lookback_hours(conn) == 12
        stored = conn.execute(
            "SELECT value FROM settings WHERE key = 'match_lookback_hours'"
        ).fetchone()
        assert stored["value"] == "12"


def test_lookback_below_minimum_is_clamped_to_12(tmp_path):
    with open_db(tmp_path / "t.sqlite") as conn:
        set_setting(conn, "match_lookback_hours", "6")
        assert get_match_lookback_hours(conn) == 12
        assert set_match_lookback_hours(conn, 48) == 48
        assert get_match_lookback_hours(conn) == 48
        assert set_match_lookback_hours(conn, MAX_MATCH_LOOKBACK_HOURS + 50) == (
            MAX_MATCH_LOOKBACK_HOURS
        )


def test_minutes_and_hours_apart_within_window_match_from_db(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 7 * 60, wtb_ts=NOW - 10)
    later_wts = _listing(
        "WTS ecto 12k ea",
        player="Cara",
        native_id="s-ecto-late",
        timestamp_unix_s=NOW - 6 * 3600,
    )
    later_wtb = _listing(
        "WTB ecto 13k ea",
        player="Dan",
        native_id="b-ecto-late",
        timestamp_unix_s=NOW - 5 * 3600,
    )
    with open_db(tmp_path / "t.sqlite") as conn:
        _persist(conn, [wts, later_wts], finished_at_unix_s=NOW - 5 * 3600, opportunities=[])
        result = _persist(conn, [wtb, later_wtb], finished_at_unix_s=NOW)
        window = listings_in_lookback_window(conn, now_unix_s=NOW)
        loaded = load_listings(conn, since_unix_s=NOW - 12 * 3600)
        rows = list_opportunities(conn, "new")
    assert result["lookback_hours"] == 12
    assert len(window) == 4
    assert len(loaded) == 4
    # Ann/Bob (7 minutes apart) and Cara/Dan (hours apart), plus cross pairs.
    assert len(rows) >= 2
    sellers = {row["seller"] for row in rows}
    buyers = {row["buyer"] for row in rows}
    assert "Ann" in sellers
    assert "Cara" in sellers
    assert "Bob" in buyers
    assert "Dan" in buyers
    assert all(row["item_canonical"] == "glob of ectoplasm" for row in rows)


def test_listings_older_than_lookback_are_excluded(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 13 * 3600, wtb_ts=NOW - 60)
    with open_db(tmp_path / "t.sqlite") as conn:
        _persist(conn, [wts], finished_at_unix_s=NOW - 13 * 3600, opportunities=[])
        result = _persist(conn, [wtb], finished_at_unix_s=NOW)
        window = listings_in_lookback_window(conn, now_unix_s=NOW)
        rows = list_opportunities(conn, "new")
    assert result["opportunities"] == 0
    assert result["lookback_hours"] == 12
    assert len(window) == 1
    assert window[0].raw.player == "Bob"
    assert rows == []


def test_custom_longer_lookback_includes_older_listings(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 20 * 3600, wtb_ts=NOW - 60)
    db = tmp_path / "t.sqlite"
    with open_db(db) as conn:
        _persist(conn, [wts], finished_at_unix_s=NOW - 20 * 3600, opportunities=[])
        excluded = _persist(conn, [wtb], finished_at_unix_s=NOW, lookback_hours=12)
        assert excluded["opportunities"] == 0
        included = _persist(conn, [wtb], finished_at_unix_s=NOW, lookback_hours=24)
        rows = list_opportunities(conn, "new")
        window_24 = listings_in_lookback_window(
            conn, now_unix_s=NOW, lookback_hours=24
        )
    assert included["opportunities"] == 1
    assert included["lookback_hours"] == 24
    assert len(rows) == 1
    assert rows[0]["seller"] == "Ann"
    assert rows[0]["buyer"] == "Bob"
    assert {row.raw.player for row in window_24} == {"Ann", "Bob"}
    with open_db(db) as conn:
        assert get_match_lookback_hours(conn) == 12
        set_match_lookback_hours(conn, 24)
        assert get_match_lookback_hours(conn) == 24


def test_scan_cycle_rematches_listings_that_scrolled_off_live_feed(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 10 * 60, wtb_ts=NOW - 30)
    db = tmp_path / "t.sqlite"
    first = CollectResult(
        messages=[wts.raw],
        listings=[wts],
        fetched_from=["decltype", "gwtoolbox"],
    )
    second = CollectResult(
        messages=[wtb.raw],
        listings=[wtb],
        fetched_from=["decltype", "gwtoolbox"],
    )
    with (
        patch("gwtradearb.scan.collect", return_value=first),
        patch("gwtradearb.scan.time.time", return_value=float(NOW - 10 * 60)),
    ):
        run_scan_cycle(db)
    with (
        patch("gwtradearb.scan.collect", return_value=second),
        patch("gwtradearb.scan.time.time", return_value=float(NOW)),
    ):
        result = run_scan_cycle(db)
    assert result.lookback_hours == 12
    assert result.lookback_listings == 2
    assert len(result.opportunities) == 1
    assert result.opportunities[0].seller == "Ann"
    assert result.opportunities[0].buyer == "Bob"
    assert any("Lookback 12h" in line for line in result.log_lines)
    with open_db(db) as conn:
        rows = list_opportunities(conn, "new")
    assert len(rows) == 1


def test_in_window_pair_stays_new_when_absent_from_live_scrape(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 3 * 3600, wtb_ts=NOW - 3 * 3600 + 30)
    other = _listing(
        "WTS lockpicks 1k each",
        player="Cara",
        native_id="s-lock",
        timestamp_unix_s=NOW - 10,
    )
    with open_db(tmp_path / "t.sqlite") as conn:
        _persist(conn, [wts, wtb], finished_at_unix_s=NOW - 3 * 3600 + 30)
        _persist(conn, [other], finished_at_unix_s=NOW)
        rows = list_opportunities(conn, "new")
        expired = list_opportunities(conn, "expired")
    assert len(rows) == 1
    assert rows[0]["seller"] == "Ann"
    assert expired == []


def test_pair_older_than_lookback_expires_on_complete_rematch(tmp_path):
    wts, wtb = _ecto_pair(wts_ts=NOW - 20 * 3600, wtb_ts=NOW - 20 * 3600 + 30)
    other = _listing(
        "WTS lockpicks 1k each",
        player="Cara",
        native_id="s-lock",
        timestamp_unix_s=NOW - 10,
    )
    with open_db(tmp_path / "t.sqlite") as conn:
        first = match_listings([wts, wtb])
        assert first
        _persist(
            conn,
            [wts, wtb],
            finished_at_unix_s=NOW - 20 * 3600 + 30,
            opportunities=first,
        )
        _persist(conn, [other], finished_at_unix_s=NOW, lookback_hours=12)
        assert list_opportunities(conn, "new") == []
        expired = list_opportunities(conn, "expired")
    assert len(expired) == 1
