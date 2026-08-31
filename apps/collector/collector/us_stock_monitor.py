"""[종목 모니터 · 미장] — 미국 보유종목 실시간 체결 테이블.

데이터 원천: S:\\GE\\raw\\data\\Toss_분봉_모니터\\output\\미장_실시간체결가.db
  · trades(symbol, ts, price, volume, collected_at) — 토스 WS `trade:us` 틱 append
  · latest(symbol PK, price, volume, ts, ...)       — 종목별 최신 체결 업서트
  · status(key, value)                              — 수집기 하트비트

KR lane(stock_monitor.py)과 **다른 판독 방식**을 쓴다 — 저쪽은 1분마다 통으로
갱신되는 분봉 DB 라 스냅샷 복사가 맞지만, 이 DB 는 1초마다 커밋되는 틱로그
(180MB+, 하루 ~180만 행)라 복사 게이트(mtime/size 안정)가 영영 안 잡히고 복사
자체도 수십 초다. 대신 상류가 정한 소비 계약을 따른다(us_realtime.py 문서):
journal_mode=DELETE + 단일 쓰기 스레드 = **mode=ro 직독** 허용, 신선도는
status.last_flush_at. 요청 경로에서 직접 읽지 않고 백그라운드 스레드가
rowid 커서로 **증분**만 당겨 메모리 집계를 유지한다 — 배치를 잘게 끊어
(≤5만 행/문장) 읽기 락이 상류의 1초 flush 를 굶기지 않게 한다.

세션 경계는 ET 로 잰다(토스 미장은 오버나이트 포함 사실상 24시간이라 KST 달력일이
무의미하다): 거래일 = [전일 20:00 ET(오버나이트 개시) → 당일 20:00 ET). 등락률
앵커는 그 직전 정규장 마감(16:00 ET) 이전 마지막 체결 — 공식 전일종가의 체결
근사다(주말 뒤에는 금요일 애프터마켓 마지막 체결이 잡히는 오차를 감수한다).

⚠️거래대금·거래량은 **수집 표본**이다: 210>200(WS 구독 한도)이라 수집기가 30초
배치 로테이션을 돌아 종목당 시간의 절반만 틱이 잡힌다. 절대값은 절반 남짓
과소지만 전 종목이 같은 비율로 표본이라 상대 순위는 유효하다 — payload 에 적는다.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
ET = ZoneInfo("America/New_York")

SRC_DIR = os.environ.get("STOCK_MONITOR_SRC_DIR", "/srv/legacy/toss_minute")
DB_PATH = os.path.join(SRC_DIR, "미장_실시간체결가.db")

SESSION_START_H_ET = 20   # 오버나이트(Blue Ocean) 개시 = 전일 애프터마켓 종료
REGULAR_CLOSE_H_ET = 16   # 정규장 마감 — 등락률 앵커 경계
POLL_S = 15               # 증분 판독 주기 (수집기 flush 는 1초 — 화면 폴링은 30초)
IDLE_AFTER_S = 180        # 이 시간 요청이 없으면 판독을 쉰다(안 보는 화면에 SMB 낭비 금지)
SCAN_BATCH = 50_000       # 문장당 행 상한 — 읽기 락 시간을 상류 busy_timeout(5s) 아래로
MAX_BATCHES = 40          # 주기당 상한(웜업 폭주 가드) — 다음 주기가 이어서 당긴다
TOP_N = 30


def _log(msg: str) -> None:
    print(f"[us-stock-monitor] {msg}", flush=True)


def _ro_uri(path: str) -> str:
    """sqlite URI (mode=ro). 한글 파일명·윈도우 경로(로컬 테스트) 둘 다 통과."""
    p = quote(path.replace("\\", "/"))
    if not p.startswith("/"):
        p = "/" + p
    return f"file:{p}?mode=ro"


def session_bounds(now_et: datetime | None = None) -> tuple[str, str, str]:
    """(세션 시작 KST, 앵커 경계 KST, 거래일 ET) — ts 문자열 비교용.

    세션 시작 = 직전 20:00 ET, 앵커 경계 = 같은 날 16:00 ET(직전 정규장 마감),
    거래일 = 시작 다음날의 ET 달력일(화 20:00 개시 사이클의 정규장은 수요일).
    """
    now_et = now_et or datetime.now(ET)
    start_et = now_et.replace(hour=SESSION_START_H_ET, minute=0, second=0,
                              microsecond=0)
    if now_et.hour < SESSION_START_H_ET:
        start_et -= timedelta(days=1)
    anchor_et = start_et.replace(hour=REGULAR_CLOSE_H_ET)
    day = (start_et + timedelta(days=1)).date().isoformat()
    fmt = "%Y-%m-%d %H:%M:%S"
    return (start_et.astimezone(KST).strftime(fmt),
            anchor_et.astimezone(KST).strftime(fmt), day)


class UsStockMonitor:
    """rowid 커서 증분 집계를 백그라운드로 유지하고, build() 는 스냅샷만 접는다."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self._lock = threading.Lock()
        self._snap: dict | None = None       # cycle 이 완성본으로 교체(reference swap)
        self._thread: threading.Thread | None = None
        self._last_req = 0.0
        self._last_err: str | None = None
        # ── 세션 상태 (cycle 스레드 단독 소유 — lock 불필요) ──
        self._ws: str | None = None          # 현재 세션 시작(KST 문자열)
        self._anchor_b: str = ""
        self._day: str = ""
        self._cursor = 0                     # 마지막 소비 rowid
        self._agg: dict[str, list] = {}      # symbol → [vol, value]
        self._anchors: dict[str, float | None] = {}

    # --- 판독 사이클 (백그라운드 스레드) ------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(_ro_uri(self.db_path), uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _bisect_start(self, con: sqlite3.Connection, ws: str) -> int:
        """세션 시작 직전 rowid — append-only 라 rowid 가 사실상 시간순이다.
        초 단위 역전은 scan 의 ts 필터가 거르므로 경계가 몇 행 어긋나도 무해."""
        hi = con.execute("SELECT MAX(rowid) FROM trades").fetchone()[0] or 0
        lo = 1
        while lo < hi:
            mid = (lo + hi) // 2
            row = con.execute(
                "SELECT ts FROM trades WHERE rowid >= ? ORDER BY rowid LIMIT 1",
                (mid,)).fetchone()
            if row is None or row[0] >= ws:
                hi = mid
            else:
                lo = mid + 1
        return max(lo - 1, 0)

    def _cycle(self) -> None:
        con = self._connect()
        try:
            ws, anchor_b, day = session_bounds()
            if ws != self._ws:                       # 세션 롤오버(또는 첫 판독)
                self._ws, self._anchor_b, self._day = ws, anchor_b, day
                self._agg = {}
                self._anchors = {}
                self._cursor = self._bisect_start(con, ws)
                _log(f"세션 리셋 — 거래일 {day}, 시작 {ws}, cursor {self._cursor}")

            caught_up = False
            for _ in range(MAX_BATCHES):
                rows = con.execute(
                    "SELECT rowid, symbol, ts, price, volume FROM trades "
                    "WHERE rowid > ? ORDER BY rowid LIMIT ?",
                    (self._cursor, SCAN_BATCH)).fetchall()
                if rows:
                    self._cursor = rows[-1][0]
                    for _rid, sym, ts, price, vol in rows:
                        if ts < ws or not price or price <= 0:
                            continue
                        a = self._agg.setdefault(sym, [0, 0.0])
                        a[0] += vol or 0
                        a[1] += (vol or 0) * price
                if len(rows) < SCAN_BATCH:
                    caught_up = True
                    break
                time.sleep(0.2)                      # 상류 1초 flush 에 숨통
            if not caught_up:
                _log("웜업 계속 — 이번 주기 배치 상한 도달, 다음 주기에 이어감")
                return                               # 반쪽 집계는 게시하지 않는다

            latest = con.execute(
                "SELECT symbol, price, volume, ts FROM latest").fetchall()
            # 앵커 — 세션 이전 과거는 불변이라 심볼당 1회만 찾는다(없으면 None 고정).
            for sym, *_ in latest:
                if sym not in self._anchors:
                    row = con.execute(
                        "SELECT price FROM trades WHERE symbol = ? AND ts < ? "
                        "ORDER BY ts DESC LIMIT 1", (sym, self._anchor_b)).fetchone()
                    self._anchors[sym] = row[0] if row else None
            status = dict(con.execute("SELECT key, value FROM status"))
        finally:
            con.close()

        out = []
        for sym, price, _vol, ts in latest:
            if not ts or ts < ws:                    # 이번 세션 체결 없는 종목은 제외
                continue
            anchor = self._anchors.get(sym)
            vol_val = self._agg.get(sym)
            out.append({
                "symbol": sym,
                "name": sym,                          # 한글명 원천 없음 — 심볼 그대로
                "price": price,
                "change_pct": ((price / anchor - 1) * 100
                               if anchor and price else None),
                "value": vol_val[1] if vol_val else None,
                "volume": vol_val[0] if vol_val else None,
                "market_cap": None,                   # KR 표와 같은 자리 — 원천 없음
                "industry": None,
                "issue": None,
                "cap_rank": None,
                "change_sigma": None,                 # 통계 원천 없음(KR 전용)
                "volume_z": None,
            })
        snap = {
            "rows": out,
            # 세션 내 마지막 체결 시각 — KR asof(마지막 봉 시각)와 같은 자리.
            "asof": max((x[3] for x in latest if x[3] and x[3] >= ws), default=None),
            "day": self._day,
            "feed_at": status.get("last_flush_at"),
        }
        with self._lock:
            self._snap = snap
            self._last_err = None

    def _loop(self) -> None:
        last_cycle = 0.0
        while True:
            active = (time.time() - self._last_req) < IDLE_AFTER_S
            if active and time.time() - last_cycle >= POLL_S:
                try:
                    self._cycle()
                except Exception as ex:              # noqa: BLE001 — 다음 주기 재시도
                    _log(f"cycle 실패(스냅샷은 마지막 정상본 유지): {ex!r}")
                    with self._lock:
                        self._last_err = repr(ex)
                last_cycle = time.time()
            time.sleep(2)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._loop, daemon=True, name="us-stock-monitor")
                self._thread.start()

    # --- payload ------------------------------------------------------
    def build(self, day: str | None = None, sort: str = "value",
              limit: int = TOP_N) -> dict:
        """화면 테이블 한 장 — KR build() 와 같은 모양. day 는 받되 무시한다
        (세션 경계가 ET 라 과거일 조회는 틱로그 재스캔 문제로 v1 범위 밖)."""
        self._last_req = time.time()
        self._ensure_thread()
        with self._lock:
            snap = self._snap
            err = self._last_err
        if snap is None:
            note = ("미장 틱 스냅샷 웜업 중 — 잠시 후 갱신됩니다"
                    if err is None else "미장 DB 를 아직 못 읽었다 — 재시도 중")
            return {"asof": None, "market": "us", "rows": [], "note": note}

        out = [dict(r) for r in snap["rows"]]        # rank 를 새로 매기므로 사본
        key = {"value": lambda x: -(x["value"] or 0),
               "change": lambda x: -(x["change_pct"] or 0),
               "sigma": lambda x: -abs(x["change_sigma"] or 0)}.get(sort)
        if key:
            out.sort(key=key)
        for i, x in enumerate(out[:limit], 1):
            x["rank"] = i

        payload = {
            "asof": snap["asof"],
            "day": snap["day"],
            "sort": sort,
            "market": "us",
            "universe": len(out),
            "feed_at": snap["feed_at"],
            "value_basis": ("수집 표본 Σ(체결가×수량) — 수집기가 30초 배치 로테이션을 "
                            "돌아 종목당 시간의 약 절반만 표본이다. 절대값은 과소, "
                            "종목 간 상대 비교용."),
            "change_basis": "직전 미국 정규장 마감(16:00 ET) 이전 마지막 체결 대비",
            "rows": out[:limit],
        }
        if not out:
            payload["note"] = "이번 미국 세션 체결이 아직 없다"
        return payload
