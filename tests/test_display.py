from __future__ import annotations

from decimal import Decimal

from gwtradearb.cli import _wants_gui, build_parser
from gwtradearb.display import format_gold, row_matches_filters


def test_wants_gui_by_default_and_not_with_cli_actions():
    parser = build_parser()
    assert _wants_gui(parser.parse_args([])) is True
    assert _wants_gui(parser.parse_args(["--gui"])) is True
    assert _wants_gui(parser.parse_args(["--db", "x.sqlite"])) is True
    assert _wants_gui(parser.parse_args(["--scan"])) is False
    assert _wants_gui(parser.parse_args(["--match"])) is False
    assert _wants_gui(parser.parse_args(["--stats"])) is False
    assert _wants_gui(parser.parse_args(["--list"])) is False


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
