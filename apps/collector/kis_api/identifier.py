from __future__ import annotations

import os
import time
import warnings

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from kis_api.store import KisStore


OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"

# OpenFIGI exchCode -> our internal exchange code.
# Most codes here map to a KIS-supported overseas venue; Taiwan ("TT") maps
# to TWSE which is *not* priceable via KIS REST and is instead fetched from
# mis.twse.com.tw (see etf_inav/data_sources/twse_prices.py).
# Only *specific venue* codes are mapped. Composite/aggregate codes like
# "US" (US composite), "UV" (OTC), "CH" (China composite) are intentionally
# excluded: KIS needs the real listing venue, and a composite code would
# send e.g. an NYSE stock to NAS and get an empty response.
# China A-shares are further disambiguated by the 6-digit ticker (see below).
OPENFIGI_EXCH_TO_KIS = {
    # United States - NASDAQ tiers
    "UW": "NAS", "UQ": "NAS", "UR": "NAS", "UB": "NAS",
    # United States - NYSE group
    "UN": "NYS", "UP": "NYS",
    # United States - NYSE American (AMEX)
    "UA": "AMS",
    # Hong Kong
    "HK": "HKS",
    # China A-share (CS = Shanghai, C2/CG = Shenzhen)
    "CS": "SHS", "C1": "SHS",
    "C2": "SZS", "CG": "SZS",
    # Japan
    "JP": "TSE", "JT": "TSE",
    # Taiwan - OpenFIGI usually returns "TT" for both TWSE and TPEx; we
    # default to TWSE and let twse_prices probe both venues at fetch time.
    "TT": "TWSE",
}
OPENFIGI_CHINA_CODES = {"CS", "C1", "C2", "CG", "CH"}

KIS_SUPPORTED_EXCHANGES = ("NAS", "NYS", "AMS", "HKS", "SHS", "SZS", "TSE")
# Non-KIS venues we still resolve (priced via separate data sources).
NON_KIS_EXCHANGES = ("TWSE", "TPEX")
_EXCHANGE_RANK = {code: idx for idx, code in enumerate(KIS_SUPPORTED_EXCHANGES + NON_KIS_EXCHANGES)}

KIS_EXCHANGE_CURRENCY = {
    "NAS": "USD",
    "NYS": "USD",
    "AMS": "USD",
    "HKS": "HKD",
    "SHS": "CNY",
    "SZS": "CNY",
    "TSE": "JPY",
    "TWSE": "TWD",
    "TPEX": "TWD",
}

# ISIN country prefix -> expected exchanges (the security's home market).
ISIN_PREFIX_TO_KIS = {
    "US": ("NAS", "NYS", "AMS"),
    "CA": ("NAS", "NYS", "AMS"),
    # Mainland A-shares and Hong Kong H-shares both use CNE ISINs. Prefer
    # mainland venues when available, but allow HKS for H-share ISINs.
    "CN": ("SHS", "SZS", "HKS"),
    "HK": ("HKS",),
    "JP": ("TSE",),
    "TW": ("TWSE", "TPEX"),
}


def _normalize_isins(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().upper()] if value.strip() else []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _kis_exchange_for(exch_code, ticker) -> str | None:
    """Resolve an OpenFIGI exchCode + ticker to a KIS exchange code."""
    code = (exch_code or "").strip().upper()
    code = code.split()[0] if code else ""  # "TT (Taiwan Stock Exchange)" -> "TT"
    ticker_text = (ticker or "").strip()

    # China A-shares: the 6-digit ticker is the reliable signal.
    #   6xxxxx -> Shanghai, 0xxxxx / 3xxxxx -> Shenzhen.
    if code in OPENFIGI_CHINA_CODES and ticker_text.isdigit() and len(ticker_text) == 6:
        if ticker_text[0] == "6":
            return "SHS"
        if ticker_text[0] in ("0", "3"):
            return "SZS"

    return OPENFIGI_EXCH_TO_KIS.get(code)


def _openfigi_post(
    isins: list[str],
    api_key: str | None,
    timeout: int,
    verify: bool,
) -> list[dict]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    payload = [{"idType": "ID_ISIN", "idValue": value} for value in isins]
    if not verify:
        urllib3.disable_warnings(InsecureRequestWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.post(
                OPENFIGI_MAPPING_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
                verify=False,
            )
    else:
        response = requests.post(
            OPENFIGI_MAPPING_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=True,
        )
    response.raise_for_status()
    rows = response.json()
    return [
        {"isin": isin_value, "data": row.get("data", []), "error": row.get("error")}
        for isin_value, row in zip(isins, rows)
    ]


def _pick_best_candidate(isin: str, candidates: list[dict]) -> dict | None:
    """Pick the listing most likely to be priceable via KIS.

    When the ISIN country prefix maps to a known home market (US/CA/CN/HK/JP),
    only candidates on that home market are accepted - this prevents a Chinese
    A-share ISIN from resolving to a thinly-traded US OTC cross-listing. For
    shell-jurisdiction ISINs (KY, BM, ...) with no home-market signal, any
    KIS-supported exchange is accepted, ranked US > HK > China > Japan.
    """
    expected = ISIN_PREFIX_TO_KIS.get(isin[:2].upper(), ())

    eligible = []
    for row in candidates or []:
        ticker = row.get("ticker")
        if not ticker or row.get("marketSector") != "Equity":
            continue
        kis = _kis_exchange_for(row.get("exchCode"), ticker)
        if kis is None:
            continue
        if expected and kis not in expected:
            continue
        eligible.append((row, kis))

    if not eligible:
        return None
    if expected:
        expected_rank = {exchange: idx for idx, exchange in enumerate(expected)}
        eligible.sort(
            key=lambda pair: (
                expected_rank.get(pair[1], len(expected)),
                _EXCHANGE_RANK.get(pair[1], len(KIS_SUPPORTED_EXCHANGES)),
            )
        )
    else:
        eligible.sort(key=lambda pair: _EXCHANGE_RANK.get(pair[1], len(KIS_SUPPORTED_EXCHANGES)))
    return eligible[0][0]


def _resolve_mapping(isin: str, mapping: dict) -> dict:
    candidate = _pick_best_candidate(isin, mapping.get("data", []))
    if not candidate:
        return {
            "isin": isin,
            "ticker": None,
            "exchange": None,
            "figi": None,
            "name": None,
            "currency": None,
            "figiExchCode": None,
        }
    ticker = (candidate.get("ticker") or "").upper() or None
    exch_code = candidate.get("exchCode") or ""
    kis_exchange = _kis_exchange_for(exch_code, ticker)
    return {
        "isin": isin,
        "ticker": ticker,
        "exchange": kis_exchange,
        "figi": candidate.get("figi"),
        "name": candidate.get("name"),
        "currency": KIS_EXCHANGE_CURRENCY.get(kis_exchange) if kis_exchange else None,
        "figiExchCode": exch_code,
    }


def _currency_for_exchange(exchange: str | None) -> str | None:
    if not exchange:
        return None
    return KIS_EXCHANGE_CURRENCY.get(exchange.upper())


def fetch_ticker_by_isin(
    isin,
    store: KisStore | None = None,
    openfigi_api_key: str | None = None,
    timeout: int = 10,
    verify: bool = False,
    use_cache: bool = True,
    batch_size: int = 10,
    batch_delay_seconds: float = 2.0,
) -> list[dict]:
    """Map ISINs to (ticker, exchange, currency) via OpenFIGI, cached in KisStore.

    Returns list of dicts in input order. Each dict has:
    isin, ticker, exchange (KIS code), figi, name, currency, figiExchCode.
    """
    isins = _normalize_isins(isin)
    if not isins:
        return []
    store = store or KisStore()
    if openfigi_api_key is None:
        openfigi_api_key = os.environ.get("OPENFIGI_API_KEY") or None

    cached_rows = store.get_isin_mappings(isins) if use_cache else {}
    cached = {
        isin: row
        for isin, row in cached_rows.items()
        if row.get("ticker") and row.get("exchange")
    }
    missing = [value for value in isins if value not in cached]

    resolved_new: list[dict] = []
    for start in range(0, len(missing), batch_size):
        chunk = missing[start : start + batch_size]
        mappings = _openfigi_post(chunk, openfigi_api_key, timeout=timeout, verify=verify)
        resolved_new.extend(_resolve_mapping(row["isin"], row) for row in mappings)
        if batch_delay_seconds > 0 and start + batch_size < len(missing):
            time.sleep(batch_delay_seconds)

    if resolved_new and use_cache:
        store.upsert_isin_mappings(resolved_new)

    resolved_by_isin = {row["isin"]: row for row in resolved_new}
    output: list[dict] = []
    for value in isins:
        if value in cached:
            row = cached[value]
            exchange = row.get("exchange")
            output.append(
                {
                    "isin": value,
                    "ticker": row.get("ticker"),
                    "exchange": exchange,
                    "figi": row.get("figi"),
                    "name": row.get("name"),
                    "currency": _currency_for_exchange(exchange),
                    "figiExchCode": None,
                }
            )
        else:
            output.append(
                resolved_by_isin.get(
                    value,
                    {
                        "isin": value,
                        "ticker": None,
                        "exchange": None,
                        "figi": None,
                        "name": None,
                        "currency": None,
                        "figiExchCode": None,
                    },
                )
            )
    return output
