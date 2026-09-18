from __future__ import annotations

from unittest.mock import patch

from gwtradearb.cli import main
from gwtradearb.collect import CollectResult
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message


def _collect_pair() -> CollectResult:
    wts = parse_message(
        RawMessage("decltype", "1", 1_700_000_000, "Ann", "WTS mallyx shield 50k")
    )
    wtb = parse_message(
        RawMessage("decltype", "2", 1_700_000_010, "Bob", "WTB mallyx shield 55k")
    )
    return CollectResult(
        messages=[wts[0].raw, wtb[0].raw],
        listings=wts + wtb,
        fetched_from=["decltype"],
    )


def test_match_cli_prints_opportunity(capsys):
    with patch("gwtradearb.cli.collect", return_value=_collect_pair()):
        code = main(["--match"])
    captured = capsys.readouterr()
    assert code == 0
    assert "opportunities=1" in captured.out
    assert "potential_difference" in captured.out
    assert "+5000 gold" in captured.out
    assert "not guaranteed profit" in captured.out


def test_scan_cli_persists_and_stats(tmp_path, capsys):
    db = tmp_path / "gw.sqlite"
    with patch("gwtradearb.cli.collect", return_value=_collect_pair()):
        assert main(["--scan", "--db", str(db), "--source", "decltype"]) == 0
    capsys.readouterr()
    assert db.is_file()
    code = main(["--stats", "--db", str(db)])
    out = capsys.readouterr().out
    assert code == 0
    assert "scans=1" in out
    assert "new=1" in out
    assert "traded=0" in out
    code = main(["--list", "--db", str(db)])
    listed = capsys.readouterr().out
    assert code == 0
    assert "[new" in listed
    assert "mallyx shield" in listed


def test_mark_traded_cli(tmp_path, capsys):
    db = tmp_path / "gw.sqlite"
    with patch("gwtradearb.cli.collect", return_value=_collect_pair()):
        main(["--scan", "--db", str(db), "--source", "decltype", "--json"])
    import json as json_lib

    payload = json_lib.loads(capsys.readouterr().out)
    key = payload["opportunities"][0]["opportunity_key"]
    assert main(["--mark", key[:16], "traded", "--db", str(db)]) == 0
    capsys.readouterr()
    main(["--list", "--status", "traded", "--db", str(db)])
    out = capsys.readouterr().out
    assert "[traded" in out
    main(["--list", "--status", "new", "--db", str(db)])
    assert "no new opportunities" in capsys.readouterr().out

