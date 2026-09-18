"""Explicit Kamadan item aliases. Full-string match after normalisation only."""

from __future__ import annotations

import re
import unicodedata

# Canonical name on the right. Keep this table small and tested; do not fuzzy-match.
ITEM_ALIASES: dict[str, str] = {
    "ecto": "glob of ectoplasm",
    "ectos": "glob of ectoplasm",
    "ectoplasm": "glob of ectoplasm",
    "ecto glob": "glob of ectoplasm",
    "glob of ectoplasm": "glob of ectoplasm",
    "globs of ectoplasm": "glob of ectoplasm",
    "lockpick": "lockpick",
    "lockpicks": "lockpick",
}

_NON_ITEM = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_item_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).lower().strip()
    text = _NON_ITEM.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def canonical_item(name: str | None) -> str | None:
    """Return a comparable item key, or None if the name is empty after normalisation."""
    if not name:
        return None
    normalised = normalise_item_name(name)
    if not normalised:
        return None
    return ITEM_ALIASES.get(normalised, normalised)
