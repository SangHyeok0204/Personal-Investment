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
from etf_inav.data_sources.us_daytime import US_DAYTIME_EXCHANGE_MAP, us_daytime_window
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
from collector.guru13f import Guru13F
from collector.stock_monitor import StockMonitor

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
# 아침 PDF 재로딩 시각(KST 분). 자정 롤오버는 오늘 KRX PDF(≈08:35 생성) 전이라 전일
# 바스켓으로 빌드된다 → 08:40 이후 오늘 basket 이 아직이면 재빌드해 오늘 PDF 를 태운다.
MORNING_RELOAD_MIN = 8 * 60 + 40  # 08:40 KST
LP_EVAL_SAMPLE_S = 60.0        # LP 평가 — 인정 스프레드 틱 체류시간 표본 주기(1분)
# LP 평가 일일 스케줄 — 자정 개장일 판정 + 16:30 마스터 CSV 이관. 폴링(60초)으로 보는
# 이유는 _rollover_loop 와 같다: 재기동이 그 시각을 지나 일어나도(예: 16:41 복구) 그
# 날 이관이 통째로 빠지지 않고 다음 분에 따라잡는다.
LP_EVAL_DAILY_CHECK_S = 60.0
LP_EVAL_EXPORT_MIN = 16 * 60 + 30   # 16:30 KST

# [뉴스 모니터링 · 텔레그램] 카드 재계산 주기. 상류 수집기가 30분마다 raw CSV 에
# append 하므로 이보다 잦게 돌 이유는 '시간 감쇠로 카드 순위가 밀리는 것'뿐이다.
# 상류 집계는 하루 2회(08:00·13:00)뿐이라 판독은 드물어도 된다. 다만 stale 판정이
# 풀링 시각을 지나는 순간 서야 해서, 파일이 그대로여도 이 주기로 다시 판정한다.
TELEGRAM_NEWS_REFRESH_S = 120.0

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


def _kst_minutes_now() -> int:
    """현재 KST 자정 기준 분(0~1439). 컨테이너 TZ 무관(UTC+9 고정 오프셋)."""
    return int(((time.time() + 9 * 3600) % 86400) // 60)


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
        # GURU[13F] 서비스 (KIS 비의존, 독립 refresh 루프 + 로컬 .cache 스냅샷).
        self.guru13f = Guru13F()
        # [종목 모니터] KOSPI200 분봉 급등락·이상탐지 (독립 .cache 스냅샷, KIS 비의존).
        self.stock_monitor = StockMonitor()

        self.engine: InavEngine | None = None
        self.instruments: list[dict] = []
        self.etf_meta: dict[str, dict] = {}
        self.etf_names: dict[str, str] = {}
        self.component_names: dict[str, str] = {}
        self.wrap: WrapCollector | None = None
        self.run_date = legacy_inputs.kst_today()
        self._token_valid = False
        # 마지막 성공 FX 테이블(naver_fx.fetch_fx_table 전체 — detail 의
        # fluctuations_pct 를 WRAP 환 수익률 컬럼이 사용). last-good 유지.
        self._fx_table: dict | None = None
        # 미국 주간거래(데이장) 전일종가 핀 — {(정규거래소, 심볼): 최신 완결 세션
        # 공식 종가}. 데이장/스냅샷 TR 의 base 는 하루 낡거나 애프터마켓으로
        # 표류하므로 일봉(HHDFS76240000) 종가로 대체한다. KST 일자당 1회 수집.
        self._us_prev_close: dict[tuple[str, str], float] = {}
        self._us_prev_close_date: str | None = None
        self._us_daytime_active: bool | None = None

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
    def _refresh_us_prev_closes(self, us_pairs: list[tuple[str, str]]) -> None:
        """미국 종목의 '전일종가'를 일봉 공식 종가로 핀 (KST 일자당 1회, 결측만 재시도).

        스냅샷 TR 의 base 는 데이장 코드에서 하루 낡은 값이 오고, 정규장 코드의
        last 는 애프터마켓 체결로 표류할 수 있어(rest_client 일봉 docstring 참조)
        HHDFS76240000 일봉의 최신 완결 세션 종가를 정본으로 쓴다.
        """
        if self.rest is None:
            return
        today = legacy_inputs.kst_today()
        if self._us_prev_close_date != today:
            self._us_prev_close = {}
            self._us_prev_close_date = today
        missing = [
            pair for pair in dict.fromkeys(us_pairs) if pair not in self._us_prev_close
        ]
        if not missing:
            return
        fetched = 0
        for exch, sym in missing:
            try:
                bars = self.rest.overseas_daily_bars(exch, sym, count=1)
            except Exception:  # noqa: BLE001 - 결측 심볼은 다음 사이클에 재시도
                continue
            close = bars[0].get("close") if bars else None
            if close is not None and close > 0:
                self._us_prev_close[(exch, sym)] = float(close)
                fetched += 1
            time.sleep(PRICE_DELAY_SECONDS)
        if fetched:
            _log(
                f"US prev-close pinned {fetched}/{len(missing)} "
                f"(total={len(self._us_prev_close)} date={today})"
            )

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
        # 미국 주간거래(데이장) 윈도우 중엔 NAS/NYS/AMS 를 BAQ/BAY/BAA 로 치환
        # 요청한다. 정규장 코드는 한국 낮 동안 전일 종가에 동결되어 있기 때문.
        # 응답은 원래 거래소 키로 되돌려 엔진 (exchange, symbol)→ISIN 매핑을 유지.
        day_active = False
        us_pairs = [(exch, sym) for exch, sym in targets if exch in US_DAYTIME_EXCHANGE_MAP]
        if us_pairs:
            try:
                day_active = bool(us_daytime_window()["active"])
            except Exception as exc:  # noqa: BLE001 - 판정 실패 시 정규장 코드 유지
                _log(f"US daytime window check failed: {exc!r}")
        if day_active != self._us_daytime_active:
            _log(
                "US daytime quotes "
                + ("ON (NAS/NYS/AMS→BAQ/BAY/BAA)" if day_active else "OFF (regular codes)")
            )
            self._us_daytime_active = day_active
        origin_by_request: dict[tuple[str, str], str] = {}
        if day_active:
            self._refresh_us_prev_closes(us_pairs)
            request_targets = []
            for exch, sym in targets:
                request_exch = US_DAYTIME_EXCHANGE_MAP.get(exch, exch)
                if request_exch != exch:
                    origin_by_request[(request_exch, sym)] = exch
                request_targets.append((request_exch, sym))
        else:
            request_targets = targets
        try:
            snaps = self.rest.snapshots(
                request_targets,
                batch_delay_seconds=PRICE_DELAY_SECONDS,
                max_workers=PRICE_WORKERS,
                overseas_batch_size=OVERSEAS_BATCH_SIZE,
            )
        except Exception as exc:  # noqa: BLE001 - fail-stale
            _log(f"KIS snapshot fetch failed: {exc!r}")
            return []
        if not origin_by_request:
            return snaps
        out: list[dict] = []
        for snap in snaps:
            key = (
                str(snap.get("exchange") or "").upper(),
                str(snap.get("symbol") or "").upper(),
            )
            origin = origin_by_request.get(key)
            if origin is not None:
                snap = dict(snap)
                snap["exchange"] = origin
                pinned = self._us_prev_close.get((origin, key[1]))
                if pinned is not None:
                    snap["base"] = pinned
                else:
                    # 데이장 base(하루 낡음)로 기존 base 를 덮지 않는다.
                    snap.pop("base", None)
            out.append(snap)
        return out

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
        self._basket_basis = basis  # 아침 재로딩이 "오늘 PDF 로 실렸나" 판단용

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
        if fx_table.get("rates") and len(fx_table["rates"]) > 1:
            self._fx_table = fx_table

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
            # 국내 시세: CHECK 에이전트 체결가 우선 → KIS REST → KRX 일별 프레임.
            # CHECK 값은 호가와 같은 envelope 라 알림의 틱 판정 기준가와 일치하고
            # 1초 주기라 REST(15초)보다 신선하다. CHECK 가 끊기면(15초 초과) 자동으로
            # REST 로 내려가므로 서버는 계속 동작한다.
            # ※ CHECK 의 basePrice 는 현재가를 그대로 되돌려주고 있어(2026-07-23 실측,
            #   14종 전부 price 와 동일) 전일종가로 쓸 수 없다 — prev_close 는 KIS 유지.
            kr_price = json_safe(hoga_row.get("price"))
            change_pct = json_safe(hoga_row.get("change"))
            if kr_price is None:
                kr_price = json_safe(quote.get("price"))
            if change_pct is None:
                change_pct = json_safe(quote.get("change_pct"))
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
                    "change_pct": change_pct,
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
                if fx_table.get("rates") and len(fx_table["rates"]) > 1:
                    self._fx_table = fx_table
                    if self.engine is not None:
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
        return self.wrap.build_payload(fx_table=self._fx_table)

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
            if current != self.run_date:
                _log(f"KST date rollover {self.run_date} -> {current}; rebuilding engine")
                try:
                    self._init_clients()
                    await self._build_engine(current)
                except Exception as exc:  # noqa: BLE001 - keep last-good engine
                    _log(f"rollover rebuild failed: {exc!r}; keeping previous engine")
                continue
            # 아침 PDF 재로딩 — 자정 롤오버는 오늘 PDF(≈08:35 생성) 전이라 전일 바스켓
            # 으로 빌드된다. 08:40 이후 오늘 basket 이 아직이면 재빌드해 오늘 PDF 를
            # 태운다. 이미 오늘 걸(재기동 등) 실었으면 재빌드 없이 완료 표시. 성공
            # (basis==오늘)일 때만 완료로 찍어 → PDF 가 늦으면 다음 분에 재시도한다.
            if (
                _kst_minutes_now() >= MORNING_RELOAD_MIN
                and getattr(self, "_morning_reload_date", "") != current
            ):
                if getattr(self, "_basket_basis", "") == current:
                    self._morning_reload_date = current
                    continue
                _log(
                    f"morning PDF reload {current}: 현재 basis="
                    f"{getattr(self, '_basket_basis', '?')} → 오늘 PDF 로 재빌드 시도"
                )
                try:
                    self._init_clients()
                    await self._build_engine(current)
                    if getattr(self, "_basket_basis", "") == current:
                        self._morning_reload_date = current
                        _log(f"morning PDF reload 완료 basis={self._basket_basis}")
                    else:
                        _log(
                            "morning PDF reload: 오늘 PDF 아직 없음"
                            f"(basis={getattr(self, '_basket_basis', '?')}) — 다음 분 재시도"
                        )
                except Exception as exc:  # noqa: BLE001 - keep last-good engine
                    _log(f"morning PDF reload failed: {exc!r}; keeping previous engine")

    async def _lp_eval_loop(self) -> None:
        """LP 평가 표본 — 60초마다 현재 호가에서 ACE 9종의 인정 스프레드 틱을
        basis(lp/total) 2종으로 누적한다. LP 의무시간(09:05~15:20 KST)·CHECK 신선할
        때만 표본하며, lp_eval.db(.cache) 에 영속(재기동에도 유지). 표본이 실제로
        누적된 분에는 그날치 통계를 S: 출력폴더에 저장한다(JSON + 마스터 CSV) —
        15:20 마지막 표본에서 그날 최종본이 된다."""
        from collector import lp_eval as _lpe
        while not self.stop_event.is_set():
            if await self._sleep_or_stop(LP_EVAL_SAMPLE_S):
                return
            try:
                n = _lpe.sample_once(self.state.hoga(), snapshot=self.state.snapshot())
                if n:
                    _lpe.write_daily_snapshot(self.etf_names)
            except Exception as exc:  # noqa: BLE001 - 표본 실패는 그 분만 건너뜀
                _log(f"lp-eval sample failed: {exc!r}")

    async def _lp_eval_daily_loop(self) -> None:
        """LP 평가 일일 스케줄 (2026-08-10 신설).

        (1) 자정(KST 날짜가 바뀔 때) 오늘이 한국 증시 개장일인지 판정해 로그로 남긴다.
            실제 차단은 lp_eval.sample_once 가 표본마다 다시 확인하므로, 이 로그는
            '오늘 왜 안 쌓이는지'를 사람이 바로 알 수 있게 하는 용도다(재기동에도
            판정이 유실되지 않는 게 이 이중 구조의 요점).
        (2) 16:30 KST 에 전 거래일 요약을 마스터 CSV 로 이관한다.
        """
        from collector import lp_eval as _lpe

        judged_date = ""
        exported_date = ""
        while not self.stop_event.is_set():
            current = legacy_inputs.kst_today()
            if current != judged_date:
                judged_date = current
                try:
                    is_open, reason = _lpe.trading_day_status()
                    _log(f"lp-eval {reason} → 표본 {'수집' if is_open else '중지'}")
                except Exception as exc:  # noqa: BLE001
                    _log(f"lp-eval trading-day check failed: {exc!r}")
            if _kst_minutes_now() >= LP_EVAL_EXPORT_MIN and exported_date != current:
                try:
                    if _lpe.export_history_csv(self.etf_names):
                        exported_date = current
                        _log(f"lp-eval history CSV 이관 완료 ({current})")
                    else:
                        # 마운트 부재(로컬 개발) — 매분 재시도하지 않도록 오늘은 종료.
                        exported_date = current
                        _log("lp-eval history CSV skip: 출력 폴더 없음")
                except Exception as exc:  # noqa: BLE001 - 다음 분에 재시도
                    _log(f"lp-eval history export failed: {exc!r}")
            if await self._sleep_or_stop(LP_EVAL_DAILY_CHECK_S):
                return

    async def _telegram_news_loop(self) -> None:
        """[뉴스 모니터링 · 텔레그램] 상류 집계 JSON(2시간 간격 풀링) 판독.

        SMB 왕복이라 executor 로 내보내 이벤트 루프를 막지 않는다. 기동 직후 1회를
        먼저 돌려 화면이 첫 폴링에서 바로 채워지게 한다.
        """
        from collector import telegram_news as _tn

        news = _tn.instance()
        if not news.available():
            _log(f"telegram-news: {_tn.ANALYSIS_PATH} 마운트 없음 — 루프 미가동")
            return
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            try:
                await loop.run_in_executor(None, news.refresh)
            except Exception as exc:  # noqa: BLE001 - 한 사이클 실패는 직전 카드 유지
                _log(f"telegram-news refresh failed: {exc!r}")
            if await self._sleep_or_stop(TELEGRAM_NEWS_REFRESH_S):
                return

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

        @app.get("/index-window")
        def index_window():
            # 지수 롤링 60분 변동폭(max−min) — INDEX_MONITOR.db(:ro) 판독. 별도 state
            # 없이 요청 시 계산(캐시 복사는 소스 mtime 변화 시에만). 실패해도 500 금지.
            from collector import index_window as _iw

            try:
                return JSONResponse(_iw.build_index_window())
            except Exception as exc:  # noqa: BLE001
                _log(f"index-window failed: {exc!r}")
                return JSONResponse({"detail": "index-window error"}, status_code=503)

        @app.get("/index-alerts")
        def index_alerts():
            # 지수 급등락 하루 알림 로그(서버측 계산·보관). 모든 클라이언트가 동일 목록.
            from collector import index_window as _iw

            try:
                return JSONResponse(_iw.build_index_alerts())
            except Exception as exc:  # noqa: BLE001
                _log(f"index-alerts failed: {exc!r}")
                return JSONResponse({"detail": "index-alerts error"}, status_code=503)

        @app.get("/lp-eval")
        def lp_eval(date: str | None = None, basis: str | None = None):
            # LP 평가 — ACE 9종 인정 스프레드 틱 체류시간(분) 분포/통계. lp_eval.db 판독.
            from collector import lp_eval as _lpe

            try:
                return JSONResponse(_lpe.build_lp_eval(date, self.etf_names, basis))
            except Exception as exc:  # noqa: BLE001
                _log(f"lp-eval failed: {exc!r}")
                return JSONResponse({"detail": "lp-eval error"}, status_code=503)

        @app.get("/lp-eval-ts")
        def lp_eval_ts(date: str | None = None, basis: str | None = None):
            # LP 평가 인정 스프레드 틱 시계열(분봉) — ACE 종목별 (ts, tick). 차트용.
            from collector import lp_eval as _lpe

            try:
                return JSONResponse(_lpe.build_lp_eval_ts(date, self.etf_names, basis))
            except Exception as exc:  # noqa: BLE001
                _log(f"lp-eval-ts failed: {exc!r}")
                return JSONResponse({"detail": "lp-eval-ts error"}, status_code=503)

        @app.get("/index-strip")
        def index_strip():
            # [종목 모니터] 상단 지수 스트립 — INDEX_MONITOR.db 판독.
            #   대상 5종은 index_window.STRIP_CODES (알림용 DEFAULT_CODES 와 별개).
            from collector import index_window as _iw

            try:
                return JSONResponse(_iw.build_index_strip())
            except Exception as exc:  # noqa: BLE001
                _log(f"index-strip failed: {exc!r}")
                return JSONResponse({"detail": "index-strip error"}, status_code=503)

        @app.get("/stock-monitor")
        def stock_monitor(day: str | None = None, sort: str = "value",
                          limit: int = 30):
            # [종목 모니터] KOSPI200 분봉 기반 급등락·이상현상. Toss_분봉_모니터 DB 판독.
            #   sort: value(거래대금) | change(등락률) | sigma(자기 변동성 대비)
            try:
                return JSONResponse(
                    self.stock_monitor.build(day=day, sort=sort, limit=limit))
            except Exception as exc:  # noqa: BLE001
                _log(f"stock-monitor failed: {exc!r}")
                return JSONResponse({"detail": "stock-monitor error"}, status_code=503)

        @app.get("/wrap-performance")
        def wrap_performance():
            # 성과 비교(track record) 누적수익률 시계열. 소스 xlsx mtime 캐시.
            if self.wrap is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            payload = self.wrap.build_performance()
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            return JSONResponse(payload)

        @app.get("/wrap-rebalancing")
        def wrap_rebalancing():
            # 리밸런싱 이력(track record) 시점별 편입 구성. 소스 xlsx mtime 캐시.
            if self.wrap is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            payload = self.wrap.build_rebalancing()
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            return JSONResponse(payload)

        # ── GURU[13F] track record ──────────────────────────────────────
        # 무거운 교차거장 집계(consensus/turnover)는 백그라운드 사전계산분(state)만 서빙,
        # 단일거장(portfolio/changes/timeline)은 요청 시 로컬 .cache copy 경량 쿼리.
        # 준비 전(첫 clean 복사 이전)은 503 not-ready. ETag = f(dbVersion, endpoint, params).
        guru = self.guru13f

        def _guru_serve(request: Request, produce, *etag_parts):
            # produce() 는 payload 를 만드는 thunk. 요청경로 쿼리 예외도 500 이 아니라
            # 503(not ready)으로 격하 — collector 는 이 페이지 때문에 절대 500 을 내지 않는다.
            try:
                payload = produce()
            except Exception as exc:  # noqa: BLE001
                _log(f"guru-13f serve failed: {exc!r}")
                payload = None
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            etag = guru.etag(*etag_parts)
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers={"ETag": etag})
            return JSONResponse(payload, headers={"ETag": etag})

        @app.get("/guru-13f/roster")
        def guru_roster(request: Request):
            return _guru_serve(request, lambda: guru.roster(), "roster")

        @app.get("/guru-13f/portfolio")
        def guru_portfolio(request: Request, cik: str, period: str):
            return _guru_serve(request, lambda: guru.portfolio(cik, period), "portfolio", cik, period)

        @app.get("/guru-13f/changes")
        def guru_changes(request: Request, cik: str, period: str):
            return _guru_serve(request, lambda: guru.changes(cik, period), "changes", cik, period)

        @app.get("/guru-13f/timeline")
        def guru_timeline(request: Request, cik: str):
            return _guru_serve(request, lambda: guru.timeline(cik), "timeline", cik)

        @app.get("/guru-13f/consensus")
        def guru_consensus_ep(request: Request, period: str | None = None):
            return _guru_serve(request, lambda: guru.consensus(period), "consensus", period or "latest")

        # ── 변동 분석: 동시 리밸런싱 / 편입·방출 / 섹터 ────────────────
        # view 생략 시 세 뷰를 한 번에. 사전계산분이라 응답은 가볍다.
        @app.get("/guru-13f/flows")
        def guru_flows_ep(request: Request, view: str | None = None):
            return _guru_serve(request, lambda: guru.flows(view), "flows", view or "all")

        @app.get("/guru-13f/turnover")
        def guru_turnover_ep(request: Request, period: str | None = None):
            return _guru_serve(request, lambda: guru.turnover(period), "turnover", period or "latest")

        # ── [매크로] 물가·고용·유동성 패널 ──────────────────────────────
        # S: 매크로모니터가 macro.db 에서 계산해 구운 macro_panels.json 만 읽는다
        # (DB 자체는 세부품목까지 담아 300MB 라 컨테이너로 복사하지 않는다).
        @app.get("/macro/panels")
        def macro_panels_ep(request: Request):
            from collector import macro_monitor as _mm
            payload = _mm.panels()
            if not payload:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            tag = _mm.etag()
            if request.headers.get("if-none-match") == tag:
                return Response(status_code=304, headers={"ETag": tag})
            return JSONResponse(payload, headers={"ETag": tag})

        # ── [회의] 회의자료 파일 탐색기 (PoC) ───────────────────────────
        # S:\GE\_Team\07_회의자료 (:ro 마운트) 를 루트로 폴더 탐색 + HTML 원문 반환.
        @app.get("/meeting/list")
        def meeting_list(path: str = ""):
            from collector import meeting as _mt
            try:
                data = _mt.list_dir(path)
            except Exception as exc:  # noqa: BLE001
                _log(f"meeting/list failed: {exc!r}")
                return JSONResponse({"detail": "meeting error"}, status_code=503)
            if data is None:
                return JSONResponse({"detail": "not found"}, status_code=404)
            return JSONResponse(data)

        @app.get("/meeting/file")
        def meeting_file(path: str):
            from collector import meeting as _mt
            try:
                html = _mt.read_file(path)
            except Exception as exc:  # noqa: BLE001
                _log(f"meeting/file failed: {exc!r}")
                return JSONResponse({"detail": "meeting error"}, status_code=503)
            if html is None:
                return JSONResponse({"detail": "not found"}, status_code=404)
            return JSONResponse({"path": path, "html": html})

        # ── [뉴스 모니터링 · 텔레그램] 실시간 카드 피드 ─────────────────
        # 방별 raw CSV(:ro) 를 증분 tail 로 읽어 만든 매크로/산업/종목 × 5장.
        # 백그라운드 루프(_telegram_news_loop)가 만들어 둔 것만 내준다 — 요청
        # 경로에 SMB 왕복이 끼면 폴링 화면이 통째로 느려진다.
        @app.get("/telegram-news")
        def telegram_news(request: Request):
            from collector import telegram_news as _tn

            payload, etag = _tn.instance().serve()
            if payload is None:
                return JSONResponse({"detail": "not ready"}, status_code=503)
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers={"ETag": etag})
            return JSONResponse(payload, headers={"ETag": etag})

        # ── [성과보고] 데일리·위클리 성과 브리프 ─────────────────────────
        # S:\GE\Wonjae\07_회의자료\정기미팅 (:ro) 의 성과보고 JSON 을 요일 규칙
        # (월=위클리 / 화~금=데일리)에 맞춰 골라 서빙. 오늘 작성분이 없으면 pending.
        @app.get("/perf-brief")
        def perf_brief():
            from collector import perf_brief as _pb
            try:
                return JSONResponse(_pb.build())
            except Exception as exc:  # noqa: BLE001
                _log(f"perf-brief failed: {exc!r}")
                return JSONResponse({"detail": "perf-brief error"}, status_code=503)

        # [분석 시작] — 운용역 소스 엑셀을 그 자리에서 읽어 정량 분석을 만든다.
        # 느린 경로(SMB xlsx 파싱 수 초)라 폴링이 아니라 버튼 요청에만 돈다.
        @app.get("/perf-brief/analyze")
        def perf_brief_analyze(mode: str = "daily"):
            from collector import perf_analyze as _pa
            try:
                return JSONResponse(_pa.analyze(mode))
            except FileNotFoundError as exc:
                return JSONResponse({"detail": f"소스 엑셀 없음: {exc}"}, status_code=404)
            except ValueError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                _log(f"perf-brief/analyze failed: {exc!r}")
                return JSONResponse({"detail": "analyze error"}, status_code=503)

        # [보고서 생성] — Windows 러너(claude 서브프로세스) 위임. 컨테이너에는 claude 가
        # 없고 인증도 구독 OAuth 라 옮길 수 없어, 계산만 여기서 하고 서사는 러너가 만든다.
        # 러너가 저장한 JSON 은 기존 /perf-brief 배선이 그대로 집어 올린다.
        def _runner(path: str, method: str = "GET"):
            import urllib.error
            import urllib.request
            base = os.environ.get("PERF_BRIEF_RUNNER_URL", "http://host.docker.internal:8010")
            token = os.environ.get("PERF_BRIEF_RUNNER_TOKEN", "").strip()
            req = urllib.request.Request(f"{base}{path}", method=method,
                                         data=b"" if method == "POST" else None)
            if token:
                req.add_header("X-Runner-Token", token)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return JSONResponse(json.loads(r.read().decode("utf-8")), status_code=r.status)
            except urllib.error.HTTPError as exc:
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                except Exception:  # noqa: BLE001
                    body = {"detail": f"runner error {exc.code}"}
                return JSONResponse(body, status_code=exc.code)
            except Exception as exc:  # noqa: BLE001
                _log(f"perf-brief runner unreachable: {exc!r}")
                return JSONResponse(
                    {"detail": "러너에 연결할 수 없습니다 — 성과보고_러너_시작.bat 이 켜져 있는지 확인해 주세요"},
                    status_code=503,
                )

        @app.post("/perf-brief/generate")
        def perf_brief_generate(mode: str = "daily"):
            return _runner(f"/generate?mode={mode}", method="POST")

        @app.get("/perf-brief/generate/status")
        def perf_brief_generate_status():
            return _runner("/status")

        # [성과보고 HTML] S: 의 bat 산출물. 계산·서사가 전부 S: 로 넘어간 구조라
        # collector 는 파일명 규약으로 오늘치를 고르고 원문만 넘긴다(회의 탭과 동일).
        @app.get("/perf-report")
        def perf_report():
            from collector import perf_report as _pr
            try:
                return JSONResponse(_pr.build())
            except Exception as exc:  # noqa: BLE001
                _log(f"perf-report failed: {exc!r}")
                return JSONResponse({"detail": "perf-report error"}, status_code=503)

        @app.get("/perf-report/file")
        def perf_report_file(path: str = ""):
            from collector import perf_report as _pr
            html = _pr.read_html(path)
            if html is None:
                return JSONResponse({"detail": "not found"}, status_code=404)
            return JSONResponse({"path": path, "html": html})

        # [성과보고 생성] 사람이 돌리던 bat 을 대신한다. n8n 이 아침에 여러 번 부르고,
        # 실행 여부는 시각이 아니라 Price 시트가 늘었는지로 정한다(perf_generate 참조).
        # 멱등이라 몇 번을 불러도 기준일당 한 번만 만든다. force=1 은 수동 재생성용.
        # SMB + openpyxl 이라 수십 초가 걸린다. 호출부 타임아웃을 넉넉히 잡을 것.
        @app.post("/perf-report/generate")
        def perf_report_generate(scope: str = "일간", force: bool = False):
            from collector import perf_generate as _pg
            try:
                return JSONResponse(_pg.generate(scope=scope, force=force))
            except ValueError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                _log(f"perf-report/generate failed: {exc!r}")
                return JSONResponse({"detail": "perf-report generate error"},
                                    status_code=503)

        # [누적 수익률 비교] S: 의 build_funds.py 가 만든 표준 시계열 JSON. 펀드가 몇 개로
        # 늘어나든 이 엔드포인트는 그대로다 — 엑셀 레이아웃 편차는 전부 S: 에서 흡수한다.
        @app.get("/fund-series")
        def fund_series():
            from collector import fund_series as _fs
            try:
                return JSONResponse(_fs.build())
            except Exception as exc:  # noqa: BLE001
                _log(f"fund-series failed: {exc!r}")
                return JSONResponse({"detail": "fund-series error"}, status_code=503)

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
            asyncio.create_task(self.guru13f.loop(self.stop_event)),
            asyncio.create_task(self._twse_loop()),
            asyncio.create_task(self._ws_loop()),
            asyncio.create_task(self._rollover_loop()),
            asyncio.create_task(self._lp_eval_loop()),
            asyncio.create_task(self._lp_eval_daily_loop()),
            asyncio.create_task(self._telegram_news_loop()),
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
