from __future__ import annotations

from unittest.mock import patch

from gwtradearb.collect import CollectResult
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message
from gwtradearb.scan import run_scan_cycle


def test_run_scan_cycle_persists_and_logs(tmp_path):
    wts = parse_message(RawMessage("decltype", "1", 1_700_000_000, "Ann", "WTS mallyx shield 50k"))
    wtb = parse_message(RawMessage("decltype", "2", 1_700_000_010, "Bob", "WTB mallyx shield 55k"))
    collected = CollectResult(
        messages=[wts[0].raw, wtb[0].raw],
        listings=wts + wtb,
        fetched_from=["decltype"],
        errors=["gwtoolbox: down"],
    )
    db = tmp_path / "t.sqlite"
    logs: list[str] = []
    with patch("gwtradearb.scan.collect", return_value=collected):
        result = run_scan_cycle(db, log=logs.append)
    assert result.source_online["decltype"] is True
    assert result.source_online["gwtoolbox"] is False
    assert result.persist["opportunities"] == 1
    assert any("Scan started" in line for line in logs)
    assert any("Decltype:" in line for line in logs)
    assert any("Offline" in line for line in logs)
    assert any("Scan complete" in line for line in logs)
    assert db.is_file()
