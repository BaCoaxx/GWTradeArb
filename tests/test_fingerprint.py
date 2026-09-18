from __future__ import annotations

from gwtradearb.models import RawMessage
from gwtradearb.fingerprint import (
    content_fingerprint,
    dedupe_by_native_id,
    group_by_fingerprint,
    normalise_message,
    normalise_player,
)


def test_native_id_dedup_within_source():
    first = RawMessage("decltype", "10", 1, "Ann", "WTS foo 50k")
    dup = RawMessage("decltype", "10", 2, "Ann", "WTS foo 50k")
    other_source = RawMessage("gwtoolbox", "10", 1, "Ann", "WTS foo 50k")
    other_id = RawMessage("decltype", "11", 1, "Ann", "WTS foo 50k")
    out = dedupe_by_native_id([first, dup, other_source, other_id])
    assert [row.native_key() for row in out] == [
        ("decltype", "10"),
        ("gwtoolbox", "10"),
        ("decltype", "11"),
    ]


def test_content_fingerprint_is_stable_across_spacing_and_case():
    a = content_fingerprint("Ann Player", "WTS  Foo   50k")
    b = content_fingerprint("  ann   player ", "wts foo 50k")
    assert a == b
    assert len(a) == 64
    assert a != content_fingerprint("Ann Player", "WTS Foo 51k")


def test_fingerprint_normalises_unicode_dashes():
    assert normalise_message("WTS foo — 50k") == normalise_message("WTS foo - 50k")
    assert normalise_player("  Trader  One ") == "trader one"


def test_cross_source_collapse_key():
    decltype = RawMessage("decltype", "1", 1, "Ann", "WTS foo 50k")
    toolbox = RawMessage("gwtoolbox", "999", 1, "Ann", "WTS foo 50k")
    assert decltype.content_fingerprint == toolbox.content_fingerprint
    grouped = group_by_fingerprint([decltype, toolbox])
    assert len(grouped) == 1
