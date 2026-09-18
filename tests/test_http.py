from __future__ import annotations

from unittest.mock import patch

import pytest

from gwtradearb.scrapers.decltype import search as search_decltype
from gwtradearb.scrapers.gwtoolbox import search as search_gwtoolbox
from gwtradearb.scrapers.http import SourceFetchError, get_json


def test_get_json_wraps_network_errors():
    with patch("gwtradearb.scrapers.http.urllib.request.urlopen", side_effect=TimeoutError()):
        with pytest.raises(SourceFetchError) as exc:
            get_json("https://example.invalid/api", source="decltype", timeout_s=1)
        assert exc.value.source == "decltype"
        assert "timed out" in str(exc.value)


def test_get_json_wraps_invalid_json():
    class _Resp:
        status = 200

        def read(self, _n):
            return b"not-json"

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("gwtradearb.scrapers.http.urllib.request.urlopen", return_value=_Resp()):
        with pytest.raises(SourceFetchError) as exc:
            get_json("https://example.invalid/api", source="gwtoolbox")
        assert "invalid JSON" in str(exc.value)


def test_search_helpers_url_encode_queries():
    with patch("gwtradearb.scrapers.decltype.get_json", return_value={"results": []}) as mocked:
        search_decltype("ecto blade")
        url = mocked.call_args[0][0]
        assert "/api/search/" in url
        assert " " not in url
        assert "ecto" in url

    with patch("gwtradearb.scrapers.gwtoolbox.get_json", return_value={"results": []}) as mocked:
        search_gwtoolbox("ecto blade")
        url = mocked.call_args[0][0]
        assert "/s/" in url
        assert " " not in url
