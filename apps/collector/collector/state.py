"""In-memory snapshot store for the collector.

Holds the latest per-ETF summary rows, the FX map, and per-input staleness
ages. Everything is fail-stale: a source that fails simply stops bumping its
``*_updated`` timestamp, so its age grows while the last-good value is served.
Thread-safe (compute runs in an executor thread; the API reads from the event
loop thread).
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, time as dt_time, timedelta, timezone

_KST = timezone(timedelta(hours=9))

_KR_OPEN = dt_time(9, 0)
_KR_CLOSE = dt_time(15, 30)


def _now_epoch() -> float:
    return time.time()


def now_kst_string() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")


def json_safe(value):
    """Coerce NaN/inf and numpy scalars to plain JSON-safe values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int,)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def kr_market_status(now: datetime | None = None) -> str:
    """Coarse KRX regular-session status (no holiday calendar in Phase-1)."""
    current = (now or datetime.now(_KST)).astimezone(_KST)
    if current.weekday() >= 5:
        return "CLOSED_WEEKEND"
    if _KR_OPEN <= current.time() < _KR_CLOSE:
        return "REGULAR"
    return "CLOSED"


def _age(reference: float | None, now: float) -> float | None:
    if reference is None:
        return None
    return round(max(0.0, now - reference), 1)


def _parse_iso_epoch(raw: str | None) -> float | None:
    """Parse an ISO8601 timestamp (e.g. ``2026-07-16T10:06:58+09:00``) to epoch
    seconds. Naive timestamps are assumed KST. Returns None on empty/unparsable
    input so downstream ages stay null-safe."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    return dt.timestamp()


class SnapshotState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_date = ""
        self._etfs: list[dict] = []
        self._fx: dict[str, float] = {}
        self._sums: dict | None = None
        self._generated_at: str | None = None
        self._timestamp_ms = 0
        # per-source last-success epoch seconds
        self._fx_ts: float | None = None
        self._price_ts: float | None = None
        self._twse_ts: float | None = None
        self._compute_ts: float | None = None
        # basket provenance
        self._basket_basis_date = ""
        self._basket_source = ""
        # KIS token gate
        self._token_valid = False
        self._token_expires_at: float | None = None
        self._setup_done = False
        # KIS realtime WebSocket lane
        self._ws_connected = False
        self._ws_subscribed_count = 0
        self._ws_tick_ts: float | None = None
        self._ws_rotation: dict | None = None
        # KR ETF own-quote lane (domestic REST: 현재가/등락률)
        self._etf_quotes: dict[str, dict] = {}
        self._etf_quote_ts: float | None = None
        # per-ETF components payload (구성종목 모달 / 무버 티커)
        self._components: dict | None = None
        self._components_ts_ms = 0
        # WRAP 포트폴리오 실시간 수익률 payload
        self._wrap: dict | None = None
        self._wrap_ts_ms = 0
        # CHECK-agent 호가(orderbook) envelope (remote agent → api → collector)
        self._hoga: dict | None = None
        self._hoga_source_timestamp: str | None = None
        self._hoga_sent_at: str | None = None
        self._hoga_seq: int | None = None
        self._hoga_received_ts: float | None = None

    # ── writers ────────────────────────────────────────────────────────
    def set_run_date(self, run_date: str) -> None:
        with self._lock:
            self._run_date = run_date

    def set_basket(self, basis_date: str, source: str) -> None:
        with self._lock:
            self._basket_basis_date = basis_date
            self._basket_source = source

    def set_token(self, valid: bool, expires_at: float | None) -> None:
        with self._lock:
            self._token_valid = bool(valid)
            self._token_expires_at = expires_at

    def mark_fx(self, ts: float | None = None) -> None:
        with self._lock:
            self._fx_ts = ts if ts is not None else _now_epoch()

    def mark_price(self, ts: float | None = None) -> None:
        with self._lock:
            self._price_ts = ts if ts is not None else _now_epoch()

    def mark_twse(self, ts: float | None = None) -> None:
        with self._lock:
            self._twse_ts = ts if ts is not None else _now_epoch()

    def set_ws_connected(self, connected: bool) -> None:
        with self._lock:
            self._ws_connected = bool(connected)

    def set_ws_subscribed(self, count: int) -> None:
        with self._lock:
            self._ws_subscribed_count = int(count)

    def mark_ws_tick(self, ts: float | None = None) -> None:
        with self._lock:
            self._ws_tick_ts = ts if ts is not None else _now_epoch()

    def set_ws_rotation(self, batch_count: int, rotation_seconds: float | None) -> None:
        with self._lock:
            self._ws_rotation = {
                "batch_count": int(batch_count),
                "rotation_seconds": rotation_seconds,
            }

    def set_etf_quotes(self, quotes: dict[str, dict]) -> None:
        with self._lock:
            self._etf_quotes = dict(quotes)
            self._etf_quote_ts = _now_epoch()

    def update_components(self, payload: dict) -> None:
        with self._lock:
            self._components = payload
            self._components_ts_ms = int(time.time() * 1000)

    def update_hoga(self, envelope: dict) -> bool:
        """Store a CHECK-agent 호가 envelope. Returns False (ignored) when the
        incoming seq regresses below the stored seq — out-of-order resends are
        dropped so the last-good orderbook is preserved."""
        seq = envelope.get("seq")
        with self._lock:
            if seq is not None and self._hoga_seq is not None and seq < self._hoga_seq:
                return False
            self._hoga = envelope.get("payload")
            self._hoga_source_timestamp = envelope.get("source_timestamp")
            self._hoga_sent_at = envelope.get("sent_at")
            self._hoga_seq = seq
            self._hoga_received_ts = _now_epoch()
            return True

    def update_etfs(
        self, rows: list[dict], fx: dict, generated_at: str, sums: dict | None = None
    ) -> None:
        with self._lock:
            self._etfs = rows
            self._sums = sums
            self._fx = {str(k): json_safe(v) for k, v in (fx or {}).items()}
            self._generated_at = generated_at
            self._timestamp_ms = int(time.time() * 1000)
            self._compute_ts = _now_epoch()
            self._setup_done = True

    # ── readers ────────────────────────────────────────────────────────
    def _staleness_locked(self, now: float) -> dict:
        return {
            "fx_age_s": _age(self._fx_ts, now),
            "price_age_s": _age(self._price_ts, now),
            "twse_age_s": _age(self._twse_ts, now),
            "kr_etf_age_s": _age(self._etf_quote_ts, now),
            "compute_age_s": _age(self._compute_ts, now),
            "basket_basis_date": self._basket_basis_date,
            "basket_source": self._basket_source,
            "token_valid": self._token_valid,
            "token_ttl_s": (
                round(self._token_expires_at - now, 1)
                if self._token_expires_at is not None
                else None
            ),
            "ws_connected": self._ws_connected,
            "ws_subscribed_count": self._ws_subscribed_count,
            "ws_last_tick_age_s": _age(self._ws_tick_ts, now),
            "ws_rotation": dict(self._ws_rotation) if self._ws_rotation else None,
            "hoga_connected": (
                self._hoga_received_ts is not None and (now - self._hoga_received_ts) < 15.0
            ),
            "hoga_last_received_age_s": _age(self._hoga_received_ts, now),
            "hoga_source_age_s": _age(_parse_iso_epoch(self._hoga_source_timestamp), now),
        }

    def snapshot(self) -> dict:
        now = _now_epoch()
        with self._lock:
            return {
                "date": self._run_date,
                "generated_at": self._generated_at,
                "timestamp": self._timestamp_ms,
                "market_status": kr_market_status(),
                "setup_done": self._setup_done,
                "etf_count": len(self._etfs),
                "etfs": list(self._etfs),
                "fx": dict(self._fx),
                "sums": dict(self._sums) if self._sums else None,
                "staleness": self._staleness_locked(now),
            }

    def health(self) -> dict:
        now = _now_epoch()
        with self._lock:
            return {
                "status": "ok" if self._setup_done else "starting",
                "date": self._run_date,
                "generated_at": self._generated_at,
                "etf_count": len(self._etfs),
                "staleness": self._staleness_locked(now),
            }

    def etag(self) -> str:
        with self._lock:
            return f'"{self._timestamp_ms:x}"'

    def etf_quotes(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._etf_quotes)

    def components(self) -> dict | None:
        with self._lock:
            return self._components

    def components_etag(self) -> str:
        with self._lock:
            return f'"c{self._components_ts_ms:x}"'

    def update_wrap(self, payload: dict) -> None:
        with self._lock:
            self._wrap = payload
            self._wrap_ts_ms = int(time.time() * 1000)

    def wrap(self) -> dict | None:
        with self._lock:
            return self._wrap

    def wrap_etag(self) -> str:
        with self._lock:
            return f'"w{self._wrap_ts_ms:x}"'

    def hoga(self) -> dict:
        """Last CHECK-agent 호가 envelope plus freshness ages (null-safe before any
        envelope has been received)."""
        now = _now_epoch()
        with self._lock:
            source_epoch = _parse_iso_epoch(self._hoga_source_timestamp)
            return {
                "payload": self._hoga,
                "source_timestamp": self._hoga_source_timestamp,
                "sent_at": self._hoga_sent_at,
                "seq": self._hoga_seq,
                "hoga_last_received_age_s": _age(self._hoga_received_ts, now),
                "hoga_source_age_s": _age(source_epoch, now),
            }
