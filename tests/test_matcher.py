from __future__ import annotations

from decimal import Decimal

from gwtradearb.matching.aliases import canonical_item
from gwtradearb.matching.matcher import fill_quantity, match_listings, opportunity_key, price_basis
from gwtradearb.models import RawMessage
from gwtradearb.parsing.parser import parse_message


def _raw(
    message: str,
    *,
    player: str,
    native_id: str,
    timestamp_unix_s: int = 1_700_000_000,
    source: str = "decltype",
) -> RawMessage:
    return RawMessage(
        source=source,  # type: ignore[arg-type]
        native_id=native_id,
        timestamp_unix_s=timestamp_unix_s,
        player=player,
        message=message,
    )


def _parsed(message: str, **kwargs):
    return parse_message(_raw(message, **kwargs))


def _high(message: str, **kwargs):
    rows = [row for row in _parsed(message, **kwargs) if row.parse_confidence == "high"]
    assert rows, (message, _parsed(message, **kwargs))
    return rows[0]


def test_canonical_item_aliases_ecto_family():
    assert canonical_item("ecto") == canonical_item("Ectos") == canonical_item("ectoplasm")
    assert canonical_item("Glob of Ectoplasm") == "glob of ectoplasm"
    assert canonical_item("lockpicks") == canonical_item("lockpick") == "lockpick"
    assert canonical_item("mallyx shield") == "mallyx shield"
    assert canonical_item("mallyx shield") != canonical_item("ectos")


def test_happy_path_equal_qty_unit_prices():
    wts = _high("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _high("WTB mallyx shield 55k", player="Bob", native_id="b1", timestamp_unix_s=1_700_000_100)
    opps = match_listings([wts, wtb])
    assert len(opps) == 1
    opp = opps[0]
    assert opp.item == "mallyx shield"
    assert opp.quantity == 1
    assert opp.seller == "Ann"
    assert opp.buyer == "Bob"
    assert opp.sell_price == Decimal("50000")
    assert opp.buy_price == Decimal("55000")
    assert opp.potential_difference == Decimal("5000")
    assert opp.price_unit == "gold"
    assert opp.wts is wts
    assert opp.wtb is wtb
    assert set(opp.sources) == {"decltype"}


def test_happy_path_equal_qty_lot_prices():
    wts = _high("WTS ectos 8 for 100k", player="Ann", native_id="s1")
    wtb = _high("WTB ectos 8 for 104k", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    assert len(opps) == 1
    assert opps[0].quantity == 8
    assert opps[0].item == "glob of ectoplasm"
    assert opps[0].sell_price == Decimal("100000")
    assert opps[0].buy_price == Decimal("104000")
    assert opps[0].potential_difference == Decimal("4000")
    assert price_basis(wts) == "lot"
    assert price_basis(wtb) == "lot"


def test_ecto_alias_matches_across_wording():
    wts = _high("WTS ecto 12k ea", player="Ann", native_id="s1")
    wtb = _high("WTB ectoplasm 13k each", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    assert len(opps) == 1
    assert opps[0].item == "glob of ectoplasm"
    assert opps[0].potential_difference == Decimal("1000")


def test_no_match_when_wts_price_not_lower():
    cheap_buy = _high("WTB mallyx shield 40k", player="Bob", native_id="b1")
    expensive_sell = _high("WTS mallyx shield 50k", player="Ann", native_id="s1")
    equal = _high("WTB mallyx shield 50k", player="Cara", native_id="b2")
    assert match_listings([expensive_sell, cheap_buy]) == []
    assert match_listings([expensive_sell, equal]) == []


def test_no_match_different_items():
    wts = _high("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _high("WTB lockpicks 55k", player="Bob", native_id="b1")
    assert match_listings([wts, wtb]) == []


def test_no_match_low_confidence():
    low_ecto = _parsed("WTS ectos 30e/ea", player="Ann", native_id="s1")[0]
    assert low_ecto.parse_confidence == "low"
    wtb = _high("WTB ectos 13k ea", player="Bob", native_id="b1")
    assert match_listings([low_ecto, wtb]) == []

    wts_gold = _high("WTS mallyx shield 50k", player="Ann", native_id="s2")
    low_buy = _parsed("WTB mallyx shield", player="Bob", native_id="b2")[0]
    assert low_buy.parse_confidence == "low"
    assert match_listings([wts_gold, low_buy]) == []


def test_no_match_same_player():
    wts = _high("WTS mallyx shield 50k", player="Ann Player", native_id="s1")
    wtb = _high("WTB mallyx shield 55k", player="  ann   player ", native_id="b1")
    assert match_listings([wts, wtb]) == []


def test_unequal_qty_skips_when_it_would_split_a_lot():
    lot = _high("WTS ectos 8 for 100k", player="Ann", native_id="s1")
    one = _high("WTB ectos 20k ea", player="Bob", native_id="b1")
    assert fill_quantity(lot, one) is None
    assert match_listings([lot, one]) == []


def test_unequal_qty_partial_fill_when_each_covers_a_whole_lot():
    lot = _high("WTS ectos 8 for 100k", player="Ann", native_id="s1")
    each = _high("WTB ectos 13k ea x10", player="Bob", native_id="b1")
    assert price_basis(lot) == "lot"
    assert price_basis(each) == "each"
    opps = match_listings([lot, each])
    assert len(opps) == 1
    assert opps[0].quantity == 8
    assert opps[0].sell_price == Decimal("100000")
    assert opps[0].buy_price == Decimal("104000")
    assert opps[0].potential_difference == Decimal("4000")


def test_unequal_qty_each_vs_each_uses_min():
    wts = _high("WTS lockpicks 1k each x2", player="Ann", native_id="s1")
    wtb = _high("WTB lockpicks 2k each x5", player="Bob", native_id="b1")
    opps = match_listings([wts, wtb])
    assert len(opps) == 1
    assert opps[0].quantity == 2
    assert opps[0].item == "lockpick"
    assert opps[0].sell_price == Decimal("2000")
    assert opps[0].buy_price == Decimal("4000")
    assert opps[0].potential_difference == Decimal("2000")


def test_no_match_stack_versus_each():
    stack = _high("WTS warhorns 50k/stack", player="Ann", native_id="s1")
    each = _high("WTB warhorns 55k ea", player="Bob", native_id="b1")
    assert stack.quantity_unit == "stack"
    assert each.quantity_unit == "each"
    assert match_listings([stack, each]) == []


def test_multi_listing_set_unique_opportunities():
    wts_a = _high("WTS mallyx shield 45k", player="Ann", native_id="s1", timestamp_unix_s=100)
    wts_b = _high("WTS mallyx shield 48k", player="Cara", native_id="s2", timestamp_unix_s=200)
    wtb = _high("WTB mallyx shield 50k", player="Bob", native_id="b1", timestamp_unix_s=300)
    other = _high("WTS lockpicks 1k each", player="Dan", native_id="s3")
    opps = match_listings([wts_a, wts_b, wtb, other])
    assert len(opps) == 2
    keys = {row.opportunity_key for row in opps}
    assert len(keys) == 2
    by_seller = {row.seller: row for row in opps}
    assert by_seller["Ann"].potential_difference == Decimal("5000")
    assert by_seller["Cara"].potential_difference == Decimal("2000")
    # Fresher pair first (buyer ts 300 with Cara 200 vs Ann 100 → max 300 both;
    # tie-break larger potential_difference, so Ann's 5000 ranks first).
    assert opps[0].seller == "Ann"


def test_fresher_listings_rank_first():
    old_wts = _high("WTS mallyx shield 40k", player="Ann", native_id="s1", timestamp_unix_s=10)
    old_wtb = _high("WTB mallyx shield 50k", player="Bob", native_id="b1", timestamp_unix_s=11)
    new_wts = _high("WTS mallyx shield 40k", player="Cara", native_id="s2", timestamp_unix_s=500)
    new_wtb = _high("WTB mallyx shield 50k", player="Dan", native_id="b2", timestamp_unix_s=501)
    opps = match_listings([old_wts, old_wtb, new_wts, new_wtb])
    assert len(opps) == 4  # each seller vs each buyer
    assert opps[0].freshness_unix_s >= opps[-1].freshness_unix_s
    assert opps[0].freshness_unix_s == 501


def test_opportunity_key_is_stable_and_collapses_mirrors():
    wts = _high("WTS mallyx shield 50k", player="Ann", native_id="s1")
    wtb = _high("WTB mallyx shield 55k", player="Bob", native_id="b1")
    first = match_listings([wts, wtb])
    second = match_listings([wtb, wts])
    assert first[0].opportunity_key == second[0].opportunity_key
    assert first[0].opportunity_key == opportunity_key(
        wts, wtb, "mallyx shield", 1
    )

    mirror = _high(
        "WTS mallyx shield 50k",
        player="Ann",
        native_id="999",
        source="gwtoolbox",
        timestamp_unix_s=1_700_000_050,
    )
    collapsed = match_listings([wts, mirror, wtb])
    assert len(collapsed) == 1
    assert collapsed[0].opportunity_key == first[0].opportunity_key


def test_same_chat_line_is_not_paired_with_its_mirror_as_counterparty():
    # Should not happen for WTS vs WTS, but fingerprint guard is explicit.
    left = _high("WTS mallyx shield 50k", player="Ann", native_id="1", source="decltype")
    right = _high("WTS mallyx shield 50k", player="Ann", native_id="2", source="gwtoolbox")
    assert left.raw.content_fingerprint == right.raw.content_fingerprint
    assert match_listings([left, right]) == []


def test_prices_are_gold_for_the_fill_qty_not_per_unit_when_qty_exceeds_one():
    wts = _high("WTS ectos 10k ea x3", player="Ann", native_id="s1")
    wtb = _high("WTB ectos 12k ea x3", player="Bob", native_id="b1")
    opp = match_listings([wts, wtb])[0]
    assert opp.quantity == 3
    assert opp.sell_price == Decimal("30000")
    assert opp.buy_price == Decimal("36000")
    assert opp.potential_difference == Decimal("6000")
