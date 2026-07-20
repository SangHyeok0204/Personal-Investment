"""Intraday FX rates from Naver Finance.

Endpoint: https://api.stock.naver.com/marketindex/exchange/FX_{XXX}KRW
- Public, no auth required.
- closePrice updates intraday during 하나은행 영업시간 (typically 09:00-15:30 KST).
- Returns last fixing when market closed.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone, timedelta

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning


KST = timezone(timedelta(hours=9))
NAVER_FX_URL = "https://api.stock.naver.com/marketindex/exchange/FX_{symbol}KRW"

DEFAULT_SYMBOLS = ("USD", "CNY", "HKD", "JPY", "EUR", "CAD", "TWD")

# Naver quotes these per 100 units (e.g. FX_JPYKRW closePrice is KRW per 100 JPY).
# We normalize everything to a per-1-unit rate.
PER_100_SYMBOLS = {"JPY", "IDR"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://m.stock.naver.com/",
}


def _to_float(value) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_fx_rate(
    symbol: str,
    timeout: int = 10,
    verify_ssl: bool = False,
) -> dict:
    """Return current Naver FX rate for {symbol}/KRW."""
    url = NAVER_FX_URL.format(symbol=symbol.upper())
    if not verify_ssl:
        urllib3.disable_warnings(InsecureRequestWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    else:
        response = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
    response.raise_for_status()
    data = response.json()
    info = data.get("exchangeInfo") or {}
    rate = _to_float(info.get("closePrice"))
    if rate is not None and symbol.upper() in PER_100_SYMBOLS:
        rate = rate / 100.0
    return {
        "symbol": symbol.upper(),
        "rate": rate,
        "fluctuations": _to_float(info.get("fluctuations")),
        "fluctuations_pct": _to_float(info.get("fluctuationsRatio")),
        "direction": (info.get("fluctuationsType") or {}).get("name"),
        "traded_at": info.get("localTradedAt"),
        "market_status": info.get("marketStatus"),
    }


def fetch_fx_table(
    symbols=DEFAULT_SYMBOLS,
    timeout: int = 10,
    verify_ssl: bool = False,
) -> dict:
    """Fetch a {currency_code: rate_krw} mapping for given symbols.

    Always includes KRW=1.0. Symbols that fail (network, parse) are omitted.
    Detail per symbol is preserved under 'detail'.
    """
    rates: dict[str, float] = {"KRW": 1.0}
    detail: dict[str, dict] = {}
    errors: list[str] = []
    for symbol in symbols:
        try:
            row = fetch_fx_rate(symbol, timeout=timeout, verify_ssl=verify_ssl)
            if row["rate"]:
                rates[symbol.upper()] = row["rate"]
                detail[symbol.upper()] = row
        except Exception as exc:  # pragma: no cover - network errors
            errors.append(f"{symbol}:{exc}")
    return {
        "rates": rates,
        "detail": detail,
        "errors": errors,
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    }
