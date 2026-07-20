"""ETF iNAV collector — Phase-2 asyncio orchestrator.

Mirrors the legacy ``streaming.py``:
  setup (KRX inputs → resolve_instruments → FX + KIS REST seed + TWSE seed →
  InavEngine) then async refresh loops (FX 60s, KIS REST 15s, TWSE 300s,
  compute 1s, KST midnight rollover), the KIS realtime WebSocket lane (live
  ticks + 40-subscription rotation), plus an in-process FastAPI served by
  uvicorn on 0.0.0.0:8100 (GET /snapshot, GET /health).

Self-sufficiency (the legacy system is terminated; the shared app key is now
exclusive to this collector). Behavior is flag-gated so the legacy system can
be restarted for comparison sessions (see docker-compose):
  * COLLECTOR_ALLOW_TOKEN_ISSUE=1 → issue the KIS token when the legacy
    piggyback token is absent/expired (caches to /app/.cache). =0 → strict
    piggyback-only (skip REST if absent).
  * COLLECTOR_ALLOW_FETCH=1 → self-fetch KRX inputs when today's legacy cache
    is missing. =0 → legacy cache only.
  * Masters/OpenFIGI DB download/create into the writable /app/.cache on a
    cache miss.
  * NEVER write to the :ro legacy mounts — only /app/.cache is writable.
Everything is fail-stale: any source error keeps the last-good value and lets
its age grow; a bad cycle never crashes the process.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time

import pandas as pd
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from etf_inav.core.engine import INAV_DIVISOR, InavEngine
from etf_inav.data_sources.kis_prices import resolve_instruments
from etf_inav.data_sources.naver_fx import fetch_fx_table
from etf_inav.data_sources.twse_prices import (
    SUPPORTED_EXCHANGES as TAIWAN_EXCHANGES,
    fetch_twse_prices,
    is_twse_post_close_window,
    is_twse_trading_hours,
)
from kis_api.auth import KisAuth, KisCredentials
from kis_api.futureoption_master import DomesticFutureOptionMaster
from kis_api.master import KisMaster
from kis_api.rest_client import KisRestClient
from kis_api.store import KisStore
from kis_api.websocket_client import (
    EXCHANGE_TO_TRKEY,
    MAX_SUBSCRIPTIONS,
    KisWebSocket,
    parse_tr_key,
)

from collector import legacy_inputs
from collector.krx_prep import (
    build_component_stock_rows,
    config_tickers,
    filter_inputs_by_ticker,
    first_existing_column,
    parse_prefixes,
    prepare_pdf_df,
    to_number,
)
from collector.legacy_inputs import CACHE_DIR, DB_DEST, MASTER_CACHE_DIR
from collector.state import SnapshotState, json_safe, now_kst_string
from collector.wrap import WrapCollector

FX_SYMBOLS = ("USD", "CNY", "HKD", "JPY", "EUR", "CAD", "TWD")

# KIS REST rate: key-exclusive now (legacy terminated). Legacy real-account
# defaults are 20 req/s; stay moderate.
PRICE_DELAY_SECONDS = 0.2      # ~5 requests/s globally
PRICE_WORKERS = 4
OVERSEAS_BATCH_SIZE = 10      # multprice batching cuts request count

FX_REFRESH_S = 60.0
PRICE_REFRESH_S = 15.0        # match legacy --price-refresh-seconds 15
ETF_QUOTE_REFRESH_S = 15.0    # KR ETF 자체 시세(현재가/등락률) — 카드 표시용
WRAP_REFRESH_S = 15.0         # WRAP 포트폴리오 실시간 수익률 (legacy cycle 과 동일)
TWSE_REFRESH_S = 300.0
COMPUTE_INTERVAL_S = 1.0
ROLLOVER_CHECK_S = 60.0

# KIS realtime WebSocket lane.
WS_ROTATION_S = 30.0          # legacy --rotation-seconds default (when >40 targets)
WS_RECONNECT_S = 5.0          # wait before re-establishing a dropped WS session

# Token self-issuance (see docker-compose COLLECTOR_ALLOW_TOKEN_ISSUE): when the
# legacy piggyback token is absent/expired and this is set, let KisAuth issue
# naturally (caches to /app/.cache). =0 restores strict piggyback-only behavior.
ALLOW_TOKEN_ISSUE = (
    os.environ.get("COLLECTOR_ALLOW_TOKEN_ISSUE", "1").strip().lower()
    not in ("0", "false", "no", "")
)

API_HOST = "0.0.0.0"
API_PORT = 8100


def _log(msg: str) -> None:
    print(f"[collector] {msg}", file=sys.stderr, flush=True)


def _pos(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _int_or_none(value):
    safe = json_safe(value)
    if safe is None:
        return None
    try:
        return int(safe)
    except (TypeError, ValueError):
        return None


# KIS HDFSCNT0 (해외주식 실시간지연체결가) live frame layout — 26 caret-delimited
# fields per tick, RSYM first:
#   0 RSYM 1 SYMB 2 ZDIV 3 TYMD 4 XYMD 5 XHMS 6 KYMD 7 KHMS 8 OPEN 9 HIGH
#   10 LOW 11 LAST 12 SIGN 13 DIFF 14 RATE 15 PBID 16 PASK 17 VBID 18 VASK
#   19 EVOL 20 TVOL 21 TAMT 22 BIVL 23 ASVL 24 STRN 25 MTYP
# The verbatim websocket_client.events() column map omits the leading RSYM,
# shifting every field by one (its SYMB←RSYM, LAST←LOW) so its bare-symbol
# subscription lookup never matches and it yields nothing. That module must
# stay byte-verbatim, so the collector parses raw frames itself.
_HDFSCNT0_FIELD_COUNT = 26
_HDFSCNT0_RSYM_IDX = 0
_HDFSCNT0_XHMS_IDX = 5
_HDFSCNT0_LAST_IDX = 11


def _parse_hdfscnt0_ticks(raw: str) -> list[tuple[str, str, float, str]]:
    """Parse a ``0|HDFSCNT0|N|payload`` frame into ``(exchange, symbol, last,
    xhms)`` tuples. Only positive last prices survive (transient zeros dropped).
    Exchange/symbol are recovered from RSYM via ``parse_tr_key`` (e.g.
    ``DHKS00700`` → ``("HKS", "00700")``), matching the engine's instrument keys.
    """
    parts = raw.split("|", 3)
    if len(parts) < 4 or parts[1] != "HDFSCNT0":
        return []
    try:
        count = int(parts[2])
    except (TypeError, ValueError):
        count = 1
    fields = parts[3].split("^")
    out: list[tuple[str, str, float, str]] = []
    for tick in range(count):
        chunk = fields[tick * _HDFSCNT0_FIELD_COUNT : (tick + 1) * _HDFSCNT0_FIELD_COUNT]
        if len(chunk) < _HDFSCNT0_FIELD_COUNT:
            break
        try:
            exchange, symbol = parse_tr_key(chunk[_HDFSCNT0_RSYM_IDX])
        except ValueError:
            continue
        try:
            last = float(chunk[_HDFSCNT0_LAST_IDX])
        except (TypeError, ValueError):
            continue
        if last <= 0:
            continue
        out.append((exchange, symbol, last, chunk[_HDFSCNT0_XHMS_IDX]))
    return out


def _etf_list_meta(etf_list_df) -> dict[str, dict]:
    """KRX ETF 목록 프레임 → {ticker: {name, list_shrs, fee_pct}}.

    name 은 PDF 의 ETF_NAME 공란 보완용, list_shrs(상장좌수)·fee_pct(총보수 %)는
    AUM(상장좌수×iNAV)·연보수 계산용.
    """
    if etf_list_df is None or getattr(etf_list_df, "empty", True):
        return {}
    ticker_col = first_existing_column(etf_list_df, ["ETF_TICKER", "ISU_SRT_CD", "ticker"])
    if not ticker_col:
        return {}
    name_col = first_existing_column(etf_list_df, ["ETF_NAME", "ISU_ABBRV", "ISU_NM"])
    shrs_col = first_existing_column(etf_list_df, ["LIST_SHRS"])
    fee_col = first_existing_column(etf_list_df, ["ETF_TOT_FEE"])
    out: dict[str, dict] = {}
    for _, row in etf_list_df.iterrows():
        ticker = str(row[ticker_col]).strip().upper()
        if not ticker or ticker in ("NAN", "<NA>", "NONE"):
            continue
        name = str(row[name_col]).strip() if name_col else ""
        if name.upper() in ("NAN", "<NA>", "NONE"):
            name = ""
        out[ticker] = {
            "name": name,
            "list_shrs": json_safe(to_number(row[shrs_col])) if shrs_col else None,
            "fee_pct": json_safe(to_number(row[fee_col])) if fee_col else None,
        }
    return out


class Collector:
    def __init__(self) -> None:
        self.config = legacy_inputs.load_config()
        self.target_tickers = config_tickers(self.config)
        self.prefixes = parse_prefixes(self.config.get("price_isin_prefixes"))
        self.timeout = 10
        self.verify_ssl = False  # matches prod; Somansa CA baked, warnings suppressed

        self.state = SnapshotState()
        self.stop_event = asyncio.Event()

        self.engine: InavEngine | None = None
        self.instruments: list[dict] = []
        self.etf_meta: dict[str, dict] = {}
        self.etf_names: dict[str, str] = {}
        self.component_names: dict[str, str] = {}
        self.wrap: WrapCollector | None = None
        self.run_date = legacy_inputs.kst_today()
        self._token_valid = False

        self.store: KisStore | None = None
        self.master: KisMaster | None = None
        self.futureoption: DomesticFutureOptionMaster | None = None
        self.auth: KisAuth | None = None
        self.rest: KisRestClient | None = None
        self.ws: KisWebSocket | None = None

    # ── KIS clients / token ────────────────────────────────────────────
    def _init_clients(self) -> None:
        legacy_inputs.ensure_dirs()
        legacy_inputs.wire_holiday_dir()
        legacy_inputs.sync_db()
        legacy_inputs.sync_master()
        self.store = KisStore(db_path=DB_DEST)
        try:
            self.store.init_db()
        except Exception as exc:  # noqa: BLE001 - never block on cache init
            _log(f"store.init_db failed: {exc!r}")
        self.master = KisMaster(
            cache_dir=MASTER_CACHE_DIR, verify_ssl=self.verify_ssl, timeout=self.timeout
        )
        self.futureoption = DomesticFutureOptionMaster(
            cache_dir=MASTER_CACHE_DIR, verify_ssl=self.verify_ssl, timeout=self.timeout
        )
        try:
            creds = KisCredentials.from_env(paper=False)
            self.auth = KisAuth(
                creds, cache_dir=CACHE_DIR, verify_ssl=self.verify_ssl, timeout=self.timeout
            )
            self.rest = KisRestClient(auth=self.auth, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - missing creds → prices stay stale
            _log(f"KIS credentials unavailable ({exc!r}); REST prices disabled")
            self.auth = None
            self.rest = None
        # WRAP 수익률 수집기 — master/rest 재사용 (rollover 시 새 클라이언트로 재생성).
        if self.master is not None and self.rest is not None:
            self.wrap = WrapCollector(self.master, self.rest)
        else:
            self.wrap = None

    def _ensure_token(self) -> bool:
        """Ensure a usable KIS access token.

        First try the (harmless) legacy piggyback: stage a still-valid legacy
        token into the writable cache. If none is available and token issuance
        is allowed, let KisAuth issue one naturally (it caches to the same
        /app/.cache path, so a subsequent ``sync_token`` picks it up). With
        issuance disabled this reverts to strict piggyback-only behavior.
        """
        if self.rest is None or self.auth is None:
            self.state.set_token(False, None)
            self._token_valid = False
            return False
        valid, expires_at = legacy_inputs.sync_token()
        if not valid and ALLOW_TOKEN_ISSUE:
            try:
                self.auth.access_token()  # issues + caches under /app/.cache
                valid, expires_at = legacy_inputs.sync_token()
                if valid:
                    _log(f"KIS token issued (ttl {int(expires_at - time.time())}s)")
            except Exception as exc:  # noqa: BLE001 - REST stays stale on failure
                _log(f"KIS token issuance failed: {exc!r}")
                valid, expires_at = False, None
        self._token_valid = valid
        self.state.set_token(valid, expires_at)
        return valid

    # ── data fetchers (run in executor) ────────────────────────────────
    def _fetch_kis_snapshots(self) -> list[dict]:
        if not self._ensure_token() or self.rest is None:
            return []
        kis = [
            inst for inst in self.instruments
            if (inst.get("exchange") or "").upper() not in TAIWAN_EXCHANGES
        ]
        targets = [
            ((inst.get("exchange") or "").upper(), str(inst.get("ticker") or "").upper())
            for inst in kis
        ]
        targets = [(exch, sym) for exch, sym in targets if exch and sym]
        if not targets:
            return []
        try:
            return self.rest.snapshots(
                targets,
                batch_delay_seconds=PRICE_DELAY_SECONDS,
                max_workers=PRICE_WORKERS,
                overseas_batch_size=OVERSEAS_BATCH_SIZE,
            )
        except Exception as exc:  # noqa: BLE001 - fail-stale
            _log(f"KIS snapshot fetch failed: {exc!r}")
            return []

    def _fetch_twse_snapshots(self) -> list[dict]:
        taiwan = [
            inst for inst in self.instruments
            if (inst.get("exchange") or "").upper() in TAIWAN_EXCHANGES
        ]
        if not taiwan:
            return []
        targets = [
            ((inst.get("exchange") or "").upper(), str(inst.get("ticker") or "").upper())
            for inst in taiwan
        ]
        targets = [(exch, sym) for exch, sym in targets if exch and sym]
        if not targets:
            return []
        try:
            raw = fetch_twse_prices(targets, timeout=self.timeout, verify_ssl=self.verify_ssl)
        except Exception as exc:  # noqa: BLE001 - fail-stale
            _log(f"TWSE fetch failed: {exc!r}")
            return []
        exch_by_symbol = {sym: exch for exch, sym in targets}
        out: list[dict] = []
        for snap in raw:
            symbol = (snap.get("symbol") or "").upper()
            original = exch_by_symbol.get(symbol)
            if not original:
                continue
            snap = dict(snap)
            snap["exchange"] = original
            snap["symbol"] = symbol
            out.append(snap)
        return out

    def _fetch_etf_quotes(self) -> dict[str, dict]:
        """KR 상장 ETF 자체의 현재가/등락률(FHKST01010100, KRX+NXT 병합)."""
        if not self._ensure_token() or self.rest is None:
            return {}
        quotes: dict[str, dict] = {}
        for ticker in self.target_tickers:
            try:
                snap = self.rest.domestic_snapshot(str(ticker))
            except Exception as exc:  # noqa: BLE001 - fail-stale per ticker
                _log(f"ETF quote fetch failed for {ticker}: {exc!r}")
                continue
            last = snap.get("last")
            if not _pos(last):
                continue
            raw = snap.get("raw") or {}
            try:
                change_pct = float(raw.get("prdy_ctrt"))
            except (TypeError, ValueError):
                base = snap.get("base")
                change_pct = (
                    (float(last) / float(base) - 1) * 100 if _pos(base) else None
                )
            quotes[str(ticker).upper()] = {
                "price": float(last),
                "prev_close": json_safe(snap.get("base")),
                "change_pct": json_safe(change_pct),
                "trade_value_krw": json_safe(snap.get("value")),
                "trade_time": snap.get("trade_time"),
            }
            time.sleep(PRICE_DELAY_SECONDS)
        return quotes

    # ── engine build (setup + rollover) ────────────────────────────────
    async def _build_engine(self, run_date: str) -> None:
        loop = asyncio.get_running_loop()
        self.run_date = run_date
        self.state.set_run_date(run_date)

        pdf_df, etf_list_df, market_df, basis, source = legacy_inputs.load_krx_inputs(
            run_date, self.target_tickers
        )
        self.state.set_basket(basis, source)

        pdf_df, etf_list_df, market_df = filter_inputs_by_ticker(
            pdf_df, etf_list_df, market_df, tickers=self.target_tickers, max_etfs=None
        )
        if pdf_df is None or pdf_df.empty:
            raise RuntimeError("legacy KRX PDF empty after ticker filter")

        prepared_pdf = prepare_pdf_df(pdf_df, self.prefixes)
        stock_rows = build_component_stock_rows(prepared_pdf)
        _log(
            f"prepared PDF rows={len(prepared_pdf)} "
            f"ETFs={prepared_pdf['ETF_TICKER'].nunique()} "
            f"price_candidates={int(prepared_pdf['is_price_candidate'].sum())} "
            f"stock_rows={len(stock_rows)}"
        )
        self.component_names = {
            str(row.get("ISIN") or "").upper(): str(row.get("name") or "")
            for row in stock_rows
        }
        self.etf_meta = _etf_list_meta(etf_list_df)
        self.etf_names = {
            ticker: meta["name"]
            for ticker, meta in self.etf_meta.items()
            if meta.get("name")
        }
        _log(f"ETF names resolved={len(self.etf_names)}")

        try:
            instruments, unresolved = await loop.run_in_executor(
                None, self._resolve, stock_rows
            )
        except Exception as exc:  # noqa: BLE001 - engine still builds without prices
            _log(f"resolve_instruments failed: {exc!r}; continuing with no instruments")
            instruments, unresolved = [], []
        self.instruments = instruments
        _log(f"instruments resolved={len(instruments)} unresolved={len(unresolved)}")

        fx_table = await loop.run_in_executor(None, self._fetch_fx)

        engine = InavEngine(prepared_pdf, etf_list_df, market_df, instruments=instruments)
        engine.set_fx_rates(fx_table)

        seed_snaps = await loop.run_in_executor(None, self._fetch_kis_snapshots)
        twse_snaps = await loop.run_in_executor(None, self._fetch_twse_snapshots)
        if seed_snaps:
            engine.bulk_update_from_snapshots(seed_snaps)
        if twse_snaps:
            engine.bulk_update_from_snapshots(twse_snaps)

        self.engine = engine
        if fx_table.get("rates") and len(fx_table["rates"]) > 1:
            self.state.mark_fx()
        if any(_pos(s.get("last")) for s in seed_snaps):
            self.state.mark_price()
        if any(_pos(s.get("last")) for s in twse_snaps):
            self.state.mark_twse()
        self._compute_once()
        _log(
            f"engine built basis={basis} source={source} fx={engine.fx_rates} "
            f"seed_prices={len(seed_snaps)} twse_seed={len(twse_snaps)} "
            f"token_valid={self._token_valid}"
        )

    def _resolve(self, stock_rows: list[dict]) -> tuple[list[dict], list[dict]]:
        return resolve_instruments(
            stock_rows,
            store=self.store,
            master=self.master,
            openfigi_api_key=None,
            verify_ssl=self.verify_ssl,
            timeout=self.timeout,
            isin_batch_size=10,
            batch_delay_seconds=2.0,
            futureoption_master=self.futureoption,
        )

    def _fetch_fx(self) -> dict:
        try:
            return fetch_fx_table(FX_SYMBOLS, timeout=self.timeout, verify_ssl=self.verify_ssl)
        except Exception as exc:  # noqa: BLE001 - fail-stale
            _log(f"FX fetch failed: {exc!r}")
            return {"rates": {}, "detail": {}, "errors": [str(exc)], "fetched_at": now_kst_string()}

    # ── compute → state ────────────────────────────────────────────────
    def _compute_once(self) -> None:
        if self.engine is None:
            return
        components, summary = self.engine.compute()
        rows, sums = self._build_summary_rows(components, summary)
        self.state.update_etfs(rows, self.engine.fx_rates, now_kst_string(), sums)
        payload = self._build_components_payload(components, summary)
        if payload is not None:
            self.state.update_components(payload)

    def _build_summary_rows(
        self, components: pd.DataFrame, summary: pd.DataFrame
    ) -> tuple[list[dict], dict]:
        priced_value_by_ticker: dict[str, float | None] = {}
        cash_count_by_ticker: dict[str, int] = {}
        if components is not None and not components.empty:
            for ticker, group in components.groupby("ETF_TICKER", dropna=False):
                priced = group["is_price_updated"]
                kfo = group["kis_exchange"].eq("KFO")
                nonkfo = group.loc[priced & ~kfo, "live_value_krw"].sum(min_count=1)
                kfo_delta = group.loc[priced & kfo, "price_delta_krw"].sum(min_count=1)
                parts = [p for p in (nonkfo, kfo_delta) if pd.notna(p)]
                priced_value_by_ticker[str(ticker)] = float(sum(parts)) if parts else None
                # 현금(설정현금·원화현금)은 '구성종목' 카운트에서 제외 — 카드의 n/m 분모용.
                cash_count_by_ticker[str(ticker)] = int(
                    group["row_type"].isin(("setting_cash_anchor", "krw_cash")).sum()
                )

        rows: list[dict] = []
        if summary is None or summary.empty:
            return rows
        etf_quotes = self.state.etf_quotes()
        # CHECK 호가(에이전트 POST) 서버측 병합 — 수신 15초 초과면 병합하지 않음(카드 '−' 복귀).
        hoga_by_code: dict[str, dict] = {}
        hoga = self.state.hoga()
        hoga_recv_age = hoga.get("hoga_last_received_age_s")
        if hoga.get("payload") and hoga_recv_age is not None and hoga_recv_age < 15.0:
            for item in hoga["payload"].get("etfs") or []:
                code = str(item.get("code") or "").strip().upper()
                if code:
                    hoga_by_code[code] = item
        for _, record in summary.iterrows():
            ticker = str(record.get("ETF_TICKER") or "").strip()
            if not ticker:
                continue
            quote = etf_quotes.get(ticker.upper()) or {}
            hoga_row = hoga_by_code.get(ticker.upper()) or {}
            inav = json_safe(record.get("inav_per_share"))
            # 국내가: 실시간 도메스틱 시세 우선, 없으면 KRX 일별 프레임 값.
            kr_price = json_safe(quote.get("price"))
            if kr_price is None:
                kr_price = json_safe(record.get("kr_etf_price"))
            deviation = None
            if isinstance(inav, (int, float)) and inav and isinstance(kr_price, (int, float)):
                deviation = (kr_price / inav - 1) * 100
            inav_total = (
                inav * INAV_DIVISOR if isinstance(inav, (int, float)) and inav else None
            )
            priced_value = priced_value_by_ticker.get(ticker)
            priced_weight = None
            if priced_value is not None and inav_total:
                priced_weight = priced_value / inav_total * 100
            # AUM(상장좌수×iNAV)·연보수 — KRX 목록의 LIST_SHRS/ETF_TOT_FEE 기반.
            meta = self.etf_meta.get(ticker.upper()) or {}
            list_shrs = meta.get("list_shrs")
            fee_pct = meta.get("fee_pct")
            aum_krw = (
                inav * list_shrs
                if isinstance(inav, (int, float))
                and isinstance(list_shrs, (int, float))
                and list_shrs
                else None
            )
            annual_fee_krw = (
                aum_krw * fee_pct / 100
                if aum_krw is not None and isinstance(fee_pct, (int, float))
                else None
            )
            rows.append(
                {
                    "ticker": ticker,
                    "name": str(record.get("ETF_NAME") or "")
                    or self.etf_names.get(ticker.upper(), ""),
                    "inav_per_share": inav,
                    "kr_etf_price": kr_price,
                    "change_pct": json_safe(quote.get("change_pct")),
                    "prev_close": json_safe(quote.get("prev_close")),
                    "trade_value_krw": json_safe(quote.get("trade_value_krw")),
                    "aum_krw": json_safe(aum_krw),
                    "expense_pct": json_safe(fee_pct),
                    "annual_fee_krw": json_safe(annual_fee_krw),
                    "deviation_pct": json_safe(deviation),
                    "priced_weight_pct": json_safe(priced_weight),
                    # CHECK 호가 병합값 — premiumIntra=거래소 공시 장중괴리(%), lpAmt=억 단위→원 환산.
                    "intraday_dev_pct": json_safe(hoga_row.get("premiumIntra")),
                    "lp_value_krw": (
                        json_safe(hoga_row["lpAmt"] * 1e8)
                        if isinstance(hoga_row.get("lpAmt"), (int, float))
                        else None
                    ),
                    "component_count": (
                        max(comp_total - cash_count_by_ticker.get(ticker, 0), 0)
                        if (comp_total := _int_or_none(record.get("component_count"))) is not None
                        else None
                    ),
                    "price_candidate_count": _int_or_none(record.get("price_candidate_count")),
                    "priced_component_count": _int_or_none(record.get("priced_component_count")),
                }
            )
        # 헤더 합계 — 구 대시보드 규칙: ACE 프리픽스(자사 ETF)만 합산.
        sums: dict[str, float | None] = {
            "aum_krw": None,
            "trade_value_krw": None,
            "annual_fee_krw": None,
        }
        for row in rows:
            if not str(row.get("name") or "").startswith("ACE"):
                continue
            for key in sums:
                value = row.get(key)
                if value is None:
                    continue
                sums[key] = (sums[key] or 0.0) + value
        return rows, sums

    def _build_components_payload(
        self, components: pd.DataFrame, summary: pd.DataFrame
    ) -> dict | None:
        """구성종목 상세(구 kis_inav_components.js 대응) — 모달/무버 티커용."""
        if components is None or components.empty or self.engine is None:
            return None
        prices = getattr(self.engine, "_prices", {}) or {}
        inav_totals: dict[str, float | None] = {}
        if summary is not None and not summary.empty:
            for _, rec in summary.iterrows():
                key = str(rec.get("ETF_TICKER") or "").strip().upper()
                if not key:
                    continue
                # inav_total_krw 는 SUMMARY_COLUMNS 에서 잘려나가므로 좌당 iNAV 로 복원.
                total = json_safe(rec.get("inav_total_krw"))
                if total is None:
                    inav = json_safe(rec.get("inav_per_share"))
                    total = (
                        inav * INAV_DIVISOR
                        if isinstance(inav, (int, float)) and inav
                        else None
                    )
                inav_totals[key] = total
        by_etf: dict[str, dict] = {}
        for ticker, group in components.groupby("ETF_TICKER", dropna=False):
            key = str(ticker or "").strip().upper()
            if not key:
                continue
            total = inav_totals.get(key)
            comp_rows: list[dict] = []
            for _, row in group.iterrows():
                isin = str(row.get("component_isin") or "").upper()
                row_type = str(row.get("row_type") or "")
                is_cash = row_type in ("setting_cash_anchor", "krw_cash")
                live = json_safe(row.get("live_price"))
                base = json_safe(row.get("base_price"))
                fx = json_safe(row.get("fx_rate"))
                live_value = json_safe(row.get("live_value_krw"))
                if is_cash:
                    krw_price = live_value
                elif live is not None and fx is not None:
                    krw_price = live * fx
                else:
                    krw_price = None
                weight = (
                    live_value / total * 100
                    if live_value is not None and total
                    else None
                )
                if is_cash:
                    name = "원화현금" if row_type == "krw_cash" else "설정현금"
                else:
                    name = self.component_names.get(isin, "")
                price_rec = prices.get(isin) or {}
                comp_rows.append(
                    {
                        "isin": isin or None,
                        "name": name,
                        "exchange": str(row.get("kis_exchange") or "") or None,
                        "currency": str(row.get("currency") or "") or None,
                        "quantity": json_safe(row.get("quantity")),
                        "basePrice": base,
                        "livePrice": live,
                        "krwPrice": json_safe(krw_price),
                        "weightPct": json_safe(weight),
                        "tradeTime": price_rec.get("trade_time"),
                        "isCash": is_cash,
                        "valueSource": str(row.get("value_source") or ""),
                    }
                )
            by_etf[key] = {
                "etfName": self.etf_names.get(key, ""),
                "inavTotalKrw": total,
                "components": comp_rows,
            }
        fx_rates = {
            str(k): json_safe(v) for k, v in (self.engine.fx_rates or {}).items()
        }
        return {
            "generatedAt": now_kst_string(),
            "timestamp": int(time.time() * 1000),
            "fxRates": fx_rates,
            "byEtf": by_etf,
        }

    # ── async loops ────────────────────────────────────────────────────
    async def _sleep_or_stop(self, seconds: float) -> bool:
        """Return True if we should stop, False after a normal interval."""
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _fx_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            if await self._sleep_or_stop(FX_REFRESH_S):
                return
            try:
                fx_table = await loop.run_in_executor(None, self._fetch_fx)
                if fx_table.get("rates") and len(fx_table["rates"]) > 1 and self.engine is not None:
                    self.engine.set_fx_rates(fx_table)
                    self.state.mark_fx()
            except Exception as exc:  # noqa: BLE001
                _log(f"fx loop cycle failed: {exc!r}")

    async def _price_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            if await self._sleep_or_stop(PRICE_REFRESH_S):
                return
            try:
                snaps = await loop.run_in_executor(None, self._fetch_kis_snapshots)
                if snaps and self.engine is not None:
                    self.engine.bulk_update_from_snapshots(snaps)
                    if any(_pos(s.get("last")) for s in snaps):
                        self.state.mark_price()
            except Exception as exc:  # noqa: BLE001
                _log(f"price loop cycle failed: {exc!r}")

    async def _twse_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if not any(
            (inst.get("exchange") or "").upper() in TAIWAN_EXCHANGES for inst in self.instruments
        ):
            return
        post_close_poll = min(60.0, TWSE_REFRESH_S)
        while not self.stop_event.is_set():
            wait_s = post_close_poll if is_twse_post_close_window() else TWSE_REFRESH_S
            if await self._sleep_or_stop(wait_s):
                return
            if not (is_twse_trading_hours() or is_twse_post_close_window()):
                continue
            try:
                snaps = await loop.run_in_executor(None, self._fetch_twse_snapshots)
                if snaps and self.engine is not None:
                    self.engine.bulk_update_from_snapshots(snaps)
                    if any(_pos(s.get("last")) for s in snaps):
                        self.state.mark_twse()
            except Exception as exc:  # noqa: BLE001
                _log(f"twse loop cycle failed: {exc!r}")

    # ── KIS realtime WebSocket lane ────────────────────────────────────
    async def _etf_quote_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            try:
                quotes = await loop.run_in_executor(None, self._fetch_etf_quotes)
                if quotes:
                    self.state.set_etf_quotes(quotes)
            except Exception as exc:  # noqa: BLE001
                _log(f"etf quote loop cycle failed: {exc!r}")
            if await self._sleep_or_stop(ETF_QUOTE_REFRESH_S):
                return

    def _build_wrap_payload(self) -> dict | None:
        if self.wrap is None or not self._ensure_token():
            return None
        return self.wrap.build_payload()

    async def _wrap_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            try:
                payload = await loop.run_in_executor(None, self._build_wrap_payload)
                if payload:
                    self.state.update_wrap(payload)
            except Exception as exc:  # noqa: BLE001
                _log(f"wrap loop cycle failed: {exc!r}")
            if await self._sleep_or_stop(WRAP_REFRESH_S):
                return

    def _ws_targets(self) -> list[tuple[str, str]]:
        """Instruments priceable over the KIS realtime-delayed WS feed.

        Domestic (KRX/KFO) and Taiwan (TWSE/TPEX) are excluded: they are not in
        EXCHANGE_TO_TRKEY and stay on their REST / TWSE lanes.
        """
        targets: list[tuple[str, str]] = []
        for inst in self.instruments:
            exchange = str(inst.get("exchange") or "").upper()
            symbol = str(inst.get("ticker") or "").upper()
            if exchange in EXCHANGE_TO_TRKEY and symbol:
                targets.append((exchange, symbol))
        return targets

    async def _ws_receiver(self) -> None:
        """Live price lane: consume raw HDFSCNT0 frames and merge each tick's
        last price into the engine. We read frames directly (not the verbatim
        ``KisWebSocket.events()``, whose column map is off-by-one for the live
        frame) and echo KIS's JSON ``PINGPONG`` keepalive so the session stays
        open. Transient zero ticks are dropped by the parser and by
        ``update_last_by_key``. Runs until the socket closes; the supervisor
        then reconnects."""
        conn = self.ws._connection
        if conn is None:
            return
        async for raw in conn:
            if not isinstance(raw, str) or not raw:
                continue
            if raw[0] == "{":
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if payload.get("header", {}).get("tr_id") == "PINGPONG":
                    await conn.send(raw)
                continue
            if raw[0] not in ("0", "1") or self.engine is None:
                continue
            for exchange, symbol, last, xhms in _parse_hdfscnt0_ticks(raw):
                self.engine.update_last_by_key(
                    exchange, symbol, last, extra={"trade_time": xhms}
                )
                self.state.mark_ws_tick()
                self.state.mark_price()

    async def _rotation_loop(self, batches: list[list[tuple[str, str]]]) -> None:
        """Rotate 40-subscription batches when targets exceed the KIS cap."""
        current = 0
        while not self.stop_event.is_set():
            batch = batches[current % len(batches)]
            try:
                await self.ws.subscribe(batch)
                self.state.set_ws_subscribed(self.ws.subscription_count)
                _log(
                    f"WS: batch {current % len(batches) + 1}/{len(batches)} "
                    f"subscribed={len(batch)}"
                )
            except Exception as exc:  # noqa: BLE001
                _log(f"WS: subscribe failed: {exc!r}")
            if await self._sleep_or_stop(WS_ROTATION_S):
                return
            try:
                await self.ws.unsubscribe(batch)
                self.state.set_ws_subscribed(self.ws.subscription_count)
            except Exception as exc:  # noqa: BLE001
                _log(f"WS: unsubscribe failed: {exc!r}")
            current += 1

    async def _ws_loop(self) -> None:
        """Supervise the WS session: connect, (rotate/)subscribe, receive ticks,
        reconnect on drop. Recreates KisWebSocket per attempt so a fresh socket
        starts with an empty subscription set."""
        if self.auth is None:
            _log("WS: KIS auth unavailable; realtime lane disabled")
            return
        targets = self._ws_targets()
        if not targets:
            _log("WS: no supported overseas targets; realtime lane idle")
            return
        rotating = len(targets) > MAX_SUBSCRIPTIONS
        batches: list[list[tuple[str, str]]] | None = None
        if rotating:
            batches = [
                targets[i : i + MAX_SUBSCRIPTIONS]
                for i in range(0, len(targets), MAX_SUBSCRIPTIONS)
            ]
            self.state.set_ws_rotation(len(batches), WS_ROTATION_S)
            _log(
                f"WS: targets={len(targets)} exceed cap={MAX_SUBSCRIPTIONS}; "
                f"rotating {len(batches)} batches every {WS_ROTATION_S:g}s"
            )
        else:
            self.state.set_ws_rotation(1, None)
            _log(f"WS: targets={len(targets)} within cap={MAX_SUBSCRIPTIONS}")

        while not self.stop_event.is_set():
            rotation_task: asyncio.Task | None = None
            self.ws = KisWebSocket(self.auth)
            try:
                await self.ws.connect()  # obtains approval_key + opens the socket
                self.state.set_ws_connected(True)
                _log("WS: connected (approval_key obtained)")
                if rotating and batches is not None:
                    rotation_task = asyncio.create_task(self._rotation_loop(batches))
                else:
                    await self.ws.subscribe(targets)
                    self.state.set_ws_subscribed(self.ws.subscription_count)
                    _log(f"WS: subscribed={self.ws.subscription_count}")
                await self._ws_receiver()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect after the delay
                _log(f"WS: session ended ({exc!r})")
            finally:
                self.state.set_ws_connected(False)
                self.state.set_ws_subscribed(0)
                if rotation_task is not None:
                    rotation_task.cancel()
                    await asyncio.gather(rotation_task, return_exceptions=True)
                try:
                    await self.ws.close()
                except Exception:  # noqa: BLE001
                    pass
            if await self._sleep_or_stop(WS_RECONNECT_S):
                return

    async def _compute_loop(self) -> None:
        while not self.stop_event.is_set():
            if await self._sleep_or_stop(COMPUTE_INTERVAL_S):
                return
            try:
                self._compute_once()
            except Exception as exc:  # noqa: BLE001
                _log(f"compute cycle failed: {exc!r}")

    async def _rollover_loop(self) -> None:
        while not self.stop_event.is_set():
            if await self._sleep_or_stop(ROLLOVER_CHECK_S):
                return
            current = legacy_inputs.kst_today()
            if current == self.run_date:
                continue
            _log(f"KST date rollover {self.run_date} -> {current}; rebuilding engine")
            try:
                self._init_clients()
                await self._build_engine(current)
            except Exception as exc:  # noqa: BLE001 - keep last-good engine
                _log(f"rollover rebuild failed: {exc!r}; keeping previous engine")

    # ── FastAPI / uvicorn ──────────────────────────────────────────────
    def _build_app(self) -> FastAPI:
        app = FastAPI(title="ETF iNAV collector", docs_url=None, redoc_url=None)
        state = self.state

        @app.get("/snapshot")
        def snapshot(request: Request):
            etag = state.etag()
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers={"ETag": etag})
            return JSONResponse(state.snapshot(), headers={"ETag": etag})

        @app.get("/components")
        def components(request: Request):
            payload = state.components()
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            etag = state.components_etag()
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers={"ETag": etag})
            return JSONResponse(payload, headers={"ETag": etag})

        @app.get("/wrap")
        def wrap(request: Request):
            payload = state.wrap()
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            etag = state.wrap_etag()
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers={"ETag": etag})
            return JSONResponse(payload, headers={"ETag": etag})

        @app.post("/ingest/hoga")
        async def ingest_hoga(request: Request):
            envelope = await request.json()
            stored = state.update_hoga(envelope)
            if not stored:
                return JSONResponse({"ok": True, "ignored": "stale_seq"})
            return JSONResponse({"ok": True})

        @app.get("/hoga")
        def hoga():
            return JSONResponse(state.hoga())

        @app.get("/health")
        def health():
            return JSONResponse(state.health())

        return app

    async def _serve_api(self) -> None:
        config = uvicorn.Config(
            self._build_app(),
            host=API_HOST,
            port=API_PORT,
            log_level="warning",
            access_log=False,
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # we own signals
        serve_task = asyncio.create_task(server.serve())
        await self.stop_event.wait()
        server.should_exit = True
        await serve_task

    # ── entrypoint ─────────────────────────────────────────────────────
    async def run(self) -> None:
        self._init_clients()
        await self._build_engine(self.run_date)
        _log("setup completed")

        loop = asyncio.get_running_loop()

        def _request_stop() -> None:
            self.stop_event.set()

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, _request_stop)
            except (NotImplementedError, RuntimeError):
                pass

        tasks = [
            asyncio.create_task(self._compute_loop()),
            asyncio.create_task(self._fx_loop()),
            asyncio.create_task(self._price_loop()),
            asyncio.create_task(self._etf_quote_loop()),
            asyncio.create_task(self._wrap_loop()),
            asyncio.create_task(self._twse_loop()),
            asyncio.create_task(self._ws_loop()),
            asyncio.create_task(self._rollover_loop()),
            asyncio.create_task(self._serve_api()),
        ]
        _log(f"loops started (api on {API_HOST}:{API_PORT})")
        try:
            await self.stop_event.wait()
        finally:
            _log("stopping")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    collector = Collector()
    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt:
        pass
    _log("stopped")


if __name__ == "__main__":
    main()
