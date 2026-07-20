"""Taiwan stock prices from TWSE MIS server.

KIS does not offer Taiwan market data, so we use the TWSE MIS endpoint that
powers the public quote widget on twse.com.tw.

Endpoint: https://mis.twse.com.tw/stock/api/getStockInfo.jsp
- ex_ch channel format: ``{prefix}_{symbol}.tw``
  - ``tse_`` for TWSE main board (Taiwan Stock Exchange)
  - ``otc_`` for TPEx (Taipei Exchange, formerly GreTai)
- Returns latest tick during regular session, last close otherwise.
- When mis blanks ``z``/``pz`` between matches mid-session, falls back to the
  best bid/ask midpoint so livePrice keeps a live value.

Regular session (Taiwan time = UTC+8, no DST):
  09:00-13:30 TST  =  10:00-14:30 KST  Mon-Fri.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning


KST = timezone(timedelta(hours=9))
TST = timezone(timedelta(hours=8))

TWSE_OPEN_KST = dt_time(10, 0)
TWSE_CLOSE_KST = dt_time(14, 30)
TWSE_POST_CLOSE_KST = dt_time(14, 45)

TWSE_ENDPOINT = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

TWSE_EXCHANGE = "TWSE"
TPEX_EXCHANGE = "TPEX"
SUPPORTED_EXCHANGES = {TWSE_EXCHANGE, TPEX_EXCHANGE}

EX_TO_EXCHANGE = {"tse": TWSE_EXCHANGE, "otc": TPEX_EXCHANGE}
EXCHANGE_TO_PREFIX = {TWSE_EXCHANGE: "tse", TPEX_EXCHANGE: "otc"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://mis.twse.com.tw/stock/fibest.jsp",
}


def is_twse_trading_hours(now: datetime | None = None) -> bool:
    """Regular Taiwan session in KST: Mon-Fri 10:00-14:30.

    Taiwan holidays are not handled here; on holidays mis.twse.com.tw simply
    returns the previous session's data with no live ticks, which the cache
    behavior already absorbs.
    """
    current = (now or datetime.now(KST)).astimezone(KST)
    if current.weekday() >= 5:
        return False
    return TWSE_OPEN_KST <= current.time() < TWSE_CLOSE_KST


def is_twse_post_close_window(now: datetime | None = None) -> bool:
    """Brief grace window right after the regular session closes
    (14:30-14:45 KST, Mon-Fri).

    TWSE/TPEx run a closing call auction from 13:25-13:30 TST (= 14:25-14:30
    KST). The confirmed close lands on mis.twse.com.tw a few seconds after
    13:30 TST. A plain N-minute polling cadence inside trading hours can
    otherwise strand the last pre-auction tick (e.g. 14:27 KST) as the
    recorded close. Fetching once or twice in this window captures the
    real closing-auction price.
    """
    current = (now or datetime.now(KST)).astimezone(KST)
    if current.weekday() >= 5:
        return False
    return TWSE_CLOSE_KST <= current.time() < TWSE_POST_CLOSE_KST


def _to_float(value) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _best_quote_level(value) -> float | None:
    """mis.twse.com.tw returns 5 bid/ask levels joined by '_'. Pick the top."""
    if value in (None, "", "-"):
        return None
    head = str(value).split("_", 1)[0]
    return _to_float(head)


def _trade_time_kst(row: dict) -> str | None:
    """Convert mis 't' (Taipei wall-clock HH:MM:SS) to KST 'HH:MM:SS'.

    mis.twse.com.tw also returns ``tlong`` (ms epoch) but in practice its
    timezone offset is inconsistent — Taipei wall-clock plus 1 hour is the
    reliable derivation since TST and KST never observe DST.
    """
    local_t = row.get("t")
    if not local_t:
        return None
    try:
        local = datetime.strptime(local_t, "%H:%M:%S")
        return (local + timedelta(hours=1)).strftime("%H:%M:%S")
    except ValueError:
        return local_t


def _normalize_row(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("c") or "").strip().upper()
    ex_key = str(row.get("ex") or "").strip().lower()
    exchange = EX_TO_EXCHANGE.get(ex_key)
    if not symbol or exchange is None:
        return None
    last = _to_float(row.get("z"))
    if last is None:
        last = _to_float(row.get("pz"))
    if last is None:
        # mis blanks z/pz between matches even for actively-trading symbols.
        # Bid/ask stays current, so use the top-of-book midpoint as the live
        # price; otherwise the dashboard shows null mid-session.
        bid = _best_quote_level(row.get("b"))
        ask = _best_quote_level(row.get("a"))
        if bid is not None and ask is not None:
            last = (bid + ask) / 2
        elif bid is not None:
            last = bid
        elif ask is not None:
            last = ask
    return {
        "exchange": exchange,
        "symbol": symbol,
        "last": last,
        "base": _to_float(row.get("y")),
        "open": _to_float(row.get("o")),
        "high": _to_float(row.get("h")),
        "low": _to_float(row.get("l")),
        "volume": _to_float(row.get("v")),
        "value": None,
        "currency": "TWD",
        "rsym": f"{ex_key}_{symbol.lower()}.tw",
        "trade_time": row.get("t"),
        "korea_time": _trade_time_kst(row),
        "raw": row,
    }


def _build_channel(exchange: str, symbol: str) -> str:
    prefix = EXCHANGE_TO_PREFIX.get(exchange.upper())
    if prefix is None:
        raise ValueError(f"Unsupported Taiwan exchange: {exchange}")
    return f"{prefix}_{symbol.strip().lower()}.tw"


def _build_channels(targets: list[tuple[str, str]], try_both: bool) -> list[str]:
    """Build ex_ch channel list. When ``try_both`` is true, query both venues
    for each symbol since OpenFIGI does not always distinguish TWSE from TPEx
    reliably for Taiwanese listings."""
    seen: set[str] = set()
    channels: list[str] = []
    for exchange, symbol in targets:
        sym_clean = symbol.strip().lower()
        if not sym_clean:
            continue
        if try_both:
            candidates = (f"tse_{sym_clean}.tw", f"otc_{sym_clean}.tw")
        else:
            candidates = (_build_channel(exchange, symbol),)
        for ch in candidates:
            if ch not in seen:
                seen.add(ch)
                channels.append(ch)
    return channels


def _get(
    params: dict,
    timeout: int,
    verify_ssl: bool,
) -> dict:
    if not verify_ssl:
        urllib3.disable_warnings(InsecureRequestWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(
                TWSE_ENDPOINT,
                headers=HEADERS,
                params=params,
                timeout=timeout,
                verify=False,
            )
    else:
        response = requests.get(
            TWSE_ENDPOINT,
            headers=HEADERS,
            params=params,
            timeout=timeout,
            verify=True,
        )
    response.raise_for_status()
    return response.json()


def fetch_twse_prices(
    targets: list[tuple[str, str]],
    timeout: int = 10,
    verify_ssl: bool = False,
    try_both_venues: bool = True,
    chunk_size: int = 50,
) -> list[dict]:
    """Fetch snapshots for Taiwan tickers from mis.twse.com.tw.

    ``targets`` is a list of (exchange, symbol) pairs where exchange is
    ``"TWSE"`` or ``"TPEX"``. When ``try_both_venues`` is true (default),
    each symbol is queried on both ``tse_`` and ``otc_`` channels and the
    venue that returns data wins; this absorbs OpenFIGI ambiguity.

    Returns snapshots in the same shape used by KIS rest snapshots:
    keys ``exchange, symbol, last, base, open, high, low, volume, value,
    currency, rsym, trade_time, korea_time, raw``. The ``exchange`` in each
    returned snapshot reflects the venue that actually had data.
    """
    if not targets:
        return []

    snapshots: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    channels = _build_channels(targets, try_both_venues)
    for start in range(0, len(channels), chunk_size):
        chunk = channels[start : start + chunk_size]
        params = {"ex_ch": "|".join(chunk), "json": "1", "delay": "0"}
        try:
            payload = _get(params, timeout=timeout, verify_ssl=verify_ssl)
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            continue
        for row in payload.get("msgArray") or []:
            snap = _normalize_row(row)
            if snap is None:
                continue
            key = (snap["exchange"], snap["symbol"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            snapshots.append(snap)
    return snapshots


def fetch_twse_table(
    targets: list[tuple[str, str]],
    timeout: int = 10,
    verify_ssl: bool = False,
    now: datetime | None = None,
) -> dict:
    """Convenience wrapper that returns snapshots + metadata, mirroring
    naver_fx.fetch_fx_table style."""
    snapshots = fetch_twse_prices(targets, timeout=timeout, verify_ssl=verify_ssl)
    return {
        "snapshots": snapshots,
        "trading_hours": is_twse_trading_hours(now),
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
    }


def is_taiwan_exchange(value: str) -> bool:
    return (value or "").strip().upper() in SUPPORTED_EXCHANGES


def write_snapshot_cache(path: Path, snapshots: list[dict]) -> None:
    """Persist snapshots to disk so a restart outside trading hours can still
    serve the last close without depending on mis.twse.com.tw."""
    if not snapshots:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "snapshots": [{k: v for k, v in snap.items() if k != "raw"} for snap in snapshots],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_snapshot_cache(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("snapshots") or []
    return [row for row in rows if isinstance(row, dict)]
