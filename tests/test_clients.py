from __future__ import annotations

from unittest.mock import patch

import pytest

from gwtradearb.scrapers.decltype import parse_payload as parse_decltype
from gwtradearb.scrapers.gwtoolbox import parse_payload as parse_gwtoolbox
from gwtradearb.scrapers.http import USER_AGENT, SourceFetchError
from tests.conftest import load_fixture


def test_decltype_live_fixture_normalises_fields():
    payload = load_fixture("decltype_live.json")
    messages = parse_decltype(payload)
    assert len(messages) == len(payload["results"])
    assert len(messages) >= 20
    first = messages[0]
    raw = payload["results"][0]
    assert first.source == "decltype"
    assert first.native_id == str(raw["id"])
    assert first.timestamp_unix_s == int(raw["timestamp"])
    assert first.player == raw["name"]
    assert first.message == raw["message"]
    assert first.replaces_id is None
    assert len(first.content_fingerprint) == 64


def test_decltype_search_fixture_uses_same_shape():
    payload = load_fixture("decltype_search_ecto.json")
    messages = parse_decltype(payload)
    assert messages
    assert all(row.source == "decltype" for row in messages)
    assert any("ecto" in row.message.lower() for row in messages)


def test_gwtoolbox_live_fixture_uses_t_as_native_id():
    payload = load_fixture("gwtoolbox_live.json")
    messages = parse_gwtoolbox(payload)
    assert len(messages) == 100
    first = messages[0]
    raw = payload[0]
    assert first.source == "gwtoolbox"
    assert first.native_id == str(raw["t"])
    assert first.timestamp_unix_s == int(raw["t"]) // 1000
    assert first.player == raw["s"]
    assert first.message == raw["m"]
    if "r" in raw:
        assert first.replaces_id == str(raw["r"])


def test_gwtoolbox_search_fixture_accepts_wrapped_results():
    payload = load_fixture("gwtoolbox_search_ecto.json")
    messages = parse_gwtoolbox(payload)
    assert len(messages) == len(payload["results"])
    assert all(row.source == "gwtoolbox" for row in messages)
    # Search payloads encode t as a string; native id must still be digits.
    assert messages[0].native_id.isdigit()
    assert messages[0].timestamp_unix_s == int(payload["results"][0]["t"]) // 1000


def test_decltype_rejects_malformed_payload():
    with pytest.raises(SourceFetchError):
        parse_decltype([])
    with pytest.raises(SourceFetchError):
        parse_decltype({"results": [{"id": "1"}]})


def test_gwtoolbox_rejects_malformed_payload():
    with pytest.raises(SourceFetchError):
        parse_gwtoolbox("nope")
    with pytest.raises(SourceFetchError):
        parse_gwtoolbox([{"s": "x", "m": "WTS"}])


def test_user_agent_identifies_the_app():
    assert "GWTradeArb" in USER_AGENT
    assert "no game automation" in USER_AGENT


def test_one_source_failure_does_not_break_the_other():
    from gwtradearb.collect import collect
    from gwtradearb.models import RawMessage

    ok = [
        RawMessage(
            source="gwtoolbox",
            native_id="1",
            timestamp_unix_s=1,
            player="Trader001",
            message="WTS widget 50k",
        )
    ]

    with (
        patch("gwtradearb.collect.decltype_live", side_effect=SourceFetchError("decltype", "down")),
        patch("gwtradearb.collect.gwtoolbox_live", return_value=ok),
    ):
        result = collect(sources=("decltype", "gwtoolbox"))

    assert result.fetched_from == ["gwtoolbox"]
    assert result.errors and result.errors[0].startswith("decltype:")
    assert len(result.messages) == 1
    assert result.high_listings
