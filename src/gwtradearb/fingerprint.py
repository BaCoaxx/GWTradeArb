"""Dedup helpers: within-source native ids and cross-source content fingerprints."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Sequence

_DASHES = re.compile(r"[\u2010-\u2015]")
_WHITESPACE = re.compile(r"\s+")


def normalise_player(player: str) -> str:
    text = unicodedata.normalize("NFKC", player).strip().lower()
    return _WHITESPACE.sub(" ", text)


def normalise_message(message: str) -> str:
    text = unicodedata.normalize("NFKC", message).strip().lower()
    text = _DASHES.sub("-", text)
    return _WHITESPACE.sub(" ", text)


def content_fingerprint(player: str, message: str) -> str:
    """SHA-256 of normalised player + message. Used later to collapse cross-source dupes."""
    payload = f"{normalise_player(player)}\n{normalise_message(message)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def native_key(source: str, native_id: str) -> tuple[str, str]:
    return (source, native_id)


def dedupe_by_native_id(messages: Sequence) -> list:
    """Keep first occurrence of each (source, native_id)."""
    seen: set[tuple[str, str]] = set()
    out: list = []
    for msg in messages:
        key = msg.native_key()
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
    return out


def group_by_fingerprint(messages: Iterable) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for msg in messages:
        grouped.setdefault(msg.content_fingerprint, []).append(msg)
    return grouped
