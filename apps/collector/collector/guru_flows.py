r"""거장 13F 포트폴리오 '변동' 분석 (rebalancing / entry-exit / sector flow).

★[벤더 사본] 이 파일을 여기서 고치지 말 것 (2026-08-11 정본 이전).
  원본 = S:\GE\raw\운용 전략\구루\13F기관내부자\src\flows.py
  분석 산출이 대시보드에서 배치 HTML(`make_report.bat`)로 옮겨가면서 원본이 그쪽으로
  갔다. guru_queries.py 가 그 프로젝트 storage.py 의 원문 복사인 것과 같은 관계다.
  고칠 일이 생기면 원본을 고치고 다시 복사한다. 원본과의 차이는 import 경로
  (`.guru_queries` ↔ `src.storage`/`src.gurus`/`src.normalize`)와 섹터 맵 경로뿐이다.

무엇을 답하는가
  1) 최근 분기에 **여러 거장이 동시에 크게 조정한 종목**은 무엇인가  (rebalance_intensity)
  2) 동시에 **신규 편입 / 전량 방출**된 종목은 무엇인가                (entries_exits)
  3) 종목이 아니라 **섹터 관점**에서 자금이 어디로 옮겨갔나            (sector_flows)

설계 전제 (어기면 숫자가 조용히 틀린다)
  - value 단위 혼재: 13F 원문은 천달러/달러가 섞여 있다(관측 68.7%가 천달러).
    따라서 **절대 value 를 거장 간에 더하지 않는다.** 항상 거장×분기 단위로
    wgt = value / Σvalue 를 재계산해 비중(bp)으로만 비교한다. holdings_13f.wgt
    컬럼이 채워져 있으나 산출 근거를 신뢰하지 않고 여기서 다시 만든다.
  - 13F-HR/A 수정본: 삭제하지 않고 (watch_cik, period) 별 최신 1건만 쓴다.
    guru_queries._LATEST_13F_CTE 를 그대로 재사용한다.
  - 분기 결측: 어떤 거장이 직전 분기를 안 냈으면 그 거장의 모든 종목이 '신규 편입'
    으로 잡힌다. **양 분기 모두 제출한 거장만** 변동 계산에 넣는다(participants).
  - 파생/숏: put_call 이 붙은 행은 제외한다. 13F 는 롱 온리 신고라 매도는
    '보유 감소'로만 관측되며 공매도는 보이지 않는다.
  - 공시 지연: period_of_report 기준 최대 45일 뒤에 공시된다. 여기 나오는 '최근'은
    시장 기준 최신이 아니라 **공시 기준 최신**이다.

★ 이 모듈은 기술(descriptive) 도구다. 예측 도구가 아니다.
  같은 데이터로 만든 시그널 8종 × 호라이즌 3개(총 24조합)를 이벤트 스터디로 검증한
  결과 전부 |t| < 1.7 로 통과 0 이었고, 정보량이 0 인 난수 시그널이 |t| = 1.563 을
  뽑아 실제 최고치(1.681)와 구분되지 않았다. 즉 **"거장들이 동시에 샀다"는 사실에서
  초과수익을 기대할 근거는 확인되지 않았다.** 이 화면은 "무슨 일이 있었나"를 보는
  용도이며, 매매 판단으로 직결시키면 안 된다.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from .guru_queries import (
    _conn,
    _label,
    _LATEST_13F_CTE,
    _SHARE_CLASS_MERGE,
    guru_label,
    pad_cik,
)

# 리밸런싱 '움직임'으로 셀 최소 비중 변화(bp). 반올림 노이즈와 실제 조정을 가른다.
MOVE_MIN_BP = 10.0
# 결과 기본 행 수
TOP_N = 25
# 기준선(baseline) 산출에 쓸 과거 분기 수 (현재 분기 제외)
BASELINE_QUARTERS = 8


# ────────────────────────────────────────────────────────────── 코어

def _filed_by_period(c: sqlite3.Connection, ciks: list[str],
                     limit: int = 12) -> list[tuple[str, int]]:
    """분기별 제출 거장 수를 최신순으로. (period, n_filed)"""
    ph = ",".join("?" * len(ciks))
    rows = c.execute(
        _LATEST_13F_CTE +
        f"SELECT period_of_report AS p, COUNT(DISTINCT watch_cik) AS n "
        f"FROM latest_13f WHERE rn=1 AND watch_cik IN ({ph}) "
        f"AND period_of_report IS NOT NULL "
        f"GROUP BY period_of_report ORDER BY p DESC LIMIT ?",
        (*ciks, limit)).fetchall()
    return [(r["p"], r["n"]) for r in rows]


def pick_periods(c: sqlite3.Connection, ciks: list[str],
                 min_ratio: float = 0.5) -> tuple[str | None, str | None, list[dict]]:
    """비교에 쓸 (최신, 직전) 분기를 고른다.

    ★ 그냥 "최신 2개 분기"를 쓰면 안 된다. 13F 공시기한은 분기말+45일이라
      마감 직전에는 최신 분기 제출률이 한 자릿수다. 실측 2026-08-11 기준
      2026-06-30 분기는 23명 중 1명(4%)만 제출한 상태였고, 이대로 비교하면
      참여 거장 1명짜리 "합의"가 만들어진다.
      → **제출률이 min_ratio 미만인 분기는 건너뛴다.**
    """
    hist = _filed_by_period(c, ciks, limit=12)
    n = len(ciks) or 1
    usable = [(p, k) for p, k in hist if k / n >= min_ratio]
    curr = usable[0][0] if usable else None
    prev = usable[1][0] if len(usable) > 1 else None
    meta = [{"period": p, "n_filed": k, "filed_pct": round(k / n * 100, 1),
             "usable": k / n >= min_ratio} for p, k in hist]
    return curr, prev, meta


def weight_matrix(ciks: list[str], periods: list[str]) -> tuple[dict, dict]:
    """(period, cik) → {cusip: wgt_bp} 행렬과 cusip 라벨을 만든다.

    wgt 는 **거장×분기 안에서** value 비중을 재계산한 값(bp, 만분율)이다.
    거장별 합은 항상 10000 bp 다. 단위 혼재는 이 정규화로 상쇄된다.
    """
    if not ciks or not periods:
        return {}, {}
    ph = ",".join("?" * len(ciks))
    pph = ",".join("?" * len(periods))
    with _conn() as c:
        rows = c.execute(
            _LATEST_13F_CTE +
            f"""SELECT l.watch_cik AS cik, l.period_of_report AS period,
                       h.cusip AS cusip, h.name_of_issuer AS name_of_issuer,
                       h.value AS value, r.name AS ref_name, r.ticker AS ticker
                FROM latest_13f l
                JOIN holdings_13f h ON h.accession_number = l.accession_number
                LEFT JOIN cusip_ref r ON r.cusip = h.cusip
                WHERE l.rn=1 AND l.watch_cik IN ({ph})
                  AND l.period_of_report IN ({pph})
                  AND COALESCE(h.put_call,'')=''""",
            (*ciks, *periods)).fetchall()

    raw: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    label: dict[str, dict] = {}
    for r in rows:
        cu = _SHARE_CLASS_MERGE.get(r["cusip"], r["cusip"])
        lbl = label.get(cu)
        if lbl is None or not lbl.get("name"):
            label[cu] = {"cusip": cu, **_label(r)}
        raw[(r["period"], r["cik"])][cu] += (r["value"] or 0.0)

    mat: dict[tuple, dict[str, float]] = {}
    for key, book in raw.items():
        tot = sum(book.values())
        if tot <= 0:
            continue
        mat[key] = {cu: v / tot * 10000.0 for cu, v in book.items()}
    return mat, label


def _g(cik: str) -> dict:
    """거장 라벨. guru_label() 은 {guru, firm} 을 주며 미등록이면 None 이다."""
    return guru_label(cik) or {"guru": cik, "firm": ""}


def _participants(mat: dict, ciks: list[str], curr: str, prev: str) -> list[str]:
    """두 분기 모두 제출한 거장만 변동 계산에 참여시킨다."""
    return [k for k in ciks if (curr, k) in mat and (prev, k) in mat]


# ────────────────────────────────────────────────── 1) 동시 리밸런싱 강도

def rebalance_intensity(ciks: list[str], curr: str | None = None,
                        prev: str | None = None, top_n: int = TOP_N,
                        min_bp: float = MOVE_MIN_BP,
                        baseline_quarters: int = BASELINE_QUARTERS) -> dict:
    """한 종목을 **여러 거장이 동시에 크게 조정**했는지를 잰다.

    종목별 산출값
      movers        조정한 거장 수 (|Δwgt| >= min_bp)
      buyers/sellers  그중 늘린/줄인 거장 수
      gross_bp      Σ|Δwgt| — 조정의 **총량**. 방향 상쇄 없음
      net_bp        ΣΔwgt   — 조정의 **순방향**
      agreement     |net_bp| / gross_bp — 1이면 전원 같은 방향, 0이면 정확히 갈림
      holders_prev / holders_curr  보유 거장 수(수준)

    ★ gross 와 net 을 반드시 함께 본다. gross 만 크고 agreement 가 낮으면
      "거장들이 서로 반대로 갔다"는 뜻이라 합의가 아니라 **분열**이다.
    """
    ciks = [c for c in (pad_cik(x) for x in (ciks or [])) if c]
    if not ciks:
        return _empty_flow("rebalance")

    pmeta: list[dict] = []
    if not (curr and prev):
        with _conn() as c:
            curr, prev, pmeta = pick_periods(c, ciks)
        if not (curr and prev):
            return _empty_flow("rebalance", periods=[p for p in (curr, prev) if p],
                               period_meta=pmeta)

    mat, label = weight_matrix(ciks, [curr, prev])
    parts = _participants(mat, ciks, curr, prev)
    if not parts:
        return _empty_flow("rebalance", periods=[curr, prev], period_meta=pmeta)

    agg: dict[str, dict] = defaultdict(
        lambda: {"movers": 0, "buyers": 0, "sellers": 0,
                 "gross_bp": 0.0, "net_bp": 0.0,
                 "holders_prev": 0, "holders_curr": 0, "by_guru": []})

    for k in parts:
        cur = mat[(curr, k)]
        old = mat[(prev, k)]
        for cu in set(cur) | set(old):
            a = old.get(cu, 0.0)
            b = cur.get(cu, 0.0)
            d = b - a
            e = agg[cu]
            if a > 0:
                e["holders_prev"] += 1
            if b > 0:
                e["holders_curr"] += 1
            if abs(d) < min_bp:
                continue
            e["movers"] += 1
            e["gross_bp"] += abs(d)
            e["net_bp"] += d
            if d > 0:
                e["buyers"] += 1
            else:
                e["sellers"] += 1
            e["by_guru"].append({
                "cik": k, **_g(k),
                "prev_bp": round(a, 1), "curr_bp": round(b, 1),
                "delta_bp": round(d, 1),
                "action": _action(a, b),
            })

    rows = []
    for cu, e in agg.items():
        if e["movers"] == 0:
            continue
        gross = e["gross_bp"]
        rows.append({
            **label.get(cu, {"cusip": cu, "name": "", "ticker": ""}),
            "movers": e["movers"], "buyers": e["buyers"], "sellers": e["sellers"],
            "gross_bp": round(gross, 1), "net_bp": round(e["net_bp"], 1),
            "agreement": round(abs(e["net_bp"]) / gross, 3) if gross else 0.0,
            "holders_prev": e["holders_prev"], "holders_curr": e["holders_curr"],
            "by_guru": sorted(e["by_guru"], key=lambda x: -abs(x["delta_bp"])),
        })

    # 정렬 1순위 = 조정한 거장 수, 2순위 = 총 조정량. "동시에 많이"라는 질문 그대로.
    rows.sort(key=lambda r: (-r["movers"], -r["gross_bp"]))
    out = rows[:top_n]

    # 평소 대비 이례성. 상위 행에만 붙인다(전체에 붙일 이유가 없고 payload 만 커진다).
    bmeta = {"quarters_used": 0, "min_obs": 0}
    if baseline_quarters >= 2:
        with _conn() as c:
            hist_p = [p for p, k in _filed_by_period(c, ciks, limit=baseline_quarters + 4)
                      if k / max(len(ciks), 1) >= 0.5]
        # 현재 분기쌍이 맨 앞에 오도록 정렬(사용자가 curr/prev 를 직접 준 경우 대비)
        hist_p = [p for p in hist_p if p <= curr][:baseline_quarters + 1]
        if len(hist_p) >= 3:
            bmeta = attach_baseline(out, ciks, hist_p, min_bp=min_bp)

    return {
        "kind": "rebalance",
        "curr_period": curr, "prev_period": prev,
        "n_participants": len(parts),
        "participants": [{"cik": k, **_g(k)} for k in parts],
        "excluded": [k for k in ciks if k not in parts],
        "min_bp": min_bp,
        "period_meta": pmeta,
        "baseline": bmeta,
        "rows": out,
        "total_rows": len(rows),
    }


def _pair_movers(mat: dict, ciks: list[str], curr: str, prev: str,
                 min_bp: float) -> dict[str, int]:
    """한 분기쌍에서 종목별 '조정한 거장 수'만 가볍게 센다(기준선 산출용)."""
    parts = _participants(mat, ciks, curr, prev)
    out: dict[str, int] = defaultdict(int)
    for k in parts:
        cur, old = mat[(curr, k)], mat[(prev, k)]
        for cu in set(cur) | set(old):
            if abs(cur.get(cu, 0.0) - old.get(cu, 0.0)) >= min_bp:
                out[cu] += 1
    return out


def attach_baseline(rows: list[dict], ciks: list[str], periods: list[str],
                    min_bp: float = MOVE_MIN_BP, min_obs: int = 3) -> dict:
    """각 종목의 현재 movers 가 **그 종목 평소 대비** 이례적인지 붙인다.

    ★ 왜 필요한가. "5명이 동시에 조정" 만으로는 판단이 안 된다. 거장 20명이
      늘 들고 흔드는 대형주는 5명이 평상시 수준이고, 아무도 안 건드리던 종목은
      2명만 움직여도 사건이다. **조건부 수치를 무조건부 수치와 나란히 둬야**
      증분 정보가 보인다.

    ★ 표본 수(n_obs)를 반드시 함께 낸다. 분기쌍 이력이 짧으면 백분위는 의미가
      없다. min_obs 미만이면 baseline 을 None 으로 두고 판단을 유보한다.
    """
    if len(periods) < 3:
        return {"quarters_used": 0, "min_obs": min_obs}
    mat, _ = weight_matrix(ciks, periods)
    hist: dict[str, list[int]] = defaultdict(list)
    # periods 는 최신순. index 0 쌍이 현재이므로 1번 쌍부터가 과거다.
    for i in range(1, len(periods) - 1):
        pm = _pair_movers(mat, ciks, periods[i], periods[i + 1], min_bp)
        for cu, n in pm.items():
            hist[cu].append(n)

    for r in rows:
        h = hist.get(r["cusip"], [])
        r["movers_n_obs"] = len(h)
        if len(h) < min_obs:
            r["movers_baseline"] = None
            r["movers_pctile"] = None
            r["is_unusual"] = None
            continue
        avg = sum(h) / len(h)
        below = sum(1 for x in h if x < r["movers"])
        r["movers_baseline"] = round(avg, 1)
        r["movers_pctile"] = round(below / len(h) * 100, 1)
        # 과거 어느 분기보다 많이 움직였고 평소의 1.5배 이상일 때만 '이례'
        r["is_unusual"] = bool(r["movers"] > max(h) and r["movers"] >= avg * 1.5)
    return {"quarters_used": len(periods) - 1, "min_obs": min_obs}


def _action(prev_bp: float, curr_bp: float) -> str:
    if prev_bp <= 0 and curr_bp > 0:
        return "new"
    if prev_bp > 0 and curr_bp <= 0:
        return "exited"
    return "increased" if curr_bp > prev_bp else "decreased"


# ────────────────────────────────────────────────── 2) 동시 편입 / 방출

def entries_exits(ciks: list[str], curr: str | None = None,
                  prev: str | None = None, top_n: int = TOP_N) -> dict:
    """**신규 편입**과 **전량 방출**만 따로 본다.

    rebalance_intensity 의 buyers 에는 '신규'와 '증가'가 섞여 있다. 여기서는
    포지션의 생성/소멸만 세므로 의미가 다르다. 편입 규모(bp)를 함께 준다.
    """
    ciks = [c for c in (pad_cik(x) for x in (ciks or [])) if c]
    if not ciks:
        return _empty_flow("entries_exits")

    pmeta: list[dict] = []
    if not (curr and prev):
        with _conn() as c:
            curr, prev, pmeta = pick_periods(c, ciks)
        if not (curr and prev):
            return _empty_flow("entries_exits",
                               periods=[p for p in (curr, prev) if p],
                               period_meta=pmeta)

    mat, label = weight_matrix(ciks, [curr, prev])
    parts = _participants(mat, ciks, curr, prev)
    if not parts:
        return _empty_flow("entries_exits", periods=[curr, prev], period_meta=pmeta)

    ent: dict[str, dict] = defaultdict(lambda: {"n": 0, "bp": 0.0, "gurus": []})
    ext: dict[str, dict] = defaultdict(lambda: {"n": 0, "bp": 0.0, "gurus": []})
    for k in parts:
        cur, old = mat[(curr, k)], mat[(prev, k)]
        for cu in set(cur) - set(old):
            e = ent[cu]
            e["n"] += 1
            e["bp"] += cur[cu]
            e["gurus"].append({"cik": k, **_g(k),
                               "bp": round(cur[cu], 1)})
        for cu in set(old) - set(cur):
            e = ext[cu]
            e["n"] += 1
            e["bp"] += old[cu]
            e["gurus"].append({"cik": k, **_g(k),
                               "bp": round(old[cu], 1)})

    def pack(d: dict) -> list[dict]:
        out = [{**label.get(cu, {"cusip": cu, "name": "", "ticker": ""}),
                "n_gurus": e["n"], "total_bp": round(e["bp"], 1),
                "avg_bp": round(e["bp"] / e["n"], 1) if e["n"] else 0.0,
                "gurus": sorted(e["gurus"], key=lambda x: -x["bp"])}
               for cu, e in d.items()]
        out.sort(key=lambda r: (-r["n_gurus"], -r["total_bp"]))
        return out

    entries, exits = pack(ent), pack(ext)
    return {
        "kind": "entries_exits",
        "curr_period": curr, "prev_period": prev,
        "n_participants": len(parts),
        "participants": [{"cik": k, **_g(k)} for k in parts],
        "excluded": [k for k in ciks if k not in parts],
        "period_meta": pmeta,
        "entries": entries[:top_n], "exits": exits[:top_n],
        "total_entries": len(entries), "total_exits": len(exits),
    }


# ──────────────────────────────────────────────────── 3) 섹터 관점

_SECTOR_MAP: dict[str, str] | None = None
UNCLASSIFIED = "미분류"


def _sector_map_path() -> str:
    import os
    return os.environ.get(
        "GURU_SECTOR_MAP",
        os.path.join(os.path.dirname(__file__), "assets", "guru_sector_map.csv"))


def load_sector_map(force: bool = False) -> dict[str, str]:
    """CUSIP → 섹터 매핑. 없거나 비어 있으면 빈 dict 를 돌려준다(장애 아님).

    ★ 13F 원문에도 filings.db 에도 섹터가 없다. cusip_ref 는 cusip/name/ticker
      뿐이라 섹터는 **외부에서 주입**해야 한다.
    ★ ticker 를 경유하면 안 된다. 실측(2026-03-31) 상위 300종목 중 ticker 가
      붙은 것은 179개(비중 63.8%)뿐이라 매핑 손실이 크다. CUSIP 을 키로 쓴다.
    ★ 보유는 극단적으로 집중돼 있다. 상위 100종목=비중 75.8%, 300종목=93.6%.
      따라서 300행짜리 수기 CSV 로도 실용적인 커버리지가 나온다.

    CSV 형식: cusip,sector  (헤더 필수, 그 외 열은 무시)
    """
    global _SECTOR_MAP
    if _SECTOR_MAP is not None and not force:
        return _SECTOR_MAP
    import csv
    import os
    path = _sector_map_path()
    out: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                cu = (row.get("cusip") or "").strip()
                sec = (row.get("sector") or "").strip()
                if cu and sec:
                    out[cu] = sec
    _SECTOR_MAP = out
    return out


def sector_flows(ciks: list[str], curr: str | None = None,
                 prev: str | None = None, min_bp: float = MOVE_MIN_BP) -> dict:
    """섹터 관점 비중 이동.

    거장별로 **섹터 비중(bp)** 을 먼저 만들고 그 차이를 집계한다. 종목 Δ 를
    나중에 합산해도 수학적으로 같지만, movers(그 섹터를 조정한 거장 수)는
    거장별 섹터 Δ 로 세어야 의미가 있다. 종목 단위로 세면 한 거장이 같은 섹터
    안에서 A 를 팔고 B 를 사도 2명으로 잡힌다.

    ★ 미분류는 숨기지 않고 하나의 행으로 같이 낸다. 매핑 커버리지가 낮으면
      미분류 버킷이 실제 1위 섹터보다 커질 수 있는데, 그걸 감추면 화면이 거짓말을
      한다. coverage 필드로 비중 기준 커버리지를 함께 반환한다.
    """
    ciks = [c for c in (pad_cik(x) for x in (ciks or [])) if c]
    if not ciks:
        return {"kind": "sector", "rows": [], "coverage": None,
                "insufficient_history": True, "period_meta": []}

    pmeta: list[dict] = []
    if not (curr and prev):
        with _conn() as c:
            curr, prev, pmeta = pick_periods(c, ciks)
        if not (curr and prev):
            return {"kind": "sector", "curr_period": curr, "prev_period": prev,
                    "rows": [], "coverage": None, "period_meta": pmeta,
                    "insufficient_history": True}

    smap = load_sector_map()
    mat, label = weight_matrix(ciks, [curr, prev])
    parts = _participants(mat, ciks, curr, prev)
    if not parts:
        return {"kind": "sector", "curr_period": curr, "prev_period": prev,
                "rows": [], "coverage": None, "period_meta": pmeta,
                "insufficient_history": True}

    # ★ 커버리지는 **분기별로** 잰다. 하나만 재면 치명적인 아티팩트를 놓친다.
    #   매핑 CSV 를 최신 분기 상위 종목으로만 만들면 직전 분기에만 있던 종목이
    #   전부 미분류로 잡히고, 그 결손 차이가 "미분류 대량 감소"로 둔갑한다.
    #   실측 사례: 커버리지 82.3%(prev) vs 88.7%(curr) 인 상태에서 미분류가
    #   -643bp/거장 줄어 보였는데, 6.4%p x 10000bp = 640bp 로 격차와 정확히 일치했다.
    #   즉 포트폴리오 이동이 아니라 매핑 결손이었다.
    def _cov(period: str) -> float:
        hit = tot = 0.0
        for kk in parts:
            for cu, w in mat[(period, kk)].items():
                tot += w
                if cu in smap:
                    hit += w
        return round(hit / tot * 100, 1) if tot else 0.0

    cov_curr, cov_prev = _cov(curr), _cov(prev)
    coverage = cov_curr
    cov_gap = round(cov_curr - cov_prev, 1)

    agg: dict[str, dict] = defaultdict(
        lambda: {"movers": 0, "up": 0, "down": 0, "gross_bp": 0.0, "net_bp": 0.0,
                 "curr_bp": 0.0, "prev_bp": 0.0, "top_names": defaultdict(float)})

    for k in parts:
        cur_s: dict[str, float] = defaultdict(float)
        old_s: dict[str, float] = defaultdict(float)
        for cu, w in mat[(curr, k)].items():
            cur_s[smap.get(cu, UNCLASSIFIED)] += w
        for cu, w in mat[(prev, k)].items():
            old_s[smap.get(cu, UNCLASSIFIED)] += w
        for sec in set(cur_s) | set(old_s):
            a, b = old_s.get(sec, 0.0), cur_s.get(sec, 0.0)
            e = agg[sec]
            e["curr_bp"] += b
            e["prev_bp"] += a
            d = b - a
            if abs(d) < min_bp:
                continue
            e["movers"] += 1
            e["gross_bp"] += abs(d)
            e["net_bp"] += d
            if d > 0:
                e["up"] += 1
            else:
                e["down"] += 1
        # 섹터별 기여 상위 종목(순변화 기준)
        for cu in set(mat[(curr, k)]) | set(mat[(prev, k)]):
            d = mat[(curr, k)].get(cu, 0.0) - mat[(prev, k)].get(cu, 0.0)
            if abs(d) >= min_bp:
                agg[smap.get(cu, UNCLASSIFIED)]["top_names"][cu] += d

    n = len(parts)
    rows = []
    for sec, e in agg.items():
        gross = e["gross_bp"]
        movers = sorted(e["top_names"].items(), key=lambda x: -abs(x[1]))[:5]
        rows.append({
            "sector": sec,
            "movers": e["movers"], "up": e["up"], "down": e["down"],
            "gross_bp": round(gross, 1), "net_bp": round(e["net_bp"], 1),
            "agreement": round(abs(e["net_bp"]) / gross, 3) if gross else 0.0,
            # 섹터 비중은 거장 평균으로 표시(합산하면 거장 수만큼 부풀려진다)
            "prev_wgt_bp": round(e["prev_bp"] / n, 1),
            "curr_wgt_bp": round(e["curr_bp"] / n, 1),
            "top_contributors": [
                {**label.get(cu, {"cusip": cu, "name": "", "ticker": ""}),
                 "delta_bp": round(d, 1)} for cu, d in movers],
        })
    rows.sort(key=lambda r: (r["sector"] == UNCLASSIFIED, -r["gross_bp"]))

    return {
        "kind": "sector",
        "curr_period": curr, "prev_period": prev,
        "n_participants": n,
        "participants": [{"cik": k, **_g(k)} for k in parts],
        "period_meta": pmeta,
        "coverage": coverage,
        "coverage_curr": cov_curr,
        "coverage_prev": cov_prev,
        "coverage_gap": cov_gap,
        # 커버리지 격차가 이 값을 넘으면 미분류 행의 net 은 아티팩트로 봐야 한다.
        # 격차 1%p 는 거장당 100bp 의 가짜 이동을 만든다.
        "unclassified_unreliable": abs(cov_gap) >= 1.0,
        "mapped_cusips": len(smap),
        "min_bp": min_bp,
        "rows": rows,
    }


# ────────────────────────────────────────────────────────── 공통

def _empty_flow(kind: str, periods: list[str] | None = None,
                period_meta: list[dict] | None = None) -> dict:
    p = periods or []
    return {"kind": kind, "curr_period": p[0] if p else None,
            "prev_period": p[1] if len(p) > 1 else None,
            "n_participants": 0, "participants": [], "excluded": [],
            "rows": [], "entries": [], "exits": [],
            "total_rows": 0, "total_entries": 0, "total_exits": 0,
            "period_meta": period_meta or [],
            "insufficient_history": True}
