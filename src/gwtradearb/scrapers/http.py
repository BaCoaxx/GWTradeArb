"""Polite HTTP helper for public JSON endpoints.

Identifies this app, uses timeouts, and never retries aggressively.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from gwtradearb import __version__

USER_AGENT = (
    f"GWTradeArb/{__version__} (Kamadan public JSON scanner; scrape-parse-display only; "
    "no game automation; +https://kamadan.decltype.org/)"
)
DEFAULT_TIMEOUT_S = 15.0
MAX_BYTES = 2_000_000


class SourceFetchError(Exception):
    """Raised when a single public source cannot be fetched or parsed."""

    def __init__(
        self,
        source: str,
        message: str,
        *,
        status: int | None = None,
        url: str | None = None,
    ) -> None:
        self.source = source
        self.status = status
        self.url = url
        super().__init__(f"{source}: {message}")


def quote_path_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def get_json(
    url: str,
    *,
    source: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain;q=0.8, */*;q=0.5",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = getattr(response, "status", None) or response.getcode()
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SourceFetchError(
            source,
            f"HTTP {exc.code} {exc.reason}",
            status=exc.code,
            url=url,
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise SourceFetchError(source, f"network error: {reason}", url=url) from exc
    except TimeoutError as exc:
        raise SourceFetchError(source, f"timed out after {timeout_s:.0f}s", url=url) from exc

    if status and status >= 400:
        raise SourceFetchError(source, f"HTTP {status}", status=status, url=url)
    if len(raw) > MAX_BYTES:
        raise SourceFetchError(source, f"response larger than {MAX_BYTES} bytes", url=url)

    try:
        text = raw.decode("utf-8")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFetchError(source, f"invalid JSON: {exc}", url=url) from exc
