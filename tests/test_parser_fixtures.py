"""Parser over captured public JSON: must not crash or invent gold prices."""

from __future__ import annotations

from gwtradearb.parsing.parser import parse_message
from gwtradearb.scrapers.decltype import parse_payload as parse_decltype
from gwtradearb.scrapers.gwtoolbox import parse_payload as parse_gwtoolbox
from tests.conftest import load_fixture


def _all_fixture_messages():
    messages = []
    messages.extend(parse_decltype(load_fixture("decltype_live.json")))
    messages.extend(parse_decltype(load_fixture("decltype_search_ecto.json")))
    messages.extend(parse_gwtoolbox(load_fixture("gwtoolbox_live.json")))
    messages.extend(parse_gwtoolbox(load_fixture("gwtoolbox_search_ecto.json")))
    return messages


def test_parser_accepts_every_captured_public_message():
    listings = []
    for raw in _all_fixture_messages():
        listings.extend(parse_message(raw))
    assert listings, "expected at least some listing atoms from live captures"
    for row in listings:
        if row.parse_confidence == "high":
            assert row.intent in {"WTS", "WTB"}
            assert row.item
            assert row.quantity and row.quantity >= 1
            assert row.price_unit == "gold"
            assert row.price_amount is not None
            assert row.price_amount > 0
        if row.price_unit in {"ecto", "armbrace"}:
            assert row.parse_confidence == "low"


def test_high_confidence_listings_are_the_minority():
    listings = [atom for raw in _all_fixture_messages() for atom in parse_message(raw)]
    high = [row for row in listings if row.parse_confidence == "high"]
    assert len(high) < len(listings)
