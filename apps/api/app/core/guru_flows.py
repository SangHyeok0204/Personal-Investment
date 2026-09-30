"""거장 13F 분기 변동 분석 — 동시 편입/방출 · 동시 리밸런싱 · 섹터 이동 · 내 보유 × 거장 (계획 A5).

원본 `apps/collector/collector/guru_flows.py`(= 13F기관내부자 `src/flows.py` 벤더 사본)를 옮겼다.
계산 규칙은 그대로 두고, 바꾼 것은 이것뿐이다:
  - ★정정공시: 원본 `_LATEST_13F_CTE`("분기마다 가장 늦은 공시 하나")는 버그다 — 버크셔 2023Q3 이
    1종목 · 100% 가 됐다. `guru13f.effective_accessions`(RESTATEMENT 대체 / NEW HOLDINGS 합산)로 바꿨다.
  - ★금액 단위는 **공시(접수번호)마다** 보정한다(value/shares 중앙값 < 1 → ×1000). 원본은 분기 안에서
    비중만 냈으므로 단위를 몰라도 됐지만, 원 공시(천 달러) + 추가분(달러)을 합치면 섞인다.
  - 거장 수는 코드에 적지 않고 **명단(`guru_roster`)에서 센다**(계획 A — 거장 추가 대비).
  - 채권(PRN)도 뺀다(원본은 옵션만 뺐다).
  - SQLite · 모듈 전역 캐시 대신, 불러온 데이터(`GuruData`)를 받는 **순수 함수**로 — 시험이 쉽다.

설계 전제(원본 머리말에서 — 어기면 숫자가 조용히 틀린다):
  - 절대 금액을 거장 간에 더하지 않는다. 거장×분기 안에서 비중(bp, 합 10000)으로만 비교한다.
  - 두 분기 모두 낸 거장만 변동 계산에 넣는다(한 분기 빠진 거장의 전 종목이 '신규'로 잡히지 않게).
    ⚠️직전 보유를 **이월하지 않는다**(계획 §D-0) — 안 낸 분기는 비어 있다.
  - 제출률 50% 미만인 분기는 비교에서 건너뛴다(마감 전 1명짜리 "합의" 방지 — 정족수).
  - 13F 는 롱 온리 · 분기말 +45일 공시다. '최근'은 공시 기준 최신이다.

★기술(descriptive) 도구다. 예측 도구가 아니다 — 시그널 24조합 이벤트 스터디 통과 0
  (`docs/guru-13f-flows.md`). 화면은 "무슨 일이 있었나"만 보여 준다.
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

MOVE_MIN_BP = 10.0          # 반올림 노이즈와 실제 조정을 가르는 최소 비중 변화
QUORUM = 0.5                # 제출률 정족수
UNCLASSIFIED = "미분류"

# 같은 회사의 주식 클래스는 합친다(원본 `_SHARE_CLASS_MERGE`).
SHARE_CLASS_MERGE = {
    "02079K107": "02079K305",  # GOOG → GOOGL
    "084670702": "084670108",  # BRK.B → BRK.A
}
# 티커로 찾을 때도 같은 규칙(내 보유 GOOG ↔ 거장 GOOGL).
TICKER_MERGE = {"GOOG": "GOOGL", "BRK-B": "BRK-A", "BRK.B": "BRK-A"}

_SECTOR_CSV = Path(__file__).resolve().parents[1] / "assets" / "guru_sector_map.csv"


@dataclass
class GuruData:
    gurus: dict[str, dict]                                   # cik → {guru, firm}
    mat: dict[tuple[date, str], dict[str, float]]           # (분기, cik) → {종목키: bp}
    label: dict[str, dict] = field(default_factory=dict)     # 종목키 → {cusip, name, ticker}
    warnings: list[str] = field(default_factory=list)


def quarter_label(d: date) -> str:
    return f"{d.year % 100:02d}Q{(d.month - 1) // 3 + 1}"


def value_scale(rows: list[tuple[float | None, float | None]]) -> float:
    """한 공시의 (value, shares) → 금액 배율. 천 달러 단위면 1000(원본 `_money_factor` 규칙)."""
    ratios = [v / s for v, s in rows if v and s and s > 0]
    return 1000.0 if ratios and statistics.median(ratios) < 1 else 1.0


def normalize(books: dict[tuple[date, str], dict[str, float]]) -> dict[tuple[date, str], dict[str, float]]:
    """금액 → 거장×분기 안의 비중(bp). 합이 0 이하인 묶음은 버린다."""
    out = {}
    for key, book in books.items():
        tot = sum(book.values())
        if tot > 0:
            out[key] = {k: v / tot * 10000.0 for k, v in book.items()}
    return out


# ── 분기 고르기 · 정족수 ──────────────────────────────────────────────────────


def filed_by_period(data: GuruData) -> list[tuple[date, int]]:
    n: dict[date, int] = defaultdict(int)
    for (p, cik) in data.mat:
        if cik in data.gurus:
            n[p] += 1
    return sorted(n.items(), key=lambda x: x[0], reverse=True)


def period_meta(data: GuruData) -> list[dict]:
    total = len(data.gurus) or 1
    return [{"period": p.isoformat(), "label": quarter_label(p), "n_filed": k, "n_gurus": len(data.gurus),
             "filed_pct": round(k / total * 100, 1), "usable": k / total >= QUORUM}
            for p, k in filed_by_period(data)]


def usable_periods(data: GuruData) -> list[date]:
    """정족수를 넘긴 분기(최신순). ★그냥 '최신 두 분기'를 쓰면 마감 전 1명짜리 합의가 된다."""
    total = len(data.gurus) or 1
    return [p for p, k in filed_by_period(data) if k / total >= QUORUM]


def participants(data: GuruData, curr: date, prev: date) -> list[str]:
    return [k for k in data.gurus if (curr, k) in data.mat and (prev, k) in data.mat]


def _g(data: GuruData, cik: str) -> dict:
    return {"cik": cik, **data.gurus.get(cik, {"guru": cik, "firm": ""})}


def _lbl(data: GuruData, key: str) -> dict:
    return data.label.get(key, {"cusip": key, "name": "", "ticker": None})


# ── 동시 편입 / 전량 방출 ──────────────────────────────────────────────────────


def entries_exits(data: GuruData, curr: date, prev: date) -> dict:
    parts = participants(data, curr, prev)
    ent: dict[str, dict] = defaultdict(lambda: {"n": 0, "bp": 0.0, "gurus": []})
    ext: dict[str, dict] = defaultdict(lambda: {"n": 0, "bp": 0.0, "gurus": []})
    for k in parts:
        cur, old = data.mat[(curr, k)], data.mat[(prev, k)]
        for key in set(cur) - set(old):
            e = ent[key]
            e["n"] += 1
            e["bp"] += cur[key]
            e["gurus"].append({**_g(data, k), "bp": round(cur[key], 1)})
        for key in set(old) - set(cur):
            e = ext[key]
            e["n"] += 1
            e["bp"] += old[key]
            e["gurus"].append({**_g(data, k), "bp": round(old[key], 1)})

    def pack(d):
        rows = [{**_lbl(data, key), "key": key, "n_gurus": e["n"], "total_bp": round(e["bp"], 1),
                 "gurus": sorted(e["gurus"], key=lambda x: -x["bp"])} for key, e in d.items()]
        rows.sort(key=lambda r: (-r["n_gurus"], -r["total_bp"]))
        return rows

    return {"n_participants": len(parts), "entries": pack(ent), "exits": pack(ext)}


# ── 동시 리밸런싱 ─────────────────────────────────────────────────────────────


def _action(a: float, b: float) -> str:
    if a <= 0 < b:
        return "new"
    if b <= 0 < a:
        return "exited"
    return "increased" if b > a else "decreased"


def rebalance(data: GuruData, curr: date, prev: date, min_bp: float = MOVE_MIN_BP) -> list[dict]:
    """여러 거장이 동시에 크게 조정한 종목. gross(총량)와 net(순방향)을 함께 — agreement 가 낮으면 '분열'."""
    agg: dict[str, dict] = defaultdict(lambda: {"movers": 0, "buyers": 0, "sellers": 0, "gross": 0.0,
                                                "net": 0.0, "by_guru": []})
    for k in participants(data, curr, prev):
        cur, old = data.mat[(curr, k)], data.mat[(prev, k)]
        for key in set(cur) | set(old):
            a, b = old.get(key, 0.0), cur.get(key, 0.0)
            d = b - a
            if abs(d) < min_bp:
                continue
            e = agg[key]
            e["movers"] += 1
            e["gross"] += abs(d)
            e["net"] += d
            e["buyers" if d > 0 else "sellers"] += 1
            e["by_guru"].append({**_g(data, k), "prev_bp": round(a, 1), "curr_bp": round(b, 1),
                                 "delta_bp": round(d, 1), "action": _action(a, b)})
    rows = [{**_lbl(data, key), "key": key, "movers": e["movers"], "buyers": e["buyers"], "sellers": e["sellers"],
             "gross_bp": round(e["gross"], 1), "net_bp": round(e["net"], 1),
             "agreement": round(abs(e["net"]) / e["gross"], 3) if e["gross"] else 0.0,
             "by_guru": sorted(e["by_guru"], key=lambda x: -abs(x["delta_bp"]))}
            for key, e in agg.items()]
    rows.sort(key=lambda r: (-r["movers"], -r["gross_bp"]))
    return rows


# ── 섹터 ─────────────────────────────────────────────────────────────────────


def load_sector_map(path: Path = _SECTOR_CSV) -> tuple[dict[str, str], dict[str, str]]:
    """(CUSIP → 섹터, 티커 → 섹터). 원본 수기 CSV(최신 분기 상위 종목) — CUSIP 이 우선, 없으면 티커로."""
    by_cusip: dict[str, str] = {}
    by_ticker: dict[str, str] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sec = (row.get("sector") or "").strip()
                if not sec:
                    continue
                cu = (row.get("cusip") or "").strip().upper()
                tk = (row.get("ticker") or "").strip().upper()
                if cu:
                    by_cusip[cu] = sec
                if tk:
                    by_ticker[tk] = sec
    return by_cusip, by_ticker


def sector_of(data: GuruData, key: str, smap: tuple[dict, dict]) -> str:
    """CSV(CUSIP → 티커) 먼저, 없으면 SEC SIC 로 정한 섹터(`cusip_map.sector`, 0023), 그래도 없으면 미분류."""
    by_cusip, by_ticker = smap
    if key.upper() in by_cusip:
        return by_cusip[key.upper()]
    lb = _lbl(data, key)
    tk = (lb.get("ticker") or "").upper()
    return by_ticker.get(tk) or lb.get("sector") or UNCLASSIFIED


def sector_flows(data: GuruData, curr: date, prev: date, smap: tuple[dict, dict]) -> dict:
    """섹터 비중 이동(거장 평균 bp). 거장마다 섹터 비중을 먼저 만든 뒤 차이를 낸다.

    ★미분류는 숨기지 않는다. 그리고 커버리지를 **분기별로** 잰다 — 두 분기 커버리지가 다르면 그 차이가
      '미분류 대량 이동'으로 둔갑한다(원본 실측: 격차 6.4%p = 가짜 −640bp). 격차 ≥ 1%p 면 미분류 순변화는 믿지 않는다.
    """
    parts = participants(data, curr, prev)
    n = len(parts)
    if not n:
        return {"n_participants": 0, "rows": [], "coverage_curr": None, "coverage_prev": None,
                "unclassified_unreliable": False}

    def cov(p):
        hit = tot = 0.0
        for k in parts:
            for key, w in data.mat[(p, k)].items():
                tot += w
                hit += w if sector_of(data, key, smap) != UNCLASSIFIED else 0.0
        return round(hit / tot * 100, 1) if tot else 0.0

    agg: dict[str, dict] = defaultdict(lambda: {"net": 0.0, "curr": 0.0, "prev": 0.0, "up": 0, "down": 0,
                                                "names": defaultdict(float)})
    for k in parts:
        cur_s: dict[str, float] = defaultdict(float)
        old_s: dict[str, float] = defaultdict(float)
        for key, w in data.mat[(curr, k)].items():
            cur_s[sector_of(data, key, smap)] += w
        for key, w in data.mat[(prev, k)].items():
            old_s[sector_of(data, key, smap)] += w
        for sec in set(cur_s) | set(old_s):
            d = cur_s[sec] - old_s[sec]
            e = agg[sec]
            e["net"] += d
            e["curr"] += cur_s[sec]
            e["prev"] += old_s[sec]
            if abs(d) >= MOVE_MIN_BP:
                e["up" if d > 0 else "down"] += 1
        for key in set(data.mat[(curr, k)]) | set(data.mat[(prev, k)]):
            d = data.mat[(curr, k)].get(key, 0.0) - data.mat[(prev, k)].get(key, 0.0)
            if abs(d) >= MOVE_MIN_BP:
                agg[sector_of(data, key, smap)]["names"][key] += d
    cc, cp = cov(curr), cov(prev)
    rows = [{"sector": sec, "net_bp": round(e["net"] / n, 1),        # 거장 평균 — 합치면 거장 수만큼 부푼다
             "curr_wgt_bp": round(e["curr"] / n, 1), "prev_wgt_bp": round(e["prev"] / n, 1),
             "up": e["up"], "down": e["down"],
             "top": [{**_lbl(data, key), "delta_bp": round(d / n, 1)}
                     for key, d in sorted(e["names"].items(), key=lambda x: -abs(x[1]))[:5]]}
            for sec, e in agg.items()]
    rows.sort(key=lambda r: (r["sector"] == UNCLASSIFIED, -abs(r["net_bp"])))
    return {"n_participants": n, "rows": rows, "coverage_curr": cc, "coverage_prev": cp,
            "unclassified_unreliable": abs(cc - cp) >= 1.0}


# ── 내 보유 × 거장 ────────────────────────────────────────────────────────────


def keys_for_ticker(data: GuruData, ticker: str) -> set[str]:
    t = TICKER_MERGE.get(ticker.upper(), ticker.upper())
    return {k for k, lb in data.label.items() if TICKER_MERGE.get((lb.get("ticker") or "").upper(),
                                                                  (lb.get("ticker") or "").upper()) == t}


def my_holdings(data: GuruData, curr: date, prev: date | None, tickers: list[tuple[str, str | None]]) -> list[dict]:
    """내 보유 종목마다: 든 거장 수(curr 에 낸 거장 중) · 거장 평균 비중 · 직전 대비(두 분기 모두 낸 거장만)."""
    filers = [k for k in data.gurus if (curr, k) in data.mat]
    parts = participants(data, curr, prev) if prev else []
    out = []
    for ticker, name in tickers:
        keys = keys_for_ticker(data, ticker)
        w_curr = {k: sum(data.mat[(curr, k)].get(x, 0.0) for x in keys) for k in filers}
        holders = sorted(({**_g(data, k), "bp": round(w, 1)} for k, w in w_curr.items() if w > 0),
                         key=lambda x: -x["bp"])
        delta = None
        if parts:
            delta = round(sum(sum(data.mat[(curr, k)].get(x, 0.0) - data.mat[(prev, k)].get(x, 0.0) for x in keys)
                              for k in parts) / len(parts), 1)
        out.append({"ticker": ticker, "name": name, "n_gurus": len(holders),
                    "avg_bp": round(sum(w_curr.values()) / len(filers), 1) if filers else None,
                    "delta_bp": delta, "holders": holders})
    out.sort(key=lambda r: (-r["n_gurus"], -(r["avg_bp"] or 0)))
    return out


def stock_trend(data: GuruData, ticker: str, periods: list[date]) -> list[dict]:
    """한 종목 × 거장별 분기 비중(bp). 안 낸 분기는 None(0 이 아니다 — 이월하지 않는다)."""
    keys = keys_for_ticker(data, ticker)
    rows = []
    for k in data.gurus:
        pts = [None if (p, k) not in data.mat else round(sum(data.mat[(p, k)].get(x, 0.0) for x in keys), 1)
               for p in periods]
        if any(v for v in pts if v):
            rows.append({**_g(data, k), "points": pts})
    rows.sort(key=lambda r: -max(v or 0 for v in r["points"]))
    return rows
