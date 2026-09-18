"""Decltype public JSON client (https://kamadan.decltype.org/).

Live:  GET /api/            → wrapped object with ~25 latest `results`
Search: GET /api/search/{q} → same shape

Fields: id, timestamp (Unix seconds), name, message.
Does not touch Guild Wars itself.
"""

from __future__ import annotations

from typing import Any

from gwtradearb.models import RawMessage
from gwtradearb.scrapers.http import SourceFetchError, get_json, quote_path_segment

SOURCE = "decltype"
LIVE_URL = "https://kamadan.decltype.org/api/"
SEARCH_URL_TEMPLATE = "https://kamadan.decltype.org/api/search/{query}"


def _as_str_id(value: Any) -> str:
    if value is None:
        raise SourceFetchError(SOURCE, "message missing id")
    text = str(value).strip()
    if not text:
        raise SourceFetchError(SOURCE, "message has empty id")
    return text


def _as_unix_seconds(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SourceFetchError(SOURCE, f"invalid timestamp {value!r}") from exc


def parse_payload(payload: Any) -> list[RawMessage]:
    """Normalise a decltype live or search JSON payload into RawMessage rows."""
    if not isinstance(payload, dict):
        raise SourceFetchError(SOURCE, "expected a JSON object with a results array")
    results = payload.get("results")
    if results is None:
        raise SourceFetchError(SOURCE, "payload missing results")
    if not isinstance(results, list):
        raise SourceFetchError(SOURCE, "results is not a list")

    messages: list[RawMessage] = []
    for index, row in enumerate(results):
        if not isinstance(row, dict):
            raise SourceFetchError(SOURCE, f"result {index} is not an object")
        try:
            native_id = _as_str_id(row.get("id"))
            timestamp = _as_unix_seconds(row.get("timestamp"))
            player = str(row.get("name") or "").strip()
            message = str(row.get("message") or "")
        except SourceFetchError:
            raise
        except (TypeError, ValueError) as exc:
            raise SourceFetchError(SOURCE, f"result {index} has invalid fields: {exc}") from exc
        if not player:
            raise SourceFetchError(SOURCE, f"result {index} missing name")
        messages.append(
            RawMessage(
                source=SOURCE,
                native_id=native_id,
                timestamp_unix_s=timestamp,
                player=player,
                message=message,
            )
        )
    return messages


def fetch_live(*, timeout_s: float | None = None) -> list[RawMessage]:
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    payload = get_json(LIVE_URL, source=SOURCE, **kwargs)
    return parse_payload(payload)


def search(query: str, *, timeout_s: float | None = None) -> list[RawMessage]:
    if not query or not query.strip():
        raise SourceFetchError(SOURCE, "search query is empty")
    url = SEARCH_URL_TEMPLATE.format(query=quote_path_segment(query.strip()))
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    payload = get_json(url, source=SOURCE, **kwargs)
    return parse_payload(payload)
