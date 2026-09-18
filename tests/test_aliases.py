from __future__ import annotations

from gwtradearb.matching.aliases import canonical_item, normalise_item_name


def test_casefold_ecto_variants_share_a_key():
    keys = {
        canonical_item("ecto"),
        canonical_item("Ecto"),
        canonical_item("ECTO"),
        canonical_item("ectos"),
        canonical_item("Ectos"),
        canonical_item("ECTOS"),
        canonical_item("ectoplasm"),
        canonical_item("Glob of Ectoplasm"),
    }
    assert keys == {"glob of ectoplasm"}


def test_casefold_and_plural_lockpick():
    assert canonical_item("lockpick") == canonical_item("Lockpicks") == "lockpick"
    assert canonical_item("LOCKPICKS") == "lockpick"


def test_armbrace_alias_includes_arms():
    assert canonical_item("armbrace") == canonical_item("Armbraces") == canonical_item("arms")
    assert canonical_item("ARMS") == "armbrace"


def test_light_plural_without_alias_table():
    assert canonical_item("mallyx shield") == canonical_item("Mallyx Shields")
    assert canonical_item("Mallyx Shields") == "mallyx shield"


def test_focus_is_not_over_singularised():
    assert canonical_item("focus") == "focus"
    assert canonical_item("Focus") == "focus"


def test_normalise_uses_casefold():
    assert normalise_item_name("ECTOS") == "ectos"
    assert normalise_item_name("  Mallyx   Shield!! ") == "mallyx shield"
