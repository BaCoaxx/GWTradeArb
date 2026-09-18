"""Live HTTP smokes. Skip automatically when offline.

CI can also exclude them with: pytest -m 'not network'
"""

from __future__ import annotations

import os

import pytest

from gwtradearb.scrapers.decltype import fetch_live as decltype_live
from gwtradearb.scrapers.gwtoolbox import fetch_live as gwtoolbox_live
from gwtradearb.scrapers.http import SourceFetchError

pytestmark = pytest.mark.network

skip_requested = pytest.mark.skipif(
    os.environ.get("GWTRADEARB_OFFLINE") == "1",
    reason="GWTRADEARB_OFFLINE=1",
)


def _skip_if_offline(exc: SourceFetchError) -> None:
    pytest.skip(f"live source unavailable: {exc}")


@skip_requested
def test_decltype_live_fetch():
    try:
        messages = decltype_live(timeout_s=20)
    except SourceFetchError as exc:
        _skip_if_offline(exc)
    assert messages, "decltype live returned no messages"
    assert 10 <= len(messages) <= 50
    row = messages[0]
    assert row.source == "decltype"
    assert row.native_id
    assert row.player
    assert row.timestamp_unix_s > 1_000_000_000


@skip_requested
def test_gwtoolbox_live_fetch():
    try:
        messages = gwtoolbox_live(timeout_s=20)
    except SourceFetchError as exc:
        _skip_if_offline(exc)
    assert messages, "gwtoolbox live returned no messages"
    assert 20 <= len(messages) <= 150
    row = messages[0]
    assert row.source == "gwtoolbox"
    assert row.native_id.isdigit()
    assert row.player
    assert row.timestamp_unix_s > 1_000_000_000


