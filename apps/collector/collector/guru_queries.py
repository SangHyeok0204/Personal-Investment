"""13F 거장 포트폴리오 분석 쿼리 — VENDORED (verbatim) from the source project.

SOURCE  : S:\\GE\\raw\\운용 전략\\구루\\13F기관내부자\\src\\storage.py (+ gurus.py, normalize.pad_cik)
COPIED  : 2026-07-24 (GURU[13F] track-record tab, ralplan v3.1)
RULE    : 이 모듈의 분석 함수(_LATEST_13F_CTE(_ONE), _SHARE_CLASS_MERGE, _money_factor,
          _label, portfolio_investor, compute_investor_turnover, portfolio_investee,
          guru_consensus, position_changes)는 소스 storage.py 에서 **원문 복사**한다.
          수정한 것은 오직 (1) `_conn()` 이 로컬 .cache 스냅샷(module DB_PATH)을 read-only 로 열고,
          (2) 소스의 `from src import config, gurus` 대신 gurus 맵/pad_cik 을 이 파일에 인라인한 것뿐.
          정합 픽스(13F-HR/A 중복제거·천달러 68.7% 단위보정·부분크롤 가드·주식클래스 병합·옵션행
          제외)는 절대 재구현/수정 금지. 소스 storage.py 변경 시 이 파일을 재복사할 것.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

# ── module-configurable DB path (guru13f.py sets this to the local .cache copy) ──
# 소스는 config.DB_PATH(라이브 S: DB)를 열지만, 벤더 사본은 WAL-over-SMB 를 피해
# guru13f.py 가 sidecar-게이트로 복사한 로컬 스냅샷 경로를 주입한다.
DB_PATH: str | None = None


@contextmanager
def _conn():
    if DB_PATH is None:
        raise RuntimeError("guru_queries.DB_PATH is not set (guru13f service must inject the .cache snapshot path)")
    # read-only 로 로컬 copy 를 연다. immutable 은 사용하지 않는다(체크포인트 torn read 방지).
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
    finally:
        conn.close()


# ── vendored from gurus.py (CIK → (guru, firm)) + normalize.pad_cik ──
GURU_BY_CIK: dict[str, tuple[str, str]] = {
    "0001067983": ("Warren Buffett", "Berkshire Hathaway"),
    "0001096343": ("Tom Gayner", "Markel Group"),
    "0000915191": ("Prem Watsa", "Fairfax Financial"),
    "0001166559": ("Bill Gates", "Gates Foundation Trust"),
    "0001336528": ("Bill Ackman", "Pershing Square"),
    "0001350694": ("Ray Dalio", "Bridgewater Associates"),
    "0001061768": ("Seth Klarman", "Baupost Group"),
    "0001709323": ("Li Lu", "Himalaya Capital"),
    "0001549575": ("Mohnish Pabrai", "Dalal Street"),
    "0001112520": ("Chuck Akre", "Akre Capital"),
    "0001536411": ("Stanley Druckenmiller", "Duquesne Family Office"),
    "0001040273": ("Daniel Loeb", "Third Point"),
    "0001656456": ("David Tepper", "Appaloosa"),
    "0000921669": ("Carl Icahn", "Icahn Capital"),
    "0001791786": ("Paul Singer", "Elliott Investment Mgmt"),
    "0001647251": ("Chris Hohn", "TCI Fund Mgmt"),
    "0001167483": ("Chase Coleman", "Tiger Global"),
    "0001135730": ("Philippe Laffont", "Coatue Mgmt"),
    "0001061165": ("Steve Mandel", "Lone Pine Capital"),
    "0001510387": ("Joel Greenblatt", "Gotham Asset Mgmt"),
    "0001697748": ("Cathie Wood", "ARK Investment Mgmt"),
    "0001649339": ("Michael Burry", "Scion Asset Mgmt"),
    "0002045724": ("Leopold Aschenbrenner", "Situational Awareness"),
}


def pad_cik(cik) -> str | None:
    """EDGAR 경로용 10자리 zero-padded CIK ('1318605' → '0001318605')."""
    if cik is None:
        return None
    return str(cik).strip().zfill(10)


def guru_label(cik: str) -> dict | None:
    """CIK 의 거장 라벨 {"guru", "firm"} 반환 (미등록이면 None)."""
    padded = pad_cik(cik)
    pair = GURU_BY_CIK.get(padded)
    if not pair:
        return None
    return {"guru": pair[0], "firm": pair[1]}


# ── 포트폴리오 분석 (13F) ──────────────────────────────────
# 수정공시(13F-HR/A) 중복 방어: (watch_cik, period_of_report) 당 1개 accession 만
# 사용한다 (최신 filing_date 우선 = /A 가 원본을 대체). 기존 공시는 절대 삭제하지
# 않고, 조회 시점에만 최신 1건을 고른다. 모든 시계열 쿼리가 이 CTE 를 토대로 한다.
_LATEST_13F_CTE = """
WITH latest_13f AS (
    SELECT accession_number, watch_cik, watch_name, period_of_report,
           ROW_NUMBER() OVER (
               PARTITION BY watch_cik, period_of_report
               ORDER BY filing_date DESC, accession_number DESC) AS rn
    FROM filings WHERE form_type='13F'
)
"""

# 단일 투자자 전용: 윈도우/조인 전에 watch_cik 를 먼저 걸러 filings/holdings 풀스캔을
# 피한다(리더보드 B1 온더플라이 가속). 첫 바인드 파라미터가 watch_cik 다.
_LATEST_13F_CTE_ONE = """
WITH latest_13f AS (
    SELECT accession_number, watch_cik, watch_name, period_of_report,
           ROW_NUMBER() OVER (
               PARTITION BY watch_cik, period_of_report
               ORDER BY filing_date DESC, accession_number DESC) AS rn
    FROM filings WHERE form_type='13F' AND watch_cik=?
)
"""


# cusip → 병합 대표 cusip (보통주 복수클래스만; 확장 가능)
# 블랜킷 ticker 합산은 위험(ETF시리즈/채권 혼입)이라 명백한 동일발행사 보통주만 화이트리스트.
_SHARE_CLASS_MERGE = {
    "02079K107": "02079K305",  # GOOG → GOOGL (Alphabet)
    "084670702": "084670108",  # BRK.B → BRK.A (Berkshire)
}

# Magnificent Seven CUSIP 집합 (AAPL/MSFT/GOOGL/GOOG/AMZN/META/NVDA/TSLA).
# GOOG/GOOGL 둘 다 포함해 _SHARE_CLASS_MERGE 적용 전/후 모두 M7 으로 잡히게 한다.
M7_CUSIPS = {
    "037833100",  # AAPL
    "594918104",  # MSFT
    "02079K305",  # GOOGL
    "02079K107",  # GOOG
    "023135106",  # AMZN
    "30303M102",  # META
    "67066G104",  # NVDA
    "88160R101",  # TSLA
}


def _label(row: sqlite3.Row) -> dict:
    """cusip_ref 라벨 (name/ticker). 없으면 holdings 의 name_of_issuer 폴백."""
    name = (row["ref_name"] or row["name_of_issuer"] or "").strip()
    return {"name": name, "ticker": (row["ticker"] or "") or None}


def _money_factor(rows: list) -> int:
    """13F 천달러/달러 단위혼재 보정 배수(표시용 금액 전용).

    accession 의 68.7% 가 천달러 단위(median(value/shares)<1)다. shares>0 행의
    value/shares 중앙값이 1 미만이면 ×1000 으로 표시용 금액을 달러 단위로 맞춘다.
    turnover(wgt) 경로엔 호출하지 말 것 — 분기 내 균일배수라 약분되어 no-op.
    """
    ratios = [r["value"] / r["shares"]
              for r in rows
              if (r["shares"] or 0) > 0 and r["value"] is not None]
    if not ratios:
        return 1
    ratios.sort()
    n = len(ratios)
    med = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
    return 1000 if med < 1 else 1


def portfolio_investor(watch_cik: str, quarters: int = 4, top_n: int = 12) -> dict:
    """기관 1곳의 분기별 종목 비중 시계열 + 이탈/신규/리밸런싱 하이라이트.

    - 비중은 이미 정확한 wgt(가치기준) 재사용. put_call(옵션) 행은 제외.
    - 리밸런싱은 가격영향이 큰 wgt 가 아니라 실제 수량변화(Δshares) 상위로 산출.
    """
    with _conn() as c:
        name_row = c.execute(
            "SELECT watch_name FROM filings WHERE watch_cik=? AND form_type='13F' "
            "ORDER BY filing_date DESC LIMIT 1", (watch_cik,)).fetchone()
        watch_name = name_row["watch_name"] if name_row else ""

        periods = [r["period_of_report"] for r in c.execute(
            _LATEST_13F_CTE +
            "SELECT period_of_report FROM latest_13f WHERE rn=1 AND watch_cik=? "
            "ORDER BY period_of_report DESC LIMIT ?", (watch_cik, quarters)).fetchall()]
        periods = sorted(p for p in periods if p)              # 오름차순 축
        if not periods:
            return {"watch_cik": watch_cik, "watch_name": watch_name, "periods": [],
                    "series": [], "all_holdings": [],
                    "highlights": {"exited": [], "added": [], "rebalanced": []},
                    "insufficient_history": True, "put_call_excluded": True}

        rows = c.execute(
            _LATEST_13F_CTE +
            f"""SELECT l.period_of_report AS period, h.cusip AS cusip,
                       h.name_of_issuer AS name_of_issuer, h.wgt AS wgt,
                       h.value AS value, h.shares AS shares,
                       r.name AS ref_name, r.ticker AS ticker
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                LEFT JOIN cusip_ref r ON r.cusip = h.cusip
                WHERE l.rn=1 AND l.watch_cik=?
                  AND l.period_of_report IN ({','.join('?' * len(periods))})
                  AND COALESCE(h.put_call,'')=''""",
            (watch_cik, *periods)).fetchall()

    # cusip 단위로 분기 시계열 모으기 (같은 cusip 다중행은 합산)
    by_cusip: dict[str, dict] = {}
    for r in rows:
        cu = r["cusip"]
        d = by_cusip.setdefault(cu, {"cusip": cu, **_label(r), "pts": {}})
        if not d["name"]:
            d.update(_label(r))
        p = d["pts"].setdefault(r["period"], {"wgt": 0.0, "value": 0.0, "shares": 0.0})
        p["wgt"] += r["wgt"] or 0.0
        p["value"] += r["value"] or 0.0
        p["shares"] += r["shares"] or 0.0

    latest = periods[-1]
    prev = periods[-2] if len(periods) >= 2 else None

    def points(d):
        return [{"period": p, **{k: round(v, 6) if k == "wgt" else v
                                 for k, v in (d["pts"].get(p) or
                                              {"wgt": 0.0, "value": 0.0, "shares": 0.0}).items()}}
                for p in periods]

    ranked = sorted(by_cusip.values(),
                    key=lambda d: (d["pts"].get(latest) or {}).get("wgt", 0.0), reverse=True)
    top = ranked[:top_n]
    rest = ranked[top_n:]
    series = [{"cusip": d["cusip"], "name": d["name"], "ticker": d["ticker"],
               "points": points(d)} for d in top]
    # 1년 내 보유한 모든 종목의 비중 시계열 (최신 비중 내림차순). 프런트 투자자 관점의
    # 좌측 자동분석(Δ비중 top3 + 신규/이탈)과 우측 동적 선택 박스가 공유하는 소스.
    all_holdings = [{"cusip": d["cusip"], "name": d["name"], "ticker": d["ticker"],
                     "points": points(d)} for d in ranked]
    if rest:                                                   # 나머지는 "기타(Others)"
        others_pts = {p: {"wgt": 0.0, "value": 0.0, "shares": 0.0} for p in periods}
        for d in rest:
            for p in periods:
                pt = d["pts"].get(p)
                if pt:
                    for k in ("wgt", "value", "shares"):
                        others_pts[p][k] += pt[k]
        series.append({"cusip": None, "name": f"기타({len(rest)})", "ticker": None,
                       "points": [{"period": p, "wgt": round(others_pts[p]["wgt"], 6),
                                   "value": others_pts[p]["value"], "shares": others_pts[p]["shares"]}
                                  for p in periods]})

    # 하이라이트 (직전 vs 최신)
    exited, added, rebalanced = [], [], []
    if prev:
        for d in by_cusip.values():
            cur = d["pts"].get(latest)
            old = d["pts"].get(prev)
            cur_sh = (cur or {}).get("shares", 0.0)
            old_sh = (old or {}).get("shares", 0.0)
            lbl = {"cusip": d["cusip"], "name": d["name"], "ticker": d["ticker"]}
            if old and old_sh and not (cur and cur_sh):
                exited.append({**lbl, "prev_shares": old_sh, "prev_wgt": round(old.get("wgt", 0.0), 6)})
            elif cur and cur_sh and not (old and old_sh):
                added.append({**lbl, "shares": cur_sh, "wgt": round(cur.get("wgt", 0.0), 6)})
            elif cur and old:
                d_sh = cur_sh - old_sh
                if d_sh:
                    rebalanced.append({**lbl, "delta_shares": d_sh,
                                       "delta_wgt": round(cur.get("wgt", 0.0) - old.get("wgt", 0.0), 6)})
        rebalanced.sort(key=lambda x: abs(x["delta_shares"]), reverse=True)
        rebalanced = rebalanced[:5]                           # |Δshares| 상위 5
        exited.sort(key=lambda x: x["prev_wgt"], reverse=True)
        added.sort(key=lambda x: x["wgt"], reverse=True)

    # M7(매그니피센트 7) 비중 + 집중도: 이미 모은 by_cusip(분기별 pts)에서 재계산(추가 쿼리 X).
    # M7 판정은 raw cusip 또는 _SHARE_CLASS_MERGE 정규화 cusip 가 M7_CUSIPS 에 들면 포함.
    m7_series = []
    concentration = []
    for p in periods:
        m7_wgt = 0.0
        wgts = []
        for cu, d in by_cusip.items():
            pt = d["pts"].get(p)
            if not pt:
                continue
            w = pt.get("wgt", 0.0) or 0.0
            wgts.append(w)
            if cu in M7_CUSIPS or _SHARE_CLASS_MERGE.get(cu, cu) in M7_CUSIPS:
                m7_wgt += w
        m7_series.append({"period": p, "weight": round(m7_wgt, 6)})
        wgts.sort(reverse=True)
        concentration.append({"period": p,
                              "top5": round(sum(wgts[:5]), 6),
                              "top10": round(sum(wgts[:10]), 6),
                              "max_single": round(wgts[0], 6) if wgts else 0.0})
    m7_delta_pp = (round(m7_series[-1]["weight"] - m7_series[-2]["weight"], 6)
                   if len(periods) >= 2 else None)

    return {"watch_cik": watch_cik, "watch_name": watch_name,
            "guru": guru_label(watch_cik), "periods": periods,
            "series": series, "all_holdings": all_holdings,
            "highlights": {"exited": exited, "added": added,
                           "rebalanced": rebalanced},
            "m7": {"series": m7_series, "delta_pp": m7_delta_pp},
            "concentration": concentration,
            "insufficient_history": len(periods) < 2, "put_call_excluded": True}


def compute_investor_turnover(watch_cik: str, quarters: int = 5,
                              top_n: int = 5) -> dict | None:
    """기관 1곳의 분기별 비중회전율(Σ|Δwgt|/2) 시계열 + 부산물.

    - `_LATEST_13F_CTE` 재사용으로 13F-HR/A 중복 방어. 최근 `quarters` 분기 사용
      (5개 미만이면 가용분기만 + partial=True).
    - cusip 단위 SUM 집계(value, shares), put_call 제외 — `portfolio_investor` 와
      동일 규칙. 집계 전 cusip 을 `_SHARE_CLASS_MERGE` 로 치환(보통주 복수클래스 병합).
    - wgt = value / Σvalue(분기별). turnover = Σ|Δwgt|/2 (연속 분기쌍, 최대 4개 QoQ).
    - 정렬 점수 = 최신 분기쌍(Q-1→Q) QoQ turnover.
    - 2개 분기 미만이라 점수 계산 불가면 None 반환(호출측이 excluded 처리).
    """
    with _conn() as c:
        name_row = c.execute(
            "SELECT watch_name FROM filings WHERE watch_cik=? AND form_type='13F' "
            "ORDER BY filing_date DESC LIMIT 1", (watch_cik,)).fetchone()
        watch_name = name_row["watch_name"] if name_row else ""

        # 완전성 가드용 여유분(quarters+3)을 받아 부실분기 제거 후 최근 quarters 사용.
        # 단일 투자자 CTE 로 윈도우/조인 전 watch_cik 선별 → 풀스캔 회피(첫 바인드=watch_cik).
        cand_periods = [r["period_of_report"] for r in c.execute(
            _LATEST_13F_CTE_ONE +
            "SELECT period_of_report FROM latest_13f WHERE rn=1 "
            "ORDER BY period_of_report DESC LIMIT ?",
            (watch_cik, quarters + 3)).fetchall()]
        cand_periods = sorted(p for p in cand_periods if p)    # 오름차순 축
        if len(cand_periods) < 2:
            return None

        rows = c.execute(
            _LATEST_13F_CTE_ONE +
            f"""SELECT l.period_of_report AS period, h.cusip AS cusip,
                       h.name_of_issuer AS name_of_issuer,
                       h.value AS value, h.shares AS shares,
                       r.name AS ref_name, r.ticker AS ticker
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                LEFT JOIN cusip_ref r ON r.cusip = h.cusip
                WHERE l.rn=1
                  AND l.period_of_report IN ({','.join('?' * len(cand_periods))})
                  AND COALESCE(h.put_call,'')=''""",
            (watch_cik, *cand_periods)).fetchall()

    # 분기 → cusip(병합 대표) → {value, shares, name, ticker} 로 SUM 집계
    by_period: dict[str, dict[str, dict]] = {p: {} for p in cand_periods}
    for r in rows:
        cu = _SHARE_CLASS_MERGE.get(r["cusip"], r["cusip"])
        bucket = by_period[r["period"]]
        d = bucket.setdefault(cu, {"cusip": cu, **_label(r),
                                   "value": 0.0, "shares": 0.0})
        if not d["name"]:
            d.update(_label(r))
        d["value"] += r["value"] or 0.0
        d["shares"] += r["shares"] or 0.0

    # 완전성 가드: 보유종목수가 자기 중앙값의 50% 미만(또는 5종목 미만)인 분기는 부실(부분
    # 크롤)로 보고 시계열에서 제외. 미제외 시 4종목 분기가 인접 풀분기와 diff 되며 가짜
    # ~99% turnover 를 만든다(예: Berkshire 2025-03-31 = 4종목 vs 인접 ~41종목).
    counts = {p: len(by_period[p]) for p in cand_periods}
    _ord = sorted(counts.values())
    _m = len(_ord)
    median_cnt = _ord[_m // 2] if _m % 2 else (_ord[_m // 2 - 1] + _ord[_m // 2]) / 2
    floor = max(5, 0.5 * median_cnt)
    dropped_periods = [p for p in cand_periods if counts[p] < floor]
    periods = [p for p in cand_periods if counts[p] >= floor][-quarters:]
    if len(periods) < 2:
        return None

    # 분기별 wgt = value / Σvalue
    wgt_by_period: dict[str, dict[str, float]] = {}
    for p in periods:
        tot = sum(d["value"] for d in by_period[p].values()) or 0.0
        wgt_by_period[p] = ({cu: (d["value"] / tot) for cu, d in by_period[p].items()}
                            if tot > 0 else {})

    # 연속 분기쌍마다 turnover = Σ|Δwgt|/2 (한쪽 0 처리 = outer union)
    qoq_series = []
    for prev, curr in zip(periods[:-1], periods[1:]):
        wp, wc = wgt_by_period[prev], wgt_by_period[curr]
        union = set(wp) | set(wc)
        turnover = sum(abs(wc.get(cu, 0.0) - wp.get(cu, 0.0)) for cu in union) / 2
        qoq_series.append({"prev_period": prev, "curr_period": curr,
                           "turnover": round(turnover, 6)})

    latest = periods[-1]
    prev = periods[-2]
    score = qoq_series[-1]["turnover"]

    # 최신 분기쌍 기준 신규/청산 + Top 매수/매도(Δwgt 상하위 N)
    wp, wc = wgt_by_period[prev], wgt_by_period[latest]
    union = set(wp) | set(wc)
    new_count = sum(1 for cu in union if wc.get(cu, 0.0) > 0 and not wp.get(cu, 0.0))
    exited_count = sum(1 for cu in union if wp.get(cu, 0.0) > 0 and not wc.get(cu, 0.0))

    def _chip(cu: str) -> dict:
        ref = by_period[latest].get(cu) or by_period[prev].get(cu) or {"cusip": cu}
        return {"cusip": cu, "name": ref.get("name", ""), "ticker": ref.get("ticker"),
                "delta_wgt": round(wc.get(cu, 0.0) - wp.get(cu, 0.0), 6)}
    deltas = sorted((_chip(cu) for cu in union),
                    key=lambda x: x["delta_wgt"], reverse=True)
    top_buys = [d for d in deltas if d["delta_wgt"] > 0][:top_n]
    top_sells = [d for d in reversed(deltas) if d["delta_wgt"] < 0][:top_n]

    # total_value: 최신 분기, 표시용 → accession(분기) 단위 금액보정 적용
    factor = _money_factor(rows)
    total_value = sum(d["value"] for d in by_period[latest].values()) * factor

    return {
        "watch_cik": watch_cik, "watch_name": watch_name, "score": score,
        "qoq_series": qoq_series, "latest_pair": {"prev": prev, "curr": latest},
        "new_count": new_count, "exited_count": exited_count,
        "top_buys": top_buys, "top_sells": top_sells,
        "total_value": total_value,
        "partial": len(periods) < quarters,
        "put_call_excluded": True,
    }


def portfolio_investee(cusips: list[str], quarters: int = 4) -> dict:
    """종목(cusip) 1개(또는 동일발행사 복수 share class)를 보유한 감시 기관별 금액 시계열."""
    cusips = [c for c in (cusips or []) if c]
    if not cusips:
        return {"cusips": [], "name": "", "periods": [], "holders": [], "scope": "watched"}
    ph = ",".join("?" * len(cusips))
    with _conn() as c:
        nm = c.execute(f"SELECT name FROM cusip_ref WHERE cusip IN ({ph}) AND name!='' LIMIT 1",
                       cusips).fetchone()
        name = nm["name"] if nm else ""
        rows = c.execute(
            _LATEST_13F_CTE +
            f"""SELECT l.watch_cik AS watch_cik, l.watch_name AS watch_name,
                       l.period_of_report AS period,
                       SUM(h.value) AS value, SUM(h.shares) AS shares,
                       SUM(h.wgt) AS wgt
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                WHERE l.rn=1 AND h.cusip IN ({ph})
                  AND COALESCE(h.put_call,'')=''
                GROUP BY l.watch_cik, l.period_of_report""",
            cusips).fetchall()

    all_periods = sorted({r["period"] for r in rows if r["period"]})[-quarters:]
    pset = set(all_periods)
    holders: dict[str, dict] = {}
    for r in rows:
        if r["period"] not in pset:
            continue
        h = holders.setdefault(r["watch_cik"],
                               {"watch_cik": r["watch_cik"], "watch_name": r["watch_name"], "pts": {}})
        h["pts"][r["period"]] = {"value": r["value"] or 0.0, "shares": r["shares"] or 0.0,
                                 "wgt": round(r["wgt"] or 0.0, 6)}
    holder_list = [{"watch_cik": h["watch_cik"], "watch_name": h["watch_name"],
                    "points": [{"period": p, **(h["pts"].get(p) or {"value": 0.0, "shares": 0.0, "wgt": 0.0})}
                               for p in all_periods]}
                   for h in holders.values()]
    holder_list.sort(key=lambda h: (h["points"][-1]["value"] if h["points"] else 0), reverse=True)
    return {"cusips": cusips, "name": name, "periods": all_periods,
            "holders": holder_list, "scope": "watched", "put_call_excluded": True}


# ── 거장 합의/확신 (cross-guru consensus) ─────────────────────

def guru_consensus(ciks: list[str], quarters: int = 2, top_n: int = 20) -> dict:
    """감시 13F 투자자(거장) 집합의 교차 보유 합의 + 분기 매수/매도 합의.

    - `_LATEST_13F_CTE`(rn=1) 로 13F-HR/A 중복 방어, watch_cik IN (...) 로 모집단 한정.
    - 최신/직전 period 를 모집단 전체에서 결정. 최신 분기: cusip(_SHARE_CLASS_MERGE 병합)
      별 보유 거장 수(holders)와 conviction_pct = holders/N.
    - QoQ(직전→최신): 거장별 보유 shares 를 두 분기 비교해 신규/증가=buyers, 감소/청산=
      sellers, net = buyers - sellers.
    - 효율: 필요한 ≤quarters 분기 행(watch_cik, period, cusip, shares, value, name +
      cusip_ref 조인)을 단일 쿼리로 끌어와 파이썬에서 집계(compute_investor_turnover 방식).
    """
    ciks = [c for c in (ciks or []) if c]
    n = len(ciks)
    if not ciks:
        return {"n_investors": 0, "latest_period": None, "prev_period": None,
                "consensus_holdings": [], "consensus_buys": [], "consensus_sells": [],
                "insufficient_history": True}

    ph = ",".join("?" * len(ciks))
    with _conn() as c:
        periods = [r["period_of_report"] for r in c.execute(
            _LATEST_13F_CTE +
            f"SELECT DISTINCT period_of_report FROM latest_13f "
            f"WHERE rn=1 AND watch_cik IN ({ph}) "
            f"ORDER BY period_of_report DESC LIMIT ?",
            (*ciks, quarters)).fetchall() if r["period_of_report"]]
        if not periods:
            return {"n_investors": n, "latest_period": None, "prev_period": None,
                    "consensus_holdings": [], "consensus_buys": [],
                    "consensus_sells": [], "insufficient_history": True}

        latest = periods[0]
        prev = periods[1] if len(periods) >= 2 else None
        use_periods = [p for p in (latest, prev) if p]

        rows = c.execute(
            _LATEST_13F_CTE +
            f"""SELECT l.watch_cik AS watch_cik, l.period_of_report AS period,
                       h.cusip AS cusip, h.name_of_issuer AS name_of_issuer,
                       h.value AS value, h.shares AS shares,
                       r.name AS ref_name, r.ticker AS ticker
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                LEFT JOIN cusip_ref r ON r.cusip = h.cusip
                WHERE l.rn=1 AND l.watch_cik IN ({ph})
                  AND l.period_of_report IN ({','.join('?' * len(use_periods))})
                  AND COALESCE(h.put_call,'')=''""",
            (*ciks, *use_periods)).fetchall()

    # (period, merged_cusip) → {guru_cik → shares 합}, + 라벨/value 합산
    # label[cu] = {name, ticker}; per[(period, cu)][watch_cik] = Σshares
    per: dict[tuple, dict[str, float]] = {}
    label: dict[str, dict] = {}
    for r in rows:
        cu = _SHARE_CLASS_MERGE.get(r["cusip"], r["cusip"])
        lbl = label.setdefault(cu, {"cusip": cu, **_label(r)})
        if not lbl["name"]:
            lbl.update({k: v for k, v in _label(r).items() if k in ("name", "ticker")})
            lbl["cusip"] = cu
        bucket = per.setdefault((r["period"], cu), {})
        bucket[r["watch_cik"]] = bucket.get(r["watch_cik"], 0.0) + (r["shares"] or 0.0)

    # 최신 분기 합의 보유 (holders = 보유 거장 수)
    consensus_holdings = []
    for cu in {c for (p, c) in per if p == latest}:
        holders = sum(1 for sh in per.get((latest, cu), {}).values() if sh > 0)
        if holders <= 0:
            continue
        lbl = label.get(cu, {"cusip": cu, "name": "", "ticker": None})
        consensus_holdings.append({
            "cusip": cu, "name": lbl["name"], "ticker": lbl["ticker"],
            "holders": holders, "conviction_pct": round(holders / n, 6) if n else 0.0})
    consensus_holdings.sort(key=lambda x: x["holders"], reverse=True)
    consensus_holdings = consensus_holdings[:top_n]

    # QoQ 매수/매도 합의 (거장별 shares 비교)
    consensus_buys, consensus_sells = [], []
    if prev:
        all_cus = {c for (p, c) in per}
        scored = []
        for cu in all_cus:
            cur_map = per.get((latest, cu), {})
            old_map = per.get((prev, cu), {})
            gurus_in = set(cur_map) | set(old_map)
            buyers = sellers = 0
            for g in gurus_in:
                cs = cur_map.get(g, 0.0)
                os_ = old_map.get(g, 0.0)
                if cs > os_:
                    buyers += 1
                elif cs < os_:
                    sellers += 1
            net = buyers - sellers
            lbl = label.get(cu, {"cusip": cu, "name": "", "ticker": None})
            scored.append({"cusip": cu, "name": lbl["name"], "ticker": lbl["ticker"],
                           "buyers": buyers, "sellers": sellers, "net": net})
        buys = sorted((s for s in scored if s["net"] > 0),
                      key=lambda x: x["net"], reverse=True)
        sells = sorted((s for s in scored if s["net"] < 0), key=lambda x: x["net"])
        consensus_buys = buys[:top_n]
        consensus_sells = sells[:top_n]

    return {"n_investors": n, "latest_period": latest, "prev_period": prev,
            "consensus_holdings": consensus_holdings,
            "consensus_buys": consensus_buys, "consensus_sells": consensus_sells,
            "insufficient_history": prev is None}


# ── 포지션 변동 테이블 (단일 투자자, 직전 vs 최신) ──────────────

def position_changes(watch_cik: str, prev: str | None = None,
                     curr: str | None = None) -> dict:
    """투자자 1곳의 두 분기(직전→최신) 포지션 변동 테이블.

    - `_LATEST_13F_CTE_ONE`(첫 바인드=watch_cik) 로 풀스캔 회피 + 13F-HR/A 중복 방어.
    - prev/curr 미지정 시 해당 투자자의 가용 최신 2개 분기 사용.
    - 두 분기를 병합 cusip(_SHARE_CLASS_MERGE, put_call 제외) full-outer-join.
      분기별 wgt = value / Σvalue. status: new/exited/increased/decreased/unchanged.
    """
    with _conn() as c:
        name_row = c.execute(
            "SELECT watch_name FROM filings WHERE watch_cik=? AND form_type='13F' "
            "ORDER BY filing_date DESC LIMIT 1", (watch_cik,)).fetchone()
        watch_name = name_row["watch_name"] if name_row else ""

        if not (prev and curr):
            avail = [r["period_of_report"] for r in c.execute(
                _LATEST_13F_CTE_ONE +
                "SELECT period_of_report FROM latest_13f WHERE rn=1 "
                "ORDER BY period_of_report DESC LIMIT 2",
                (watch_cik,)).fetchall() if r["period_of_report"]]
            if len(avail) >= 2:
                curr, prev = avail[0], avail[1]
            elif len(avail) == 1:
                curr, prev = avail[0], None
            else:
                curr, prev = None, None

        if not curr:
            return {"watch_cik": watch_cik, "watch_name": watch_name,
                    "prev_period": prev, "curr_period": curr, "rows": [],
                    "insufficient_history": True}

        use_periods = [p for p in (prev, curr) if p]
        rows = c.execute(
            _LATEST_13F_CTE_ONE +
            f"""SELECT l.period_of_report AS period, h.cusip AS cusip,
                       h.name_of_issuer AS name_of_issuer,
                       h.value AS value, h.shares AS shares,
                       r.name AS ref_name, r.ticker AS ticker
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                LEFT JOIN cusip_ref r ON r.cusip = h.cusip
                WHERE l.rn=1
                  AND l.period_of_report IN ({','.join('?' * len(use_periods))})
                  AND COALESCE(h.put_call,'')=''""",
            (watch_cik, *use_periods)).fetchall()

    # period → cusip(병합) → {value, shares} 합산 + 라벨
    by_period: dict[str, dict[str, dict]] = {p: {} for p in use_periods}
    label: dict[str, dict] = {}
    for r in rows:
        cu = _SHARE_CLASS_MERGE.get(r["cusip"], r["cusip"])
        lbl = label.setdefault(cu, {"cusip": cu, **_label(r)})
        if not lbl["name"]:
            lbl.update(_label(r))
            lbl["cusip"] = cu
        bucket = by_period[r["period"]].setdefault(cu, {"value": 0.0, "shares": 0.0})
        bucket["value"] += r["value"] or 0.0
        bucket["shares"] += r["shares"] or 0.0

    cur_map = by_period.get(curr, {})
    old_map = by_period.get(prev, {}) if prev else {}
    cur_tot = sum(d["value"] for d in cur_map.values()) or 0.0
    old_tot = sum(d["value"] for d in old_map.values()) or 0.0
    factor = _money_factor(rows)            # 13F 천달러/달러 단위 보정(표시용 금액 전용)

    def _pct(chg: float, base: float) -> float | None:
        return round(chg / base, 6) if base else None

    out_rows = []
    for cu in set(cur_map) | set(old_map):
        cd = cur_map.get(cu)
        od = old_map.get(cu)
        v_cur = cd["value"] if cd else 0.0
        v_old = od["value"] if od else 0.0
        s_cur = cd["shares"] if cd else 0.0
        s_old = od["shares"] if od else 0.0
        w_cur = (v_cur / cur_tot) if cur_tot else 0.0
        w_old = (v_old / old_tot) if old_tot else 0.0
        if cd and not od:
            status = "new"
        elif od and not cd:
            status = "exited"
        elif s_cur > s_old:
            status = "increased"
        elif s_cur < s_old:
            status = "decreased"
        else:
            status = "unchanged"
        lbl = label.get(cu, {"cusip": cu, "name": "", "ticker": None})
        out_rows.append({
            "cusip": cu, "name": lbl["name"], "ticker": lbl["ticker"], "status": status,
            "value_prev": v_old * factor, "value_curr": v_cur * factor,
            "value_chg": (v_cur - v_old) * factor,
            "value_chg_pct": _pct(v_cur - v_old, v_old),
            "shares_prev": s_old, "shares_curr": s_cur, "shares_chg": s_cur - s_old,
            "shares_chg_pct": _pct(s_cur - s_old, s_old),
            "wgt_prev": round(w_old, 6), "wgt_curr": round(w_cur, 6),
            "wgt_chg": round(w_cur - w_old, 6)})
    out_rows.sort(key=lambda x: x["value_chg"], reverse=True)

    return {"watch_cik": watch_cik, "watch_name": watch_name,
            "prev_period": prev, "curr_period": curr, "rows": out_rows,
            "insufficient_history": prev is None}
