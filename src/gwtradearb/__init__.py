"""GWTradeArb: fetch, parse, match, and persist public Kamadan trade chat.

This package never automates Guild Wars, sends whispers, or stores credentials.
"""

__version__ = "0.4.0"

from gwtradearb.matching import match_listings
from gwtradearb.models import Listing, Opportunity, RawMessage

__all__ = ["Listing", "Opportunity", "RawMessage", "match_listings", "__version__"]
