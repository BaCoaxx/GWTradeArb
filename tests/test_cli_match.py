from __future__ import annotations

from unittest.mock import patch

from gwtradearb.cli import main
from gwtradearb.collect import CollectResult
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message


def test_match_cli_prints_opportunity(capsys):
    wts = parse_message(
        RawMessage("decltype", "1", 1_700_000_000, "Ann", "WTS mallyx shield 50k")
    )
    wtb = parse_message(
        RawMessage("decltype", "2", 1_700_000_010, "Bob", "WTB mallyx shield 55k")
    )
    result = CollectResult(
        messages=[wts[0].raw, wtb[0].raw],
        listings=wts + wtb,
        fetched_from=["decltype"],
    )
    with patch("gwtradearb.cli.collect", return_value=result):
        code = main(["--match"])
    captured = capsys.readouterr()
    assert code == 0
    assert "opportunities=1" in captured.out
    assert "potential_difference" in captured.out
    assert "+5000 gold" in captured.out
    assert "not guaranteed profit" in captured.out
