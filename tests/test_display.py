from __future__ import annotations

from decimal import Decimal

import pytest

from gwtradearb.cli import _wants_gui, build_parser
from gwtradearb.display import format_gold, row_matches_filters


def test_help_text_encodes_to_cp1252():
    # Packaged Windows consoles often use cp1252. --help must not raise UnicodeEncodeError.
    help_text = build_parser().format_help()
    help_text.encode("cp1252")
    assert "WTS/WTB" in help_text
    assert "--lookback-hours" in help_text


def test_wants_gui_by_default_and_not_with_cli_actions():
    parser = build_parser()
    assert _wants_gui(parser.parse_args([])) is True
    assert _wants_gui(parser.parse_args(["--gui"])) is True
    assert _wants_gui(parser.parse_args(["--db", "x.sqlite"])) is True
    assert _wants_gui(parser.parse_args(["--scan"])) is False
    assert _wants_gui(parser.parse_args(["--match"])) is False
    assert _wants_gui(parser.parse_args(["--stats"])) is False
    assert _wants_gui(parser.parse_args(["--list"])) is False
    assert _wants_gui(parser.parse_args(["--lookback-hours", "24"])) is True
    assert _wants_gui(parser.parse_args(["--scan", "--lookback-hours", "24"])) is False


def test_lookback_hours_cli_bounds():
    parser = build_parser()
    assert parser.parse_args(["--lookback-hours", "12"]).lookback_hours == 12
    assert parser.parse_args(["--lookback-hours", "72"]).lookback_hours == 72
    with pytest.raises(SystemExit):
        parser.parse_args(["--lookback-hours", "6"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--lookback-hours", "0"])


def test_format_gold_and_filters():
    assert format_gold(Decimal("50000")) == "50k gold"
    assert format_gold("5000") == "5k gold"
    row = {
        "item_canonical": "glob of ectoplasm",
        "seller": "Ann",
        "buyer": "Bob",
        "sources": '["decltype"]',
        "potential_difference": "4000",
    }
    assert row_matches_filters(row, item_query="ECTO")
    assert not row_matches_filters(row, item_query="mallyx")
    assert row_matches_filters(row, source="decltype")
    assert not row_matches_filters(row, source="gwtoolbox")
    assert row_matches_filters(row, min_difference=Decimal("4000"))
    assert not row_matches_filters(row, min_difference=Decimal("4001"))
