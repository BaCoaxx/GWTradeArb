from __future__ import annotations

from decimal import Decimal

from gwtradearb.parsing.parser import parse_text


def _high(message: str):
    return [row for row in parse_text(message) if row.parse_confidence == "high"]


def test_simple_wts_gold():
    listings = parse_text("WTS mallyx shield 50k")
    assert len(listings) == 1
    row = listings[0]
    assert row.intent == "WTS"
    assert row.item.lower() == "mallyx shield"
    assert row.quantity == 1
    assert row.quantity_unit == "each"
    assert row.price_amount == Decimal("50000")
    assert row.price_unit == "gold"
    assert row.parse_confidence == "high"


def test_simple_wtb_gold():
    listings = parse_text("WTB lockpicks, 1k each")
    assert len(listings) == 1
    row = listings[0]
    assert row.intent == "WTB"
    assert "lockpick" in row.item.lower()
    assert row.quantity == 1
    assert row.quantity_unit == "each"
    assert row.price_amount == Decimal("1000")
    assert row.price_unit == "gold"
    assert row.parse_confidence == "high"


def test_simple_wts_gold_ana_dash():
    listings = _high("WTS AnA - 45k")
    assert len(listings) == 1
    assert listings[0].item.lower() == "ana"
    assert listings[0].price_amount == Decimal("45000")


def test_multi_intent_split():
    listings = parse_text("WTS Armbraces 30e/ea -- WTB Mini Rift Warden 15a")
    assert len(listings) == 2
    sell, buy = listings
    assert sell.intent == "WTS"
    assert "armbrace" in sell.item.lower()
    assert sell.price_unit == "ecto"
    assert sell.price_amount == Decimal("30")
    assert sell.quantity == 1
    assert sell.parse_confidence == "low"
    assert "non_gold_price" in sell.reasons

    assert buy.intent == "WTB"
    assert "rift warden" in buy.item.lower()
    assert buy.price_unit == "armbrace"
    assert buy.price_amount == Decimal("15")
    assert buy.parse_confidence == "low"
    assert "non_gold_price" in buy.reasons
    assert _high("WTS Armbraces 30e/ea -- WTB Mini Rift Warden 15a") == []


def test_ecto_and_armbrace_marked_non_gold():
    ecto = parse_text("WTS Armbraces 30e/ea")[0]
    assert ecto.price_unit == "ecto"
    assert ecto.parse_confidence == "low"
    assert ecto.price_amount == Decimal("30")

    arms = parse_text("WTS Hero boxes 12a")[0]
    assert arms.price_unit == "armbrace"
    assert arms.parse_confidence == "low"
    assert arms.price_amount == Decimal("12")


def test_unparseable_lines_produce_no_high_confidence_listing():
    samples = [
        "hello kamadan",
        "WTB Cheap bds",
        "WTS Miniatures : Dedicaced Grawl",
        "WTT Celestials (Me) pig or Dog",
        "Wtb———-Q9 Vs pm your price———-!",
        "PC ecto",
        "WTB RESTO FROGGY pm me",
    ]
    for message in samples:
        assert _high(message) == [], message


def test_wtt_is_not_high_confidence():
    listings = parse_text("WTT Celestials pig or dog")
    assert all(row.parse_confidence == "low" for row in listings)
    assert all(row.intent == "WTT" for row in listings)


def test_quantity_x2():
    listings = _high("WTS widget x2 50k")
    assert listings[0].quantity == 2
    assert listings[0].price_amount == Decimal("50000")

    listings = _high("WTS widget 50k x2")
    assert listings[0].quantity == 2


def test_quantity_paren_5x():
    listings = _high("WTS widget (5x) 50k")
    assert listings[0].quantity == 5
    assert listings[0].price_unit == "gold"


def test_quantity_eight_for_100k():
    listings = _high("WTB Ectos 8 for 100k")
    assert len(listings) == 1
    row = listings[0]
    assert row.intent == "WTB"
    assert "ecto" in row.item.lower()
    assert row.quantity == 8
    assert row.price_amount == Decimal("100000")
    assert row.price_unit == "gold"


def test_quantity_eight_for_100k_with_lot_marker_keeps_bundle_size():
    listings = _high("WTB Ectos 8 for 100k (5x)")
    assert listings[0].quantity == 8
    assert listings[0].price_amount == Decimal("100000")


def test_quantity_leading_count_without_for():
    listings = _high("wts 8 ectos 100k")
    assert listings[0].quantity == 8
    assert listings[0].price_amount == Decimal("100000")
    assert "ecto" in listings[0].item.lower()


def test_quantity_ea_and_stack():
    each = _high("WTS ectos 13k/ea")[0]
    assert each.quantity == 1
    assert each.quantity_unit == "each"
    assert each.price_amount == Decimal("13000")

    stack = _high("WTS warhorns 50k/stack")[0]
    assert stack.quantity == 1
    assert stack.quantity_unit == "stack"
    assert stack.price_amount == Decimal("50000")

    stk = parse_text("WTB Rezz Scrolls 2a/stk")[0]
    assert stk.quantity_unit == "stack"
    assert stk.price_unit == "armbrace"
    assert stk.parse_confidence == "low"


def test_decimal_comma_gold():
    listings = _high("WTB ectos 12,5k ea")
    assert listings[0].price_amount == Decimal("12500")
    listings = _high("WTB ectos 12.5k ea")
    assert listings[0].price_amount == Decimal("12500")


def test_slash_bundle_without_e_unit():
    listings = _high("WTS ectos 8/100k")
    assert listings[0].quantity == 8
    assert listings[0].price_amount == Decimal("100000")
    assert listings[0].item.lower() == "ectos"


def test_ecto_word_between_qty_and_for():
    listings = _high("WTS 8 ecto for 100k")
    assert listings[0].quantity == 8
    assert listings[0].price_amount == Decimal("100000")
    assert listings[0].item.lower() == "ecto"


def test_paren_lot_does_not_leave_empty_parens_in_item():
    listings = _high("WTS 7 ecto 100k (x2)")
    assert listings[0].quantity == 7
    assert "(" not in listings[0].item


def test_ecto_slash_gold_bundle():
    listings = _high("WTB ecto 8e/100k")
    assert listings[0].quantity == 8
    assert listings[0].price_amount == Decimal("100000")
    assert listings[0].price_unit == "gold"


def test_equals_bundle():
    listings = _high("WTS ectos 7=100k")
    assert listings[0].quantity == 7
    assert listings[0].price_amount == Decimal("100000")


def test_same_intent_multi_price_is_not_high():
    listings = parse_text("WTS Grog 9e/stack styg gem 2.5a/stack")
    assert listings
    assert all(row.parse_confidence == "low" for row in listings)


def test_case_insensitive_intent_and_stars():
    listings = _high("***WTS ECTO 13k/ea***")
    assert listings[0].item.lower() == "ecto"
    assert listings[0].price_amount == Decimal("13000")


def test_mid_message_wtb_after_wts():
    listings = parse_text("WTS arms 30e ea - trade me WTB Mini Rift Warden 15a")
    assert [row.intent for row in listings] == ["WTS", "WTB"]
    assert listings[0].price_unit == "ecto"
    assert listings[1].price_unit == "armbrace"


def test_parser_never_invents_a_gold_price():
    listings = parse_text("WTS Eternal Blade")
    assert listings[0].price_amount is None
    assert listings[0].parse_confidence == "low"
