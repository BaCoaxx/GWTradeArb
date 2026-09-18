"""GWToolbox public JSON client (https://kamadan.gwtoolbox.com/).

Live:   GET /m           → JSON array of ~100 latest messages
Search: GET /s/{query}   → object with `results` (and `num_results`)

Fields: t (Unix milliseconds, used as native id), s (sender), m (message),
optional r (opaque replacement token for a prior send of the same line).

v1 uses HTTP only. Do not depend on the LZ-compressed WebSocket feed.
Does not touch Guild Wars itself.
"""

from __future__ import annotations

from typing import Any

from gwtradearb.models import RawMessage
from gwtradearb.scrapers.http import SourceFetchError, get_json, quote_path_segment

SOURCE = "gwtoolbox"
LIVE_URL = "https://kamadan.gwtoolbox.com/m"
SEARCH_URL_TEMPLATE = "https://kamadan.gwtoolbox.com/s/{query}"


def _as_millis(value: Any) -> int:
    if value is None:
        raise SourceFetchError(SOURCE, "message missing t")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SourceFetchError(SOURCE, f"invalid t {value!r}") from exc


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return results
        raise SourceFetchError(SOURCE, "payload object missing results list")
    raise SourceFetchError(SOURCE, "expected a JSON array or an object with results")


def parse_payload(payload: Any) -> list[RawMessage]:
    """Normalise a GWToolbox live array or search object into RawMessage rows."""
    rows = _rows_from_payload(payload)
    messages: list[RawMessage] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceFetchError(SOURCE, f"result {index} is not an object")
        millis = _as_millis(row.get("t"))
        player = str(row.get("s") or "").strip()
        message = str(row.get("m") or "")
        if not player:
            raise SourceFetchError(SOURCE, f"result {index} missing s")
        replaces = row.get("r")
        replaces_id = str(replaces) if replaces is not None and str(replaces) != "" else None
        messages.append(
            RawMessage(
                source=SOURCE,
                native_id=str(millis),
                timestamp_unix_s=millis // 1000,
                player=player,
                message=message,
                replaces_id=replaces_id,
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
