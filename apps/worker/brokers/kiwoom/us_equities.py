"""US-equities flow — NOT_SUPPORTED this round.

Kiwoom US REST support is unconfirmed against official docs (kiwoom-api-reference
§5). The handler checks US_SUPPORTED and logs the fetch_us_* steps as SKIPPED
rather than calling these. If called anyway, they raise NotSupportedError so we
fail loudly instead of fabricating data. To enable later: implement per reference
§5.2 (endpoint /api/us/acnt, api-id ust2107x/2111x/2112x/2116x, KRW conversion
via exch_rate/usd_exch_rate) and set US_SUPPORTED = True.
"""
from .exceptions import NotSupportedError

US_SUPPORTED = False
SKIP_REASON = "US REST support unconfirmed (see kiwoom-api-reference §5)"


def fetch_us_balance(client, account):
    raise NotSupportedError(SKIP_REASON)


def fetch_us_positions(client, account):
    raise NotSupportedError(SKIP_REASON)
