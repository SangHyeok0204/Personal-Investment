"""GURU[13F] 서비스 — 13F 거장 포트폴리오 비중/변화 payload 빌더.

데이터 원천: S:\\GE\\raw\\data\\13F기관내부자\\db\\filings.db (SQLite 300MB, **WAL**,
개발PC 상주서버가 기록). WAL-over-SMB 는 SQLite 공식 미지원이라 요청 경로에서 원본을
직접 열지 않는다. 대신 이 서비스가:

  1. 백그라운드 refresh 루프에서 소스 DB mtime 변화를 감지하고,
  2. sidecar(-wal/-shm/-journal) **부재**를 게이트로 소스 DB 를 /app/.cache 로 복사한 뒤
     (복사 전후 mtime/size/sidecar 재확인 + 논리 sanity(MAX period,COUNT) + quick_check),
  3. 무거운 교차거장 집계(consensus/turnover)를 **사전계산**해 메모리에 캐시하고,
  4. 단일거장 조회(portfolio/changes/timeline)는 요청 시 **로컬 copy** 로 경량 쿼리한다.

정합 로직(13F-HR/A 중복제거·천달러 단위보정·부분크롤 가드·주식클래스 병합·옵션행 제외)은
모두 guru_queries.py(소스 storage.py verbatim 벤더링)에 있다. 이 파일은 서빙 셸 + reshape 만.
ralplan v3.1 §3-B/§3-E. 2026-07-24.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import time
from datetime import datetime

from collector import guru_queries

# 소스 DB(:ro 마운트) 와 로컬 스냅샷 복사본 경로.
SRC_DB = os.environ.get("GURU13F_SRC_DB", "/srv/legacy/guru13f_db/filings.db")
CACHE_DIR = os.environ.get("GURU13F_CACHE_DIR", "/app/.cache/guru13f")
CACHE_DB = os.path.join(CACHE_DIR, "filings.db")

# 초기 노출 로스터 = 사용자 승인 대표 거장 9인(ralplan §8-1, 2026-07-24 확정).
# guru_queries.GURU_BY_CIK(큐레이션 23) 중 실제 최신분기 제출자는 22명이지만, 사용자가
# "대표 ~10명 우선"을 선택 → 아래 화이트리스트로 초기 노출을 한정한다(전체 지원은 유지).
DEFAULT_ROSTER_CIKS = {
    "0001067983",  # Berkshire Hathaway (Buffett)
    "0001350694",  # Bridgewater (Dalio)
    "0001135730",  # Coatue (Laffont)
    "0001167483",  # Tiger Global (Coleman)
    "0001536411",  # Duquesne (Druckenmiller)
    "0001656456",  # Appaloosa (Tepper)
    "0001061768",  # Baupost (Klarman)
    "0001336528",  # Pershing Square (Ackman)
    "0001709323",  # Himalaya (Li Lu)
}

REFRESH_CHECK_S = 300          # 소스 mtime 재확인 주기(초). 분기 데이터라 느슨.
COPY_RETRIES = 3
TIMELINE_QUARTERS = 8          # §8-4b
TIMELINE_TOP_N = 8
PORTFOLIO_TOP_N = 15           # §8-4a
CONSENSUS_TOP_N = 20


def _log(msg: str) -> None:
    print(f"[guru13f] {msg}", flush=True)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sidecars_present(src: str) -> bool:
    """WAL writer 활성 표식. 하나라도 있으면 복사 금지(체크포인트 미완료 가능)."""
    return any(os.path.exists(src + ext) for ext in ("-wal", "-shm", "-journal"))


def _db_sig(uri: str):
    """비퇴화 시그니처 = (MAX(period_of_report), COUNT(*)) on 13F filings.

    서빙 쿼리가 실제로 읽는 테이블(filings form_type='13F' / holdings_13f)을 기준으로
    삼아, 상류에서 파생 테이블이 사라져도 유효성 판정이 서빙과 함께 움직이게 한다.
    """
    try:
        con = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            row = con.execute(
                "SELECT MAX(period_of_report), COUNT(*) FROM filings WHERE form_type='13F'"
            ).fetchone()
            return (row[0], row[1])
        finally:
            con.close()
    except Exception:
        return None


def _quick_check(path: str) -> bool:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            con.close()
    except Exception:
        return False


class Guru13F:
    """13F 거장 payload 서비스 (독립 — KIS 클라이언트 비의존)."""

    def __init__(self) -> None:
        self._ready = False
        self._snapshot_mtime: float | None = None
        self._dbver = "0"
        self._roster: dict | None = None
        self._consensus: dict | None = None
        self._turnover: dict | None = None
        self._latest_period: str | None = None

    # ── 복사 게이트 (§3-B) ────────────────────────────────────────────
    def _copy_snapshot(self) -> bool:
        src = SRC_DB
        if not os.path.exists(src):
            return False
        if _sidecars_present(src):            # writer 활성 → 이번 사이클 skip
            return False
        try:
            st0 = os.stat(src)
        except OSError:
            return False
        # 주의: 라이브 WAL DB 는 :ro SMB 바인드마운트에서 열리지 않는다("unable to open
        # database file") — 이것이 애초에 복사하는 이유다. 따라서 복사 전 live 시그니처
        # 대조는 불가능하다. 일관성은 (a) sidecar 부재 + (b) 복사 전후 (mtime,size) 불변
        # 으로 '체크포인트 완료 & 복사중 원본 무변경' 을 보장하고, 복사본은 quick_check +
        # 비퇴화(레코드 존재) 검사로 확인한다.
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE_DB + ".tmp"
        try:
            shutil.copy2(src, tmp)
        except OSError as exc:
            _log(f"copy failed: {exc!r}")
            _safe_unlink(tmp)
            return False

        # 복사 후 재검증: sidecar 여전히 부재 AND (mtime,size) 불변
        if _sidecars_present(src):
            _safe_unlink(tmp)
            return False
        try:
            st1 = os.stat(src)
        except OSError:
            _safe_unlink(tmp)
            return False
        if (st1.st_mtime, st1.st_size) != (st0.st_mtime, st0.st_size):
            _safe_unlink(tmp)
            return False
        # 구조 검사 + 비퇴화(레코드 존재) 검사. quick_check 는 구조 손상만 잡으므로,
        # (mtime,size) 불변 게이트가 논리 tearing(복사중 원본 변경)을 막는 실제 보증이다.
        if not _quick_check(tmp):
            _safe_unlink(tmp)
            return False
        sig = _db_sig(f"file:{tmp}?mode=ro")
        if not sig or sig[0] is None or (sig[1] or 0) <= 0:
            _safe_unlink(tmp)
            return False
        os.replace(tmp, CACHE_DB)             # 같은 fs 원자 교체
        return True

    # ── refresh 루프 진입점(블로킹, to_thread 로 호출) ───────────────
    def refresh(self) -> None:
        try:
            mtime = os.stat(SRC_DB).st_mtime
        except OSError:
            mtime = None
        if self._ready and self._snapshot_mtime == mtime:
            return                            # 변화 없음
        ok = False
        for attempt in range(COPY_RETRIES):
            if self._copy_snapshot():
                ok = True
                break
            time.sleep(1.5 * (attempt + 1))
        if not ok:
            _log("copy gated/failed — keeping last-good")
            return
        guru_queries.DB_PATH = CACHE_DB       # on-request 쿼리도 로컬 copy 대상
        try:
            roster = self._build_roster()
            consensus = self._build_consensus(roster)
            turnover = self._build_turnover(roster)
        except Exception as exc:              # noqa: BLE001 — last-good 유지
            _log(f"precompute failed: {exc!r} — keeping last-good")
            return
        self._roster = roster
        self._consensus = consensus
        self._turnover = turnover
        self._latest_period = roster.get("latest_period")
        self._snapshot_mtime = mtime
        self._dbver = str(int(mtime)) if mtime else "0"
        self._ready = True
        _log(f"refreshed dbver={self._dbver} gurus={len(roster.get('gurus', []))} "
             f"latest={self._latest_period}")

    async def loop(self, stop_event) -> None:
        import asyncio
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(self.refresh)
            except Exception as exc:          # noqa: BLE001
                _log(f"refresh loop error: {exc!r}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=REFRESH_CHECK_S)
            except asyncio.TimeoutError:
                pass

    # ── precompute 빌더 ───────────────────────────────────────────────
    def _build_roster(self) -> dict:
        con = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True, timeout=10.0)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT DISTINCT watch_cik AS cik, period_of_report AS period "
                "FROM filings WHERE form_type='13F' AND period_of_report!=''"
            ).fetchall()
        finally:
            con.close()
        by_cik: dict[str, set] = {}
        for r in rows:
            if guru_queries.guru_label(r["cik"]) is None:   # 큐레이션 거장(23)만
                continue
            by_cik.setdefault(r["cik"], set()).add(r["period"])
        gurus = []
        for cik, periods in by_cik.items():
            gl = guru_queries.guru_label(cik)
            qs = sorted(periods)
            gurus.append({"cik": cik, "guru": gl["guru"], "firm": gl["firm"],
                          "latest": qs[-1], "quarters": qs})
        latest_overall = max((g["latest"] for g in gurus), default=None)
        # 초기 노출 = 최신분기 제출 거장 중 대표 화이트리스트(§8-1). 미설정 시 전체.
        exposed = [g for g in gurus if g["latest"] == latest_overall]
        if DEFAULT_ROSTER_CIKS:
            exposed = [g for g in exposed if g["cik"] in DEFAULT_ROSTER_CIKS]
        # AUM 내림차순 정렬 + 드롭다운 표시용 (background 이므로 per-guru 쿼리 허용)
        for g in exposed:
            try:
                pc = guru_queries.position_changes(g["cik"], prev=g["latest"], curr=g["latest"])
                g["aum_usd"] = sum(r["value_curr"] for r in pc["rows"])
            except Exception:                 # noqa: BLE001
                g["aum_usd"] = 0.0
        exposed.sort(key=lambda g: g["aum_usd"], reverse=True)
        return {"latest_period": latest_overall, "gurus": exposed}

    def _build_consensus(self, roster: dict) -> dict:
        ciks = [g["cik"] for g in roster.get("gurus", [])]
        gc = guru_queries.guru_consensus(ciks, quarters=2, top_n=CONSENSUS_TOP_N)
        def _h(h):
            return {"cusip": h["cusip"], "name": h["name"], "ticker": h["ticker"],
                    "holders_n": h["holders"], "conviction_pct": round(h["conviction_pct"] * 100, 2)}
        def _f(x):
            return {"cusip": x["cusip"], "name": x["name"], "ticker": x["ticker"],
                    "buyers": x["buyers"], "sellers": x["sellers"], "net": x["net"]}
        return {"period": gc["latest_period"], "prev_period": gc["prev_period"],
                "gurus_n": gc["n_investors"],
                "holdings": [_h(h) for h in gc["consensus_holdings"]],
                "buys": [_f(x) for x in gc["consensus_buys"]],
                "sells": [_f(x) for x in gc["consensus_sells"]]}

    def _build_turnover(self, roster: dict) -> dict:
        rows = []
        for g in roster.get("gurus", []):
            t = guru_queries.compute_investor_turnover(g["cik"])
            if not t:
                continue
            rows.append({"cik": g["cik"], "guru": g["guru"], "firm": g["firm"],
                         "turnover_pct": round(t["score"] * 100, 2),
                         "new_n": t["new_count"], "exited_n": t["exited_count"],
                         "partial": t["partial"], "aum_usd": t["total_value"]})
        rows.sort(key=lambda r: r["turnover_pct"], reverse=True)
        return {"period": roster.get("latest_period"), "rows": rows}

    # ── on-request 로컬 copy 조회 헬퍼 ────────────────────────────────
    def _prev_period(self, cik: str, period: str) -> str | None:
        con = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True, timeout=10.0)
        try:
            ps = [r[0] for r in con.execute(
                "SELECT DISTINCT period_of_report FROM filings "
                "WHERE watch_cik=? AND form_type='13F' AND period_of_report!='' "
                "ORDER BY period_of_report DESC", (cik,)).fetchall()]
        finally:
            con.close()
        if period in ps:
            i = ps.index(period)
            return ps[i + 1] if i + 1 < len(ps) else None
        return None

    def _filing_meta(self, cik: str, period: str) -> tuple[str | None, bool]:
        con = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True, timeout=10.0)
        try:
            fd = con.execute(
                "SELECT filing_date FROM filings WHERE watch_cik=? AND form_type='13F' "
                "AND period_of_report=? ORDER BY filing_date DESC LIMIT 1",
                (cik, period)).fetchone()
            cnt = con.execute(
                "SELECT COUNT(*) FROM filings WHERE watch_cik=? AND form_type='13F' "
                "AND period_of_report=?", (cik, period)).fetchone()[0]
        finally:
            con.close()
        # 같은 (cik,period) 에 복수 공시 = 원본+정정(13F-HR/A) → amended
        return (fd[0] if fd else None), (cnt > 1)

    # ── payload 서빙 (main.py 엔드포인트가 호출) ──────────────────────
    def etag(self, *parts) -> str:
        raw = "|".join(str(p) for p in (self._dbver, *parts))
        return '"' + hashlib.sha1(raw.encode()).hexdigest()[:16] + '"'

    def roster(self) -> dict | None:
        if not self._ready or self._roster is None:
            return None
        return {"generatedAt": _now(), "dbVersion": self._dbver, **self._roster}

    def consensus(self, period: str | None = None) -> dict | None:
        # precompute-only(최신분기). 비최신 period 요청 = None → 503 (요청경로 무거운 쿼리 금지).
        if not self._ready or self._consensus is None:
            return None
        if period is not None and period != self._latest_period:
            return None
        return {"generatedAt": _now(), "dbVersion": self._dbver, **self._consensus}

    def turnover(self, period: str | None = None) -> dict | None:
        if not self._ready or self._turnover is None:
            return None
        if period is not None and period != self._latest_period:
            return None
        return {"generatedAt": _now(), "dbVersion": self._dbver, **self._turnover}

    def portfolio(self, cik: str, period: str) -> dict | None:
        if not self._ready:
            return None
        prev = self._prev_period(cik, period)
        pc = guru_queries.position_changes(cik, prev=(prev or period), curr=period)
        comp = [r for r in pc["rows"] if r["status"] != "exited"]
        if not comp and not pc["rows"]:
            return None
        comp.sort(key=lambda r: r["wgt_curr"], reverse=True)
        aum = sum(r["value_curr"] for r in comp)
        priced_n = sum(1 for r in comp if r["ticker"])
        top5 = sum(r["wgt_curr"] for r in comp[:5]) * 100
        top10 = sum(r["wgt_curr"] for r in comp[:10]) * 100
        holdings = [{"cusip": r["cusip"], "name": r["name"], "ticker": r["ticker"],
                     "weight_pct": round(r["wgt_curr"] * 100, 4),
                     "value_usd": r["value_curr"], "shares": r["shares_curr"]}
                    for r in comp[:PORTFOLIO_TOP_N]]
        filing_date, _ = self._filing_meta(cik, period)
        gl = guru_queries.guru_label(cik) or {"guru": pc.get("watch_name", ""), "firm": ""}
        return {"generatedAt": _now(), "dbVersion": self._dbver,
                "cik": cik, "guru": gl["guru"], "firm": gl["firm"],
                "period": period, "filingDate": filing_date,
                "aum_usd": aum, "n_holdings": len(comp),
                "priced_n": priced_n, "total_n": len(comp),
                "top5_pct": round(top5, 2), "top10_pct": round(top10, 2),
                "holdings": holdings}

    def changes(self, cik: str, period: str) -> dict | None:
        if not self._ready:
            return None
        prev = self._prev_period(cik, period)
        is_first = prev is None
        pc = guru_queries.position_changes(cik, prev=(prev or period), curr=period)
        filing_date, amended = self._filing_meta(cik, period)

        def _mk(r):
            return {"cusip": r["cusip"], "name": r["name"], "ticker": r["ticker"],
                    "weight_pct": round(r["wgt_curr"] * 100, 4),
                    "delta_ppt": round(r["wgt_chg"] * 100, 4)}

        def _mk_ex(r):
            return {"cusip": r["cusip"], "name": r["name"], "ticker": r["ticker"],
                    "prev_weight_pct": round(r["wgt_prev"] * 100, 4),
                    "delta_ppt": round(r["wgt_chg"] * 100, 4)}

        rows = pc["rows"]
        new = sorted((_mk(r) for r in rows if r["status"] == "new"),
                     key=lambda x: x["weight_pct"], reverse=True)
        inc = sorted((_mk(r) for r in rows if r["status"] == "increased"),
                     key=lambda x: x["delta_ppt"], reverse=True)
        dec = sorted((_mk(r) for r in rows if r["status"] == "decreased"),
                     key=lambda x: x["delta_ppt"])
        ex = sorted((_mk_ex(r) for r in rows if r["status"] == "exited"),
                    key=lambda x: x["prev_weight_pct"], reverse=True)
        return {"generatedAt": _now(), "dbVersion": self._dbver,
                "cik": cik, "period": period, "prevPeriod": prev,
                "isFirst": is_first, "amended": amended,
                "new": new, "increased": inc, "decreased": dec, "exited": ex}

    def timeline(self, cik: str) -> dict | None:
        if not self._ready:
            return None
        pi = guru_queries.portfolio_investor(cik, quarters=TIMELINE_QUARTERS,
                                             top_n=TIMELINE_TOP_N)
        periods = list(pi["periods"])
        # 부분크롤 분기 제외(턴오버 가드와 동일 취지): 보유종목수가 중앙값의 50% 미만
        # (또는 5 미만)인 분기는 top-N 이 0으로 찍혀 가짜 급락 V자를 만든다 → 축에서 제거.
        cnt = {p: 0 for p in periods}
        for h in pi["all_holdings"]:
            for pt in h["points"]:
                if (pt.get("wgt") or 0) > 0 and pt["period"] in cnt:
                    cnt[pt["period"]] += 1
        if cnt:
            ordered = sorted(cnt.values())
            m = len(ordered)
            median_cnt = ordered[m // 2] if m % 2 else (ordered[m // 2 - 1] + ordered[m // 2]) / 2
            floor = max(5, 0.5 * median_cnt)
            periods = [p for p in periods if cnt[p] >= floor]
        series = []
        for s in pi["series"]:
            if not s["cusip"]:                # '기타(Others)' 합계행 제외
                continue
            wmap = {p["period"]: p["wgt"] for p in s["points"]}
            series.append({"cusip": s["cusip"], "name": s["name"], "ticker": s["ticker"],
                           "weights": [round((wmap.get(p, 0.0) or 0.0) * 100, 4) for p in periods]})
        return {"generatedAt": _now(), "dbVersion": self._dbver,
                "cik": cik, "periods": periods, "series": series}


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
