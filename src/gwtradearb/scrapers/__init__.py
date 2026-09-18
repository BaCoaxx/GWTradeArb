"""Shared scraper exports."""

from gwtradearb.scrapers.decltype import fetch_live as fetch_decltype_live
from gwtradearb.scrapers.decltype import parse_payload as parse_decltype_payload
from gwtradearb.scrapers.decltype import search as search_decltype
from gwtradearb.scrapers.gwtoolbox import fetch_live as fetch_gwtoolbox_live
from gwtradearb.scrapers.gwtoolbox import parse_payload as parse_gwtoolbox_payload
from gwtradearb.scrapers.gwtoolbox import search as search_gwtoolbox
from gwtradearb.scrapers.http import SourceFetchError, USER_AGENT

__all__ = [
    "USER_AGENT",
    "SourceFetchError",
    "fetch_decltype_live",
    "fetch_gwtoolbox_live",
    "parse_decltype_payload",
    "parse_gwtoolbox_payload",
    "search_decltype",
    "search_gwtoolbox",
]
