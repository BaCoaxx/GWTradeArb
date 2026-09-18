"""Item name canonicalisation for matching.

Case-insensitive (str.casefold), then an explicit alias table, then a light
singularisation of the last token so `Ectos` / `ecto` / `ECTOS` share a key.
No fuzzy matching and no LLM.
"""

from __future__ import annotations

import re
import unicodedata

# Full-string keys must already be casefolded. Canonical form is the value.
ITEM_ALIASES: dict[str, str] = {
    "ecto": "glob of ectoplasm",
    "ectos": "glob of ectoplasm",
    "ectoplasm": "glob of ectoplasm",
    "ecto glob": "glob of ectoplasm",
    "ectos glob": "glob of ectoplasm",
    "glob of ectoplasm": "glob of ectoplasm",
    "globs of ectoplasm": "glob of ectoplasm",
    "lockpick": "lockpick",
    "lockpicks": "lockpick",
    "armbrace": "armbrace",
    "armbraces": "armbrace",
    "arms": "armbrace",
    "warhorn": "warhorn",
    "warhorns": "warhorn",
    "conset": "consumable set",
    "consets": "consumable set",
    "consumable set": "consumable set",
    "consumable sets": "consumable set",
}

_NON_ITEM = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_item_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold().strip()
    text = _NON_ITEM.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _singularise_last_token(text: str) -> str:
    """Light English plural fold on the final word only.

    Skips short tokens and common non-plural endings (ss/us/is) so `focus`
    does not become `focu`.
    """
    parts = text.split()
    if not parts:
        return text
    word = parts[-1]
    if len(word) <= 3:
        return text
    if word.endswith(("ss", "us", "is")):
        return text
    if word.endswith("ies") and len(word) > 4:
        parts[-1] = word[:-3] + "y"
        return " ".join(parts)
    if word.endswith(("ches", "shes")) or (
        word.endswith("es") and len(word) > 4 and word[-3] in "sxz"
    ):
        parts[-1] = word[:-2]
        return " ".join(parts)
    if word.endswith("s"):
        parts[-1] = word[:-1]
        return " ".join(parts)
    return text


def canonical_item(name: str | None) -> str | None:
    """Return a comparable item key, or None if the name is empty after normalisation."""
    if not name:
        return None
    normalised = normalise_item_name(name)
    if not normalised:
        return None
    if normalised in ITEM_ALIASES:
        return ITEM_ALIASES[normalised]
    folded = _singularise_last_token(normalised)
    if folded in ITEM_ALIASES:
        return ITEM_ALIASES[folded]
    return folded
