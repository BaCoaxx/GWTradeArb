from __future__ import annotations

from decimal import Decimal

from gwtradearb.database import (
    expire_absent_opportunities,
    listing_key,
    list_opportunities,
    list_opportunity_details,
    load_listings,
    open_db,
    persist_scan,
    set_status,
    stats,
    status_history,
    upsert_listings,
    upsert_opportunities,
)
from gwtradearb.matching import match_listings
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message


def _listing(
    message: str,
    *,
    player: str,
    native_id: str,
    timestamp_unix_s: int = 1_700_000_000,
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


def test_upsert_listings_dedupes_same_source_id(tmp_path):
    db = tmp_path / "t.sqlite"
    listing = _listing("WTS mallyx shield 50k", player="Ann", native_id="10")
    with open_db(db) as conn:
        upsert_listings(conn, [listing], now_unix_s=100)
        upsert_listings(conn, [listing], now_unix_s=200)
        count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        last = conn.execute("SELECT last_seen_unix_s, first_seen_unix_s FROM listings").fetchone()
    assert count == 1
    assert last["first_seen_unix_s"] == 100
    assert last["last_seen_unix_s"] == 200


def test_opportunity_upsert_stable_key_and_status_retention(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    assert len(opps) == 1
    key = opps[0].opportunity_key
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=opps,
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=10,
            finished_at_unix_s=11,
        )
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=opps,
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=20,
            finished_at_unix_s=21,
        )
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
        set_status(conn, key, "traded", now_unix_s=30)
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=opps,
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=40,
            finished_at_unix_s=41,
        )
        row = conn.execute("SELECT status FROM opportunities").fetchone()
        events = status_history(conn, key)
        listed = list_opportunities(conn, "traded")
        assert row["status"] == "traded"
        assert [event["new_status"] for event in events] == ["new", "traded"]
        assert listed[0]["opportunity_key"] == key
        assert listed[0]["potential_difference"] == "5000"

    with open_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1


def test_stats_counts_without_profit_total(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=match_listings([wts, wtb]),
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=1,
            finished_at_unix_s=2,
        )
        payload = stats(conn)
    assert payload["listings"] == 2
    assert payload["opportunities"] == 1
    assert payload["new"] == 1
    assert payload["traded"] == 0
    assert payload["scans"] == 1
    assert "profit" not in payload
    assert "potential_difference_sum" not in payload


def test_expire_absent_on_complete_scan_keeps_row(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    other = _listing("WTS lockpicks 1k each", player="Cara", native_id="s2")
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=opps,
            requested_sources=("decltype", "gwtoolbox"),
            fetched_from=("decltype", "gwtoolbox"),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=1,
            finished_at_unix_s=2,
        )
        persist_scan(
            conn,
            listings=[other],
            opportunities=[],
            requested_sources=("decltype", "gwtoolbox"),
            fetched_from=("decltype", "gwtoolbox"),
            message_count=1,
            errors=[],
            query=None,
            started_at_unix_s=3,
            finished_at_unix_s=4,
        )
        row = conn.execute("SELECT status FROM opportunities").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
    assert row["status"] == "expired"


def test_partial_scan_does_not_expire(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=match_listings([wts, wtb]),
            requested_sources=("decltype", "gwtoolbox"),
            fetched_from=("decltype", "gwtoolbox"),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=1,
            finished_at_unix_s=2,
        )
        persist_scan(
            conn,
            listings=[],
            opportunities=[],
            requested_sources=("decltype", "gwtoolbox"),
            fetched_from=("decltype",),
            message_count=0,
            errors=["gwtoolbox: down"],
            query=None,
            started_at_unix_s=3,
            finished_at_unix_s=4,
        )
        assert conn.execute("SELECT status FROM opportunities").fetchone()[0] == "new"


def test_case_insensitive_pair_survives_db_round_trip(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS ECTOS 12k ea", player="Ann", native_id="s1")
    wtb = _listing("WTB ecto 13k ea", player="Bob", native_id="b1")
    first = match_listings([wts, wtb])
    assert len(first) == 1
    assert first[0].item == "glob of ectoplasm"
    with open_db(db) as conn:
        upsert_listings(conn, [wts, wtb], now_unix_s=5)
        upsert_opportunities(conn, first, now_unix_s=5)
        loaded = load_listings(conn)
        again = match_listings(loaded)
        stored = list_opportunities(conn, "new")
    assert len(again) == 1
    assert again[0].opportunity_key == first[0].opportunity_key
    assert stored[0]["item_canonical"] == "glob of ectoplasm"
    assert stored[0]["opportunity_key"] == first[0].opportunity_key


def test_new_listing_pair_gets_new_opportunity_key(tmp_path):
    db = tmp_path / "t.sqlite"
    wts_a = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    wts_b = _listing("WTS mallyx shield 40k", player="Cara", native_id="s2")
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts_a, wtb],
            opportunities=match_listings([wts_a, wtb]),
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=1,
            finished_at_unix_s=2,
        )
        persist_scan(
            conn,
            listings=[wts_b, wtb],
            opportunities=match_listings([wts_b, wtb]),
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=3,
            finished_at_unix_s=4,
        )
        keys = [
            row["opportunity_key"]
            for row in conn.execute("SELECT opportunity_key FROM opportunities")
        ]
        statuses = {
            row["opportunity_key"]: row["status"]
            for row in conn.execute("SELECT opportunity_key, status FROM opportunities")
        }
    assert len(set(keys)) == 2
    assert "expired" in statuses.values()
    assert "new" in statuses.values()


def test_listing_key_stable_for_same_atom():
    a = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    b = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    assert listing_key(a) == listing_key(b)


def test_expire_helper_skips_when_incomplete(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    with open_db(db) as conn:
        upsert_listings(conn, [wts, wtb], now_unix_s=1)
        upsert_opportunities(conn, opps, now_unix_s=1)
        n = expire_absent_opportunities(
            conn, seen_keys=[], now_unix_s=2, complete=False
        )
        assert n == 0
        assert conn.execute("SELECT status FROM opportunities").fetchone()[0] == "new"


def test_opportunity_details_join_original_messages(tmp_path):
    db = tmp_path / "t.sqlite"
    wts = _listing("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _listing("WTB mallyx shield 55k", player="Bob", native_id="b1")
    with open_db(db) as conn:
        persist_scan(
            conn,
            listings=[wts, wtb],
            opportunities=match_listings([wts, wtb]),
            requested_sources=("decltype",),
            fetched_from=("decltype",),
            message_count=2,
            errors=[],
            query=None,
            started_at_unix_s=1,
            finished_at_unix_s=2,
        )
        details = list_opportunity_details(conn, "new")
    assert len(details) == 1
    assert "mallyx shield 50k" in (details[0]["wts_message"] or "")
    assert "mallyx shield 55k" in (details[0]["wtb_message"] or "")
    assert details[0]["wts_player"] == "Ann"
    assert details[0]["wtb_player"] == "Bob"
