"""[종목 모니터] — KOSPI200 분봉 기반 실시간 급등락·이상현상 탐지.

데이터 원천: S:\\GE\\raw\\data\\Toss_분봉_모니터\\output
  · minute_bars_YYYYMM.db — minute_bars(symbol, ts, open/high/low/close, volume, source)
  · state.db              — universe(symbol, name, prev_close, cap_rank,
                                      sigma_daily, vol_mu, vol_sigma)

상류(S:)가 굽고 대시보드는 읽는다 — 매크로·성과보고와 같은 배선이다. 다만 저쪽이
주는 것은 결과 JSON 이 아니라 **원시 분봉**이라, 집계는 여기서 한다(GURU[13F] 와 같은 처지).

★WAL-over-SMB 는 SQLite 공식 미지원이다. 수집기가 계속 쓰는 DB 를 요청 경로에서
  직접 열지 않고, sidecar(-wal/-shm) **부재**를 게이트로 /app/.cache 에 복사해 읽는다.
  guru13f.py 가 같은 이유로 같은 일을 한다 — 그 방식을 그대로 따른다.

★화면 컬럼은 토스 '실시간 차트' 를 따른다(docs/toss 실시간.png). 다만
  · `토스증권 거래 비율` 은 토스 앱 내부값이라 원천이 없다 → **뺀다**(사용자 확정).
  · `시가총액`·`산업` 은 원천이 없지만 자리는 남긴다 → 빈 칸으로 내려보낸다.
  · `토스증권 AI 요약` → **[실시간 이슈]** 로 이름만 바꾸고 역시 빈 칸.
  세 컬럼은 소스가 생기면 이 파일의 reshape 만 고치면 된다(화면은 그대로).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from datetime import datetime

SRC_DIR = os.environ.get("STOCK_MONITOR_SRC_DIR", "/srv/legacy/toss_minute")
CACHE_DIR = os.environ.get("STOCK_MONITOR_CACHE_DIR", "/app/.cache/stock_monitor")

REFRESH_CHECK_S = 30          # 분봉이라 촘촘히 본다(수집기는 1분마다 쓴다)
COPY_RETRIES = 3
TOP_N = 30                    # 화면이 2칸이라 30행이면 스크롤로 충분하다


def _log(msg: str) -> None:
    print(f"[stock-monitor] {msg}", flush=True)


def _bars_name(day: str) -> str:
    """'YYYY-MM-DD' → minute_bars_YYYYMM.db (상류 db.bars_db_path 와 같은 규칙)."""
    return f"minute_bars_{day[:7].replace('-', '')}.db"


def _sidecars_absent(path: str) -> bool:
    """-wal/-shm/-journal 이 없어야 '지금은 아무도 안 쓰는 상태'로 본다."""
    return not any(os.path.exists(path + suf) for suf in ("-wal", "-shm", "-journal"))


def _copy_when_quiet(src: str, dst: str) -> bool:
    """sidecar 부재를 게이트로 복사한다. 복사 전후 mtime/size 가 어긋나면 버린다."""
    if not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for _ in range(COPY_RETRIES):
        if not _sidecars_absent(src):
            time.sleep(0.4)
            continue
        st0 = os.stat(src)
        try:
            shutil.copy2(src, dst)
        except OSError as ex:
            _log(f"복사 실패: {ex}")
            time.sleep(0.4)
            continue
        st1 = os.stat(src)
        if (st0.st_mtime, st0.st_size) != (st1.st_mtime, st1.st_size):
            continue                      # 복사 중에 상류가 썼다 — 다시
        try:
            con = sqlite3.connect(dst)
            ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            con.close()
        except sqlite3.Error:
            ok = False
        if ok:
            return True
        time.sleep(0.4)
    _log("조용한 순간을 못 잡았다 — 이전 스냅샷을 계속 쓴다")
    return False


class StockMonitor:
    """분봉 DB 스냅샷을 들고 화면용 payload 를 만든다."""

    def __init__(self) -> None:
        self._last_copy = 0.0
        self._src_sig: tuple | None = None

    # --- 스냅샷 -------------------------------------------------------
    def _refresh(self, day: str) -> None:
        if time.time() - self._last_copy < REFRESH_CHECK_S:
            return
        self._last_copy = time.time()
        pairs = [(os.path.join(SRC_DIR, _bars_name(day)),
                  os.path.join(CACHE_DIR, _bars_name(day))),
                 (os.path.join(SRC_DIR, "state.db"),
                  os.path.join(CACHE_DIR, "state.db"))]
        sig = tuple((os.stat(s).st_mtime, os.stat(s).st_size)
                    if os.path.exists(s) else None for s, _ in pairs)
        if sig == self._src_sig and all(os.path.exists(d) for _, d in pairs):
            return                        # 상류가 안 바뀌었다
        for s, d in pairs:
            _copy_when_quiet(s, d)
        self._src_sig = sig

    def _connect(self, day: str) -> sqlite3.Connection | None:
        bars = os.path.join(CACHE_DIR, _bars_name(day))
        state = os.path.join(CACHE_DIR, "state.db")
        if not (os.path.exists(bars) and os.path.exists(state)):
            return None
        con = sqlite3.connect(bars)
        con.row_factory = sqlite3.Row
        con.execute("ATTACH DATABASE ? AS st", (state,))
        return con

    # --- payload ------------------------------------------------------
    def build(self, day: str | None = None, sort: str = "value",
              limit: int = TOP_N) -> dict:
        """화면 테이블 한 장. sort: value(거래대금) | change(등락) | sigma(이상)"""
        day = day or datetime.now().strftime("%Y-%m-%d")
        self._refresh(day)
        con = self._connect(day)
        if con is None:
            return {"asof": None, "rows": [], "note": "분봉 스냅샷이 아직 없다"}

        # 그날의 마지막 봉 시각 — 화면 머리글의 '오늘 15:39 기준' 자리.
        asof = con.execute(
            "SELECT MAX(ts) FROM minute_bars WHERE ts LIKE ?", (day + "%",)
        ).fetchone()[0]
        if not asof:
            con.close()
            return {"asof": None, "rows": [], "note": f"{day} 분봉이 없다"}

        # ★거래대금은 분봉 (volume × close) 누적이다. 토스의 '토스증권 거래대금'과는
        #   정의가 다르다 — 저쪽은 토스 앱 체결분만 센다. 같은 이름을 쓰되 뜻이
        #   다르다는 것을 payload 에 적어 화면이 오해하지 않게 한다.
        rows = con.execute(
            """
            WITH agg AS (
              SELECT symbol,
                     SUM(volume)               AS vol,
                     SUM(volume * close)       AS value,
                     MAX(ts)                   AS last_ts
              FROM minute_bars
              WHERE ts LIKE ?
              GROUP BY symbol
            ),
            last AS (
              SELECT b.symbol, b.close
              FROM minute_bars b
              JOIN agg a ON a.symbol = b.symbol AND a.last_ts = b.ts
            )
            SELECT u.symbol, u.name, u.prev_close, u.cap_rank,
                   u.sigma_daily, u.vol_mu, u.vol_sigma,
                   l.close, a.vol, a.value
            FROM agg a
            JOIN last l ON l.symbol = a.symbol
            JOIN st.universe u ON u.symbol = a.symbol
            """,
            (day + "%",),
        ).fetchall()
        con.close()

        out = []
        for r in rows:
            close, prev = r["close"], r["prev_close"]
            chg = (close / prev - 1) * 100 if prev else None
            sig = r["sigma_daily"] or 0
            # 그 종목 자신의 분포로 잰다 — 고정 임계값(±5%)은 종목마다 뜻이 달라진다.
            chg_z = (chg / sig) if (chg is not None and sig) else None
            vs = r["vol_sigma"] or 0
            vol_z = ((r["vol"] - (r["vol_mu"] or 0)) / vs) if vs else None
            out.append({
                "symbol": r["symbol"],
                "name": r["name"],
                "price": close,
                "change_pct": chg,
                "value": r["value"],
                "volume": r["vol"],
                "market_cap": None,      # 원천 없음 — 자리만 둔다
                "industry": None,        # 원천 없음
                "issue": None,           # [실시간 이슈] — 원천 없음
                "cap_rank": r["cap_rank"],
                "change_sigma": chg_z,
                "volume_z": vol_z,
            })

        key = {"value": lambda x: -(x["value"] or 0),
               "change": lambda x: -(x["change_pct"] or 0),
               "sigma": lambda x: -abs(x["change_sigma"] or 0)}.get(sort)
        if key:
            out.sort(key=key)
        for i, x in enumerate(out[:limit], 1):
            x["rank"] = i

        return {
            "asof": asof,
            "day": day,
            "sort": sort,
            "universe": len(rows),
            # 화면이 '거래대금'을 토스와 같은 것으로 읽지 않게 한다.
            "value_basis": "분봉 Σ(volume×close) — 토스 앱 체결분만 세는 '토스증권 거래대금'과 다르다",
            "rows": out[:limit],
        }
