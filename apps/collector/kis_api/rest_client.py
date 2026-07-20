from __future__ import annotations

import time
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from kis_api.auth import KisAuth


_KST = timezone(timedelta(hours=9))


KIS_EXCHANGE_TO_REST_EXCD = {
    "KRX": "KRX",
    "NAS": "NAS",
    "NYS": "NYS",
    "AMS": "AMS",
    "BAQ": "BAQ",
    "BAY": "BAY",
    "BAA": "BAA",
    "HKS": "HKS",
    "SHS": "SHS",
    "SZS": "SZS",
    "TSE": "TSE",
    "HNX": "HNX",
    "HSX": "HSX",
}

PRICE_DETAIL_TR_ID = "HHDFS76200200"
PRICE_DETAIL_PATH = "/uapi/overseas-price/v1/quotations/price-detail"
MULT_PRICE_TR_ID = "HHDFS76220000"
MULT_PRICE_PATH = "/uapi/overseas-price/v1/quotations/multprice"
PRICE_TR_ID = "HHDFS00000300"
PRICE_PATH = "/uapi/overseas-price/v1/quotations/price"
DAILY_PRICE_TR_ID = "HHDFS76240000"
DAILY_PRICE_PATH = "/uapi/overseas-price/v1/quotations/dailyprice"
DOMESTIC_PRICE_TR_ID = "FHKST01010100"
DOMESTIC_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
FUTUREOPTION_PRICE_TR_ID = "FHMIF10000000"
FUTUREOPTION_PRICE_PATH = "/uapi/domestic-futureoption/v1/quotations/inquire-price"


def _to_float(value):
    if value in (None, "", "0"):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _normalize_symbol(exchange: str, symbol: str) -> str:
    symbol_text = symbol.upper()
    if exchange.upper() == "HKS" and symbol_text.isdigit():
        return symbol_text.zfill(5)
    return symbol_text


def _is_overseas_exchange(exchange: str) -> bool:
    return exchange.upper() not in {"KRX", "KFO"}


def _chunked(values: list, size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


class KisRestClient:
    def __init__(
        self,
        auth: KisAuth,
        timeout: int = 10,
        suppress_insecure_warning: bool = True,
    ):
        self.auth = auth
        self.timeout = timeout
        self.suppress_insecure_warning = suppress_insecure_warning
        if not auth.verify_ssl and suppress_insecure_warning:
            urllib3.disable_warnings(InsecureRequestWarning)

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        url = f"{self.auth.credentials.rest_base}{path}"
        headers = self.auth.rest_headers(tr_id)
        if not self.auth.verify_ssl and self.suppress_insecure_warning:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout,
                    verify=False,
                )
        else:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=self.timeout,
                verify=self.auth.verify_ssl,
            )
        response.raise_for_status()
        return response.json()

    def overseas_price_detail(self, exchange: str, symbol: str) -> dict:
        """Detailed snapshot for one overseas stock (TR_ID HHDFS76200200).

        Response output keys include: last(현재가), base(전일종가),
        rsym(realtime symbol), open, high, low, tvol(거래량),
        pbid/pask(매수/매도호가), tamt(거래대금) and crency-related fields.
        """
        exchange = exchange.upper()
        symbol = _normalize_symbol(exchange, symbol)
        excd = KIS_EXCHANGE_TO_REST_EXCD.get(exchange, exchange)
        params = {
            "AUTH": "",
            "EXCD": excd,
            "SYMB": symbol,
        }
        data = self._get(PRICE_DETAIL_PATH, PRICE_DETAIL_TR_ID, params)
        return data.get("output") or {}

    def overseas_price(self, exchange: str, symbol: str) -> dict:
        """Light snapshot (TR_ID HHDFS00000300). Only last/base/sign."""
        exchange = exchange.upper()
        symbol = _normalize_symbol(exchange, symbol)
        excd = KIS_EXCHANGE_TO_REST_EXCD.get(exchange, exchange)
        params = {
            "AUTH": "",
            "EXCD": excd,
            "SYMB": symbol,
        }
        data = self._get(PRICE_PATH, PRICE_TR_ID, params)
        return data.get("output") or {}

    def overseas_daily_bars(
        self, exchange: str, symbol: str, count: int = 2, adjusted: bool = False
    ) -> list[dict]:
        """Recent daily bars for one overseas stock (TR_ID HHDFS76240000).

        Returns up to ``count`` bars, most recent first, normalized to
        {"date": "YYYYMMDD"(exchange-local), "close": float, "raw": row}.
        The latest completed session's ``close`` is the official closing
        price — unlike ``last`` on the snapshot TRs it never drifts with
        after-hours trades. GUBN=0(일), BYMD=""(최신부터),
        MODP=0(원주가; 당일 종가×당일 PDF 수량 계산이므로 수정주가 불필요).
        """
        exchange = exchange.upper()
        symbol = _normalize_symbol(exchange, symbol)
        excd = KIS_EXCHANGE_TO_REST_EXCD.get(exchange, exchange)
        params = {
            "AUTH": "",
            "EXCD": excd,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": "",
            "MODP": "1" if adjusted else "0",
        }
        data = self._get(DAILY_PRICE_PATH, DAILY_PRICE_TR_ID, params)
        if str(data.get("rt_cd", "")) not in ("", "0"):
            message = data.get("msg1") or data.get("msg_cd") or "KIS dailyprice failed"
            raise RuntimeError(str(message))
        out: list[dict] = []
        for row in data.get("output2") or []:
            date = str(row.get("xymd") or "").strip()
            close = _to_float(row.get("clos"))
            if not date or close is None:
                continue
            out.append({"date": date, "close": close, "raw": row})
            if len(out) >= max(1, count):
                break
        return out

    def _overseas_snapshot_from_row(self, row: dict, exchange: str, symbol: str) -> dict:
        exchange = exchange.upper()
        symbol = _normalize_symbol(exchange, symbol)
        return {
            "exchange": exchange,
            "symbol": symbol.upper(),
            "last": _to_float(row.get("last")),
            "base": _to_float(row.get("base")),
            "open": _to_float(row.get("open")),
            "high": _to_float(row.get("high")),
            "low": _to_float(row.get("low")),
            "volume": _to_float(row.get("tvol")),
            "value": _to_float(row.get("tamt")),
            "currency": (row.get("curr") or row.get("crncy") or "").upper() or None,
            "rsym": row.get("rsym"),
            "trade_time": row.get("xhms") or row.get("dymd") or row.get("ymd") or "",
            "korea_time": row.get("khms"),
            "raw": row,
        }

    def overseas_multprice(self, targets: list[tuple[str, str]]) -> list[dict]:
        """Return normalized snapshots for up to 10 overseas symbols.

        KIS HHDFS76220000 accepts EXCD_01..10/SYMB_01..10 and returns
        output2 rows. The caller is responsible for chunking larger lists.
        """
        if not targets:
            return []
        if len(targets) > 10:
            raise ValueError("overseas_multprice supports at most 10 targets per request")

        params = {"AUTH": "", "NREC": str(len(targets))}
        request_targets = []
        for idx, (exchange, symbol) in enumerate(targets, start=1):
            exchange = exchange.upper()
            symbol = _normalize_symbol(exchange, symbol)
            request_targets.append((exchange, symbol))
            params[f"EXCD_{idx:02d}"] = KIS_EXCHANGE_TO_REST_EXCD.get(exchange, exchange)
            params[f"SYMB_{idx:02d}"] = symbol

        data = self._get(MULT_PRICE_PATH, MULT_PRICE_TR_ID, params)
        if str(data.get("rt_cd", "")) not in ("", "0"):
            message = data.get("msg1") or data.get("msg_cd") or "KIS multprice failed"
            raise RuntimeError(str(message))

        rows = data.get("output2") or []
        if len(rows) == len(request_targets):
            return [
                self._overseas_snapshot_from_row(row, exchange, symbol)
                for row, (exchange, symbol) in zip(rows, request_targets)
            ]

        rows_by_key: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            key = (
                str(row.get("excd") or "").upper(),
                _normalize_symbol(str(row.get("excd") or ""), str(row.get("symb") or "")),
            )
            rows_by_key.setdefault(key, []).append(row)

        out: list[dict] = []
        for exchange, symbol in request_targets:
            key = (KIS_EXCHANGE_TO_REST_EXCD.get(exchange, exchange), symbol)
            row_list = rows_by_key.get(key) or []
            row = row_list.pop(0) if row_list else {}
            out.append(self._overseas_snapshot_from_row(row, exchange, symbol))
        return out

    def domestic_price(self, symbol: str, market_div_code: str = "J") -> dict:
        """Current snapshot for one Korea-listed stock or ETF."""
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": symbol.upper(),
        }
        data = self._get(DOMESTIC_PRICE_PATH, DOMESTIC_PRICE_TR_ID, params)
        return data.get("output") or {}

    def domestic_snapshot(self, symbol: str) -> dict:
        # MRKT_DIV_CODE="UN" merges KRX + NXT so NXT pre/after-hours trades
        # (08:00–08:50, 15:30–20:00) are reflected; "J" alone returns the
        # prior-day close until 09:00.
        raw = self.domestic_price(symbol, market_div_code="UN")
        last = _to_float(raw.get("stck_prpr"))
        base = _to_float(raw.get("stck_prdy_clpr") or raw.get("stck_sdpr"))
        # FHKST01010100 ("주식현재가 시세") returns no trade-time field, and
        # KRX is not subscribed via WebSocket either. Stamp the local fetch
        # time as a proxy: during trading hours this is within the snapshot
        # interval of the actual tick; after hours it is when we last pulled.
        trade_time = datetime.now(_KST).strftime("%H%M%S")
        return {
            "exchange": "KRX",
            "symbol": symbol.upper(),
            "last": last,
            "base": base,
            "open": _to_float(raw.get("stck_oprc")),
            "high": _to_float(raw.get("stck_hgpr")),
            "low": _to_float(raw.get("stck_lwpr")),
            "volume": _to_float(raw.get("acml_vol")),
            "value": _to_float(raw.get("acml_tr_pbmn")),
            "currency": "KRW",
            "rsym": raw.get("stck_shrn_iscd") or symbol.upper(),
            "trade_time": trade_time,
            "raw": raw,
        }

    def futureoption_price(self, symbol: str, market_div_code: str = "JF") -> dict:
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": symbol.upper(),
        }
        data = self._get(FUTUREOPTION_PRICE_PATH, FUTUREOPTION_PRICE_TR_ID, params)
        return data.get("output1") or {}

    def futureoption_snapshot(self, symbol: str, market_div_code: str = "JF") -> dict:
        raw = self.futureoption_price(symbol, market_div_code=market_div_code)
        last = _to_float(raw.get("futs_prpr"))
        base = _to_float(raw.get("futs_prdy_clpr") or raw.get("futs_sdpr"))
        return {
            "exchange": "KFO",
            "symbol": symbol.upper(),
            "last": last,
            "base": base,
            "open": _to_float(raw.get("futs_oprc")),
            "high": _to_float(raw.get("futs_hgpr")),
            "low": _to_float(raw.get("futs_lwpr")),
            "volume": _to_float(raw.get("acml_vol")),
            "value": _to_float(raw.get("acml_tr_pbmn")),
            "currency": "KRW",
            "rsym": symbol.upper(),
            "trade_time": raw.get("futs_last_tr_date") or "",
            "raw": raw,
        }

    def snapshot(self, exchange: str, symbol: str) -> dict:
        """Return normalized snapshot for a domestic or overseas symbol.

        Uses HHDFS76200200 (price-detail) since it carries the fields we need
        (last, open/high/low, volume, base, currency). The KRW-converted
        price is not included natively here - callers should multiply by an
        externally supplied USD/KRW rate when needed.
        """
        if exchange.upper() == "KRX":
            return self.domestic_snapshot(symbol)
        if exchange.upper() == "KFO":
            return self.futureoption_snapshot(symbol)

        symbol = _normalize_symbol(exchange, symbol)
        raw = self.overseas_price_detail(exchange, symbol)
        return self._overseas_snapshot_from_row(raw, exchange, symbol)

    def snapshots(
        self,
        targets: list[tuple[str, str]],
        batch_delay_seconds: float = 0.05,
        max_workers: int = 1,
        overseas_batch_size: int = 1,
    ) -> list[dict]:
        def error_snapshot(exchange: str, symbol: str, exc: Exception) -> dict:
            return {
                "exchange": exchange.upper(),
                "symbol": symbol.upper(),
                "last": None,
                "error": str(exc),
            }

        def build_operations():
            operations = []
            pending_overseas = []

            def flush_overseas() -> None:
                nonlocal pending_overseas
                if not pending_overseas:
                    return
                for chunk in _chunked(pending_overseas, max(1, min(overseas_batch_size, 10))):
                    operations.append(("overseas_multi", chunk))
                pending_overseas = []

            for idx, (exchange, symbol) in enumerate(targets):
                exchange = exchange.upper()
                symbol = _normalize_symbol(exchange, symbol)
                item = (idx, exchange, symbol)
                if overseas_batch_size > 1 and _is_overseas_exchange(exchange):
                    pending_overseas.append(item)
                    continue
                flush_overseas()
                operations.append(("single", [item]))

            flush_overseas()
            return operations

        operations = build_operations()

        def fetch_operation(operation):
            kind, items = operation
            if kind == "overseas_multi":
                request_targets = [(exchange, symbol) for _, exchange, symbol in items]
                try:
                    rows = self.overseas_multprice(request_targets)
                    return [(idx, row) for (idx, _, _), row in zip(items, rows)]
                except Exception as exc:
                    return [
                        (idx, error_snapshot(exchange, symbol, exc))
                        for idx, exchange, symbol in items
                    ]

            idx, exchange, symbol = items[0]
            try:
                return [(idx, self.snapshot(exchange, symbol))]
            except Exception as exc:
                return [(idx, error_snapshot(exchange, symbol, exc))]

        if max_workers <= 1 or len(operations) <= 1:
            ordered: list[dict | None] = [None] * len(targets)
            for op_idx, operation in enumerate(operations):
                for idx, item in fetch_operation(operation):
                    ordered[idx] = item
                if batch_delay_seconds > 0 and op_idx + 1 < len(operations):
                    time.sleep(batch_delay_seconds)
            return [item for item in ordered if item is not None]

        interval = max(0.0, batch_delay_seconds)
        lock = threading.Lock()
        next_start = time.perf_counter()

        def wait_for_slot() -> None:
            nonlocal next_start
            if interval <= 0:
                return
            with lock:
                now = time.perf_counter()
                wait_seconds = max(0.0, next_start - now)
                next_start = max(now, next_start) + interval
            if wait_seconds > 0:
                time.sleep(wait_seconds)

        def fetch_one(operation) -> list[tuple[int, dict]]:
            wait_for_slot()
            return fetch_operation(operation)

        worker_count = min(max_workers, len(operations))
        ordered: list[dict | None] = [None] * len(targets)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(fetch_one, operation): operation
                for operation in operations
            }
            for future in as_completed(futures):
                for idx, item in future.result():
                    ordered[idx] = item

        return [item for item in ordered if item is not None]
