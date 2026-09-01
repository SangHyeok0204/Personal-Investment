# -*- coding: utf-8 -*-
r"""[시장 시그널] 2단 재료 — markets.ttl 생성기 (2026-08-31 신설).

`knowledge.ttl` 이 **변하지 않는 인과 구조**(손으로 쓴 암묵지)라면, 이 파일이 굽는
`markets.ttl` 은 **매일 변하는 관측**이다. 둘을 갈라 놓는 이유는 하나다 —
상관계수와 체제는 체제에 따라 변하는데, 인과 방향("구리가 오르면 호주가 오른다")은
안 변한다. 섞어 두면 매일 손으로 쓴 지식까지 덮어쓰게 된다.

담는 것 3종(사용자 지정):
  1. **체제**   — "~시장이 강세다 / 약세다"
  2. **상관**   — "a 와 b 는 최근 1년간 상관 0.xx"
  3. **매크로 동조** — "c 는 최근 1개월 동안 매크로 영향과 동조한다"

★상관은 |r| 이 임계 이상인 쌍만 싣는다. 87시장이면 쌍이 3,741개인데 전부 실으면
  파일이 커지고 탐색이 느려지는데다, r=0.1 짜리 간선은 가설 근거가 못 된다.

★★체제 판정에서 **채권은 가격 기준**이다. 금리 상승 = 채권 가격 하락 = 약세.
  시트가 주는 값이 금리(yield)라 부호를 뒤집지 않으면 "금리 급등 = 채권 강세"라는
  거꾸로 된 그래프가 나온다.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from collector.market_signal import indicators as ind

CORR_MIN = 0.55        # 이보다 약한 간선은 가설 근거가 못 된다
CORR_WINDOW = 365      # "최근 1년" (달력일)
MACRO_WINDOW = 30      # "최근 1개월" 매크로 동조
MACRO_MIN = 0.50       # 동조로 부를 최소 |r|
MIN_OVERLAP = 60       # 1년 상관을 재려면 겹치는 관측일이 이만큼은 있어야 한다
# ★★매크로 동조는 최소 겹침이 **따로** 있어야 한다. 1개월 창은 거래일이 22일 남짓인데
#   60 을 요구하면 **한 건도 안 나온다**(첫 실행에서 실제로 0건이 나왔다).
#   15 는 3주치 — 이보다 짧으면 r 이 우연으로 널뛴다.
MIN_OVERLAP_MACRO = 15

NS = "http://ge.local/market#"

# 매크로 동인 → 그 동인의 체온계가 될 시장(knowledge.ttl 의 mk:proxyFor 와 같아야 한다).
# ★여기서 다시 적는 이유: build 단계는 ttl 을 아직 안 읽는다(닭-달걀). knowledge.ttl 이
#   바뀌면 여기도 같이 고쳐야 한다 — graph.py 가 기동 때 둘의 불일치를 검사한다.
DRIVER_PROXY = {
    "USRates": "GT10 Govt",
    "Dollar": "DXY Curncy",
    "RiskAppetite": "XBTUSD BGN Curncy",
    "ChinaGrowth": "LMCADS03 Comdty",
    "OilSupply": "CL1 COMB Comdty",
    "SemiCycle": "SOX Index",
    "JapanPolicy": "GTJPY10Y Govt",
    "Inflation": "XAU Curncy",
}


def _slug(ticker: str) -> str:
    """티커 → URI 로컬명. 티커에 공백·점이 있어 그대로는 못 쓴다."""
    out = []
    for ch in ticker:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    s = "".join(out).strip("_")
    while "__" in s:
        s = s.replace("__", "_")
    return "M_" + s


def _returns(series: dict[date, float], is_yield: bool,
             since: date) -> dict[date, float]:
    """상관 계산용 일간 변화. **이월 제거 후**의 실제 변동만 쓴다.

    ⚠️이월(ffill 복사본)을 안 걷으면 주말 0% 가 양쪽에 같이 끼어 **상관이 통째로
      부풀려진다**(같은 날 둘 다 0 이니 완벽히 일치한다). 이 파이프라인에서 가장
      쉽게 나는 거짓 상관이 이것이다.
    """
    moves = ind._real_moves(series)
    out: dict[date, float] = {}
    ds = sorted(moves)
    for i in range(1, len(ds)):
        d = ds[i]
        if d < since:
            continue
        c = ind.change(moves[d], moves[ds[i - 1]], is_yield)
        if c is not None:
            out[d] = c
    return out


def _pearson(a: dict[date, float], b: dict[date, float],
             min_overlap: int = MIN_OVERLAP) -> tuple[float, int] | None:
    """겹치는 날짜만으로 상관. (r, 겹친 관측수) 또는 None."""
    keys = a.keys() & b.keys()
    n = len(keys)
    if n < min_overlap:
        return None
    xs = [a[k] for k in keys]
    ys = [b[k] for k in keys]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy), n


def classify_regime(m: dict, is_yield: bool) -> tuple[str, float]:
    """체제 판정 → ("Bull"|"Bear"|"Range", 점수).

    ★근거를 하나만 쓰지 않는다. 6개월 수익률만 보면 최근 급락을 놓치고, 이평만 보면
      횡보에서 부호가 팔랑거린다. 셋(중기수익률·이평배열·레인지위치)의 합의로 정한다.
    ★★채권은 **가격 기준으로 뒤집는다**(금리 상승 = 채권 약세).
    """
    r6 = m.get("r6m")
    stack = m.get("ma_stack")
    pos = m.get("range_pos_252")
    if is_yield:
        r6 = None if r6 is None else -r6
        stack = None if stack is None else -stack
        pos = None if pos is None else (100.0 - pos)

    score = 0.0
    if r6 is not None:
        score += 1.0 if r6 > 0 else -1.0
    if stack:
        score += 1.0 if stack > 0 else -1.0
    if pos is not None:
        score += 1.0 if pos >= 60 else (-1.0 if pos <= 40 else 0.0)

    if score >= 2:
        return "Bull", score
    if score <= -2:
        return "Bear", score
    return "Range", score


def build(columns: dict[str, dict[date, float]], catalog: list[tuple],
          asof: date | None = None) -> str:
    """price_board 컬럼 + 카탈로그 → markets.ttl 본문(문자열).

    catalog = [(ticker, label, asset_class, is_yield), ...]
    """
    if asof is None:
        asof = max((d for s in columns.values() for d in s), default=date.today())
    since_corr = asof - timedelta(days=CORR_WINDOW)
    since_macro = asof - timedelta(days=MACRO_WINDOW)

    ac_uri = {"equity": "Equity", "bond": "Bond", "commodity": "Commodity",
              "fx": "FX", "crypto": "Crypto"}

    L: list[str] = [
        "@prefix mk:   <%s> ." % NS,
        "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
        "# ⚠️ 이 파일은 build_graph.py 가 **생성**한다. 손으로 고치지 말 것 —",
        "#    다음 갱신에 통째로 덮인다. 손으로 쓸 지식은 knowledge.ttl 로.",
        "# 생성 기준일: %s" % asof.isoformat(),
        "",
    ]

    # ── 1. 시장 인스턴스 + 체제 ──
    rets_1y: dict[str, dict[date, float]] = {}
    rets_1m: dict[str, dict[date, float]] = {}
    metrics: dict[str, dict] = {}
    present: list[tuple] = []

    for ticker, label, cat, is_yield in catalog:
        s = columns.get(ticker)
        if not s:
            continue
        m = ind.compute(s, is_yield=is_yield, asof=asof)
        if not m:
            continue
        present.append((ticker, label, cat, is_yield))
        metrics[ticker] = m
        rets_1y[ticker] = _returns(s, is_yield, since_corr)
        rets_1m[ticker] = _returns(s, is_yield, since_macro)

        regime, score = classify_regime(m, is_yield)
        u = "mk:" + _slug(ticker)
        L.append("%s a mk:Market ;" % u)
        L.append('    mk:ticker "%s" ; rdfs:label "%s" ;' % (ticker, _esc(label)))
        L.append("    mk:inAssetClass mk:%s ;" % ac_uri.get(cat, "Equity"))
        L.append("    mk:isYield %s ;" % ("true" if is_yield else "false"))
        L.append("    mk:hasRegime mk:%s ; mk:regimeScore %.1f ;" % (regime, score))
        parts = []
        # ★dtd·wtd·mtd 를 **노드에 싣는다**. 2단 탐색이 "이웃도 같이 움직였나"를 물을 때
        #   그 이웃의 당일 수익률이 필요한데, 그걸 그래프 밖에서 다시 계산하면 탐색이
        #   순수 그래프 연산이 아니게 된다(사용자 설계: .py 가 .ttl 을 탐색한다).
        for k, prop in (("dtd", "retDtd"), ("wtd", "retWtd"), ("mtd", "retMtd"),
                        ("r1m", "ret1m"), ("r3m", "ret3m"), ("r6m", "ret6m"),
                        ("ytd", "retYtd"), ("ytd_high_drawdown", "drawdown"),
                        ("range_pos_252", "rangePos"), ("vol252", "vol252")):
            v = m.get(k)
            if v is not None:
                parts.append("    mk:%s %.2f" % (prop, v))
        L.append(" ;\n".join(parts) + " .")
        L.append("")

    L.append("# ── 체제 (강세/약세/횡보) ──")
    L.append("mk:Bull a mk:Regime ; rdfs:label \"강세\" .")
    L.append("mk:Bear a mk:Regime ; rdfs:label \"약세\" .")
    L.append("mk:Range a mk:Regime ; rdfs:label \"횡보\" .")
    L.append("")

    # ── 2. 상관 (최근 1년) ──
    L.append("# ── 상관 관측 (최근 %d일, |r| >= %.2f 만) ──" % (CORR_WINDOW, CORR_MIN))
    n_corr = 0
    tickers = [t for t, _l, _c, _y in present]
    for i, t1 in enumerate(tickers):
        for t2 in tickers[i + 1:]:
            pr = _pearson(rets_1y[t1], rets_1y[t2])
            if pr is None:
                continue
            r, n = pr
            if abs(r) < CORR_MIN:
                continue
            L.append("[] a mk:Correlation ;")
            L.append("   mk:subjectMarket mk:%s ; mk:objectMarket mk:%s ;"
                     % (_slug(t1), _slug(t2)))
            L.append('   mk:corrValue %.3f ; mk:corrWindow %d ; mk:corrN %d ;'
                     % (r, CORR_WINDOW, n))
            L.append('   mk:asof "%s"^^xsd:date .' % asof.isoformat())
            n_corr += 1
    L.append("")

    # ── 3. 매크로 동조 (최근 1개월) ──
    L.append("# ── 매크로 동조 (최근 %d일, |r| >= %.2f) ──" % (MACRO_WINDOW, MACRO_MIN))
    n_macro = 0
    for drv, proxy_tk in DRIVER_PROXY.items():
        pr_rets = rets_1m.get(proxy_tk)
        if not pr_rets:
            continue
        for t, _l, _c, _y in present:
            if t == proxy_tk:
                continue
            pr = _pearson(rets_1m[t], pr_rets, MIN_OVERLAP_MACRO)
            if pr is None:
                continue
            r, n = pr
            if abs(r) < MACRO_MIN:
                continue
            L.append("[] a mk:MacroComove ;")
            L.append("   mk:subjectMarket mk:%s ; mk:driver mk:%s ;" % (_slug(t), drv))
            L.append('   mk:corrValue %.3f ; mk:corrWindow %d ; mk:corrN %d ;'
                     % (r, MACRO_WINDOW, n))
            L.append('   mk:asof "%s"^^xsd:date .' % asof.isoformat())
            n_macro += 1

    L.append("")
    L.append("# 요약: 시장 %d · 상관간선 %d · 매크로동조 %d"
             % (len(present), n_corr, n_macro))
    return "\n".join(L) + "\n"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write(path: str, columns=None, catalog=None, asof: date | None = None) -> dict:
    """markets.ttl 을 원자적으로 쓴다(tmp → os.replace). 반환 = 요약 통계."""
    import os
    from collector import price_board as pb
    from collector.market_signal import signal_rules as sr

    if columns is None:
        columns = pb._read_columns()
    if catalog is None:
        catalog = sr.catalog_from_price_board()
    body = build(columns, catalog, asof)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    last = body.rstrip().rsplit("\n", 1)[-1]
    return {"path": path, "bytes": len(body.encode("utf-8")), "summary": last}
