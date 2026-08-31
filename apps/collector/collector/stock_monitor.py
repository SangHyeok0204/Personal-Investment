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

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime

SRC_DIR = os.environ.get("STOCK_MONITOR_SRC_DIR", "/srv/legacy/toss_minute")
CACHE_DIR = os.environ.get("STOCK_MONITOR_CACHE_DIR", "/app/.cache/stock_monitor")
# 종목 메타(stock_info)·5대 축(stock_axis) — 파일 키는 **한글 이름**(심볼 아님).
# stock_info/{이름}.json      {name, symbol, sector:{L1..L5}, country, currency, news_axis}
# stock_axis/{이름}_axis.json {name, symbol, news_axis, axes:[5]}  ← 화면 편집이 여길 고쳐 쓴다
INPUT_DIR = os.environ.get("STOCK_MONITOR_INPUT_DIR", "/srv/legacy/toss_input")

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
    """sidecar 부재를 게이트로 복사한다. 복사 전후 mtime/size 가 어긋나면 버린다.

    ★검증(quick_check)을 통과한 사본만 tmp→os.replace 로 **원자 교체**한다.
    예전엔 dst 를 제자리에서 덮어썼는데, 복사가 도는 1~2초 동안 다른 요청 스레드가
    dst 를 열면 반쯤 덮인 파일을 읽어 'database disk image is malformed' 503 이
    났다 — 화면의 "collector 에 못 닿았습니다" 간헐 오류의 정체(2026-08-25 장중
    실측: 응답 0.00s 즉시 503 = 손상 캐시 판독 실패, 타임아웃 아님).
    교체 후엔 읽던 연결은 제 fd 로 옛 파일을 계속 보고, 새 연결만 새 파일을 연다
    (index_window._copy_db 와 같은 패턴 — 저쪽은 처음부터 이렇게 했다).
    """
    if not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    for _ in range(COPY_RETRIES):
        if not _sidecars_absent(src):
            time.sleep(0.4)
            continue
        st0 = os.stat(src)
        try:
            shutil.copy2(src, tmp)
        except OSError as ex:
            _log(f"복사 실패: {ex}")
            time.sleep(0.4)
            continue
        st1 = os.stat(src)
        if (st0.st_mtime, st0.st_size) != (st1.st_mtime, st1.st_size):
            continue                      # 복사 중에 상류가 썼다 — 다시
        # ★close 는 finally 로 — execute 가 던지는 경로에서 연결이 열린 채 남으면
        #   (Windows 로컬 테스트 실측) tmp 제거가 막힌다.
        try:
            con = sqlite3.connect(tmp)
            try:
                ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                con.close()
        except sqlite3.Error:
            ok = False
        if ok:
            os.replace(tmp, dst)          # 검증 통과분만 설치
            return True
        time.sleep(0.4)
    try:
        os.remove(tmp)                    # 실패 잔재 정리 — dst 는 마지막 정상본 유지
    except OSError:
        pass
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


# ── 종목 상세 · 5대 축 ──────────────────────────────────────────────────────
# 파일 키가 한글 이름이라 심볼→파일 역인덱스가 없다. 전량 스캔으로 만들 수도 있지만
# SMB 위 199파일 stat 이 요청 예산을 넘긴 전례(회의탭 PoC 503)가 있어, 화면이 이미
# 들고 있는 name 을 그대로 받아 **딱 2파일만** 직독한다.

def _safe_name(name: str) -> str | None:
    """경로 문자를 막는다 — name 이 그대로 파일명이 된다."""
    if not name or any(t in name for t in ("/", "\\", "..", "\x00")):
        return None
    return name


def stock_detail(name: str) -> dict | None:
    """stock_info/{이름}.json + stock_axis/{이름}_axis.json 병합. 둘 다 없으면 None.

    news_axis 는 두 파일에 다 있는데 **축 파일 값이 이긴다** — 편집으로 갱신되는 쪽이
    그 파일이라, info 쪽이 이기면 방금 저장한 값이 화면에서 되돌아가 보인다.
    """
    nm = _safe_name(name)
    if nm is None:
        return None
    out: dict = {"name": nm, "symbol": None, "sector": None, "country": None,
                 "currency": None, "news_axis": False,
                 "axes": ["", "", "", "", ""], "has_axis_file": False}
    found = False
    try:
        with open(os.path.join(INPUT_DIR, "stock_info", f"{nm}.json"),
                  encoding="utf-8") as f:
            info = json.load(f)
        out.update({k: info.get(k, out[k]) for k in
                    ("symbol", "sector", "country", "currency", "news_axis")})
        found = True
    except (OSError, json.JSONDecodeError):
        pass
    try:
        with open(os.path.join(INPUT_DIR, "stock_axis", f"{nm}_axis.json"),
                  encoding="utf-8") as f:
            ax = json.load(f)
        axes = ax.get("axes")
        if isinstance(axes, list):
            out["axes"] = [str(a) for a in (axes + [""] * 5)[:5]]
        out["symbol"] = out["symbol"] or ax.get("symbol")
        out["news_axis"] = bool(ax.get("news_axis", out["news_axis"]))
        out["has_axis_file"] = True
        found = True
    except (OSError, json.JSONDecodeError):
        pass
    return out if found else None


def save_axes(payload: dict) -> tuple[int, dict]:
    """5대 축 저장 — stock_axis/{이름}_axis.json 을 tmp→os.replace 로 원자 교체.

    (status, body) 를 돌려주고 HTTP 매핑은 라우트가 한다. 파일이 없으면 404 —
    생성은 상류(수기 입력) 소관이라 여기서 새 파일을 만들지 않는다.
    """
    nm = _safe_name(str(payload.get("name") or ""))
    if nm is None:
        return 400, {"detail": "이름이 비었거나 경로 문자가 들어있다"}
    axes = payload.get("axes")
    if not isinstance(axes, list) or len(axes) != 5 \
            or not all(isinstance(a, str) for a in axes):
        return 400, {"detail": "axes 는 문자열 5개 배열이라야 한다"}

    path = os.path.join(INPUT_DIR, "stock_axis", f"{nm}_axis.json")
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
    except FileNotFoundError:
        return 404, {"detail": "축 파일이 없다 — 생성은 상류(수기 입력) 소관"}
    except (OSError, json.JSONDecodeError) as ex:
        return 503, {"detail": f"축 파일을 못 읽었다: {ex}"}

    # 화면이 보던 종목과 파일이 같은 종목인지 대조 — 이름이 같고 심볼이 다르면
    # (개명·재상장 등) 조용히 덮어쓰지 않는다.
    sym = payload.get("symbol")
    if sym and cur.get("symbol") and sym != cur["symbol"]:
        return 409, {"detail": f"symbol 불일치 — 파일 {cur['symbol']} vs 요청 {sym}"}

    # 상류 스키마·키 순서를 그대로 보존한다(수기 입력자가 diff 로 봐도 낯설지 않게).
    doc = {"name": cur.get("name", nm), "symbol": cur.get("symbol"),
           "news_axis": bool(payload.get("news_axis", cur.get("news_axis", False))),
           "axes": [a.strip() for a in axes]}
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as ex:
        return 503, {"detail": f"저장 실패: {ex}"}
    return 200, {"ok": True, "name": nm, "saved": doc}
