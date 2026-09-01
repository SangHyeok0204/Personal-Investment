# -*- coding: utf-8 -*-
r"""[시장 시그널] 1단 — "price 가 튀었는가" if 로직 (2026-08-31 신설).

파이프라인 1단이다. 여기서 걸린 것만 2단(온톨로지 해석)·3단(뉴스 근거)으로 간다.
**여기서 안 걸린 건 아예 AI 를 안 부른다** — 그게 이 단의 존재 이유다(콜당 비용).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★★★ 고정 % 임계는 절대 쓰지 않는다 ★★★

주간가격모니터가 이미 겪고 고친 자리다([[weekly-price-monitor-anomaly-rules]]).
2021-01~2026-08 실측, 주간 |수익률| >= 5% 발화율:

    DXY 0.0%(5년 반 0건) · USDKRW 0.1% · S&P500 3.4% · 나스닥 8.8%
    · 항셍테크 29.4% · WTI 30.3% · BTC 36.2% · ETH 47.1%(2주에 한 번)

같은 임계가 어떤 시장엔 5.3σ, 어떤 시장엔 0.56σ였다. 그래서 전부
**그 시장 자신의 실측 분위수**로 자른다. z 도 아니다 — 꼬리 두께가 시장마다 달라
같은 z 가 다른 희소도를 뜻한다(과창판 주간 +12.31% = z 2.1 인데 실제로는 상위 1.2%).
분위수면 발화율이 정의상 균일해지고 "과거 N년 중 상위 X%" 를 문장에 그대로 쓴다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

발화율 목표: **전 시장 합쳐 하루 3~8건.** 이보다 많으면 '특이점'이라는 말이 무의미해지고,
적으면 카드가 늘 비어 있다. 카드가 한 번에 1건만 보여주므로 상위 1건만 쓰이지만,
2단(온톨로지)이 후보를 여러 개 봐야 교차 검증이 되므로 3~8건을 남긴다.
"""
from __future__ import annotations

from datetime import date

from collector.market_signal import indicators as ind

# ── 컷 (발화율 목표치이므로 이것만 상수다) ──────────────────────────────────
# ★★2026-08-31 백테스트로 조인 값이다. 0.98(양꼬리 4%)이면 87시장×3기간에서
#   spike 만 하루 11건이 나온다 — 이론 발화율 그대로다(87×(1-0.96^3)=10.0).
#   카드가 1건만 보여주므로 1단은 하루 3~8건이면 충분하다 → 0.995(양꼬리 1%).
PCT_HI = 0.995         # 상위 0.5%
PCT_LO = 0.005         # 하위 0.5%
VOL_RATIO_CUT = 1.80   # 단기 변동성이 장기의 1.8배 = 변동성 체제 확장
STREAK_CUT = 8         # 연속 8일 동일 방향(6→8, 백테스트에서 6은 하루 3.3건)
CROSS_FRESH_D = 3      # 크로스는 발생 3일 내만 '사건'
# ★★2026-09-01 재측정으로 90 → 21 로 내렸다. 90 은 **버그가 만든 숫자를 보고 과잉
#   교정한 값**이었다 — 당시 하루 7.2건은 임계 탓이 아니라 `gap=None → 무조건 발화`
#   버그 탓이었고, 버그를 고친 뒤 재 보니 90일이든 21일이든 차이가 **하루 0.4건**뿐이다
#   (실측: 90일 0.5/일 · 21일 0.9/일). 그 대가로 "미국채 10Y 가 29일 만에 52주 신고
#   수익률을 뚫었는데 아무 신호도 없다"를 만들고 있었다.
RANGE_NEW_D = 21       # 신고/신저는 이만큼 쉬었다 뚫어야 사건 취급
# ★돌파는 **그날 하루짜리 사건이 아니다.** 뚫은 다음 날도 신고가면 quiet=1 이 되어
#   조용해지는데, 보는 사람에게는 여전히 "신고가 행진 중"이다. 돌파 시작 후 이만큼은
#   유효하게 둔다(반복은 pipeline 의 REPEAT_PENALTY 가 순위로 눌러 준다).
RANGE_RUN_D = 5
# ★★2026-09-01 신설. 엔진 전체가 **변화(change)** 기반이라 "지금 어디에 서 있나"를
#   말하는 룰이 하나도 없었다 — `range_pos_252` 를 계산만 하고 아무도 안 썼다.
#   미국채 10Y 가 52주 최고 수익률(레인지 100%)인데 60일간 한 번도 안 뜬 게 그 증거다
#   (돌파일에도 quiet=29일이라 RANGE_NEW_D=90 컷에 못 미쳤다).
#   range_break 는 **한 번의 돌파 사건**이고, 이건 **상태**다 — 랠리가 이어지는 동안
#   계속 잡힌다. 매일 뜨는 문제는 pipeline 의 REPEAT_PENALTY 가 이미 처리한다.

# 지표 표시명 — 카드 문장에 그대로 들어간다.
LABEL = {"dtd": "일간", "wtd": "주간", "mtd": "월간"}


def _sig(rule: str, market: str, label: str, cat: str, metric: str,
         value: float, rarity: float | None, severity: float, note: str,
         extra: dict | None = None, direction: int | None = None) -> dict:
    """시그널 노드 하나. 2단(온톨로지)이 이 dict 를 그대로 받아 그래프를 탐색한다.

    ★사용자 요구: 노드는 최소한 [어느 시장의 / 어느 지표가 / 얼만큼 튀었느냐] 를 갖는다.
      → market · metric · value 가 그 셋이고, rarity 가 "얼마나 드문가"를 더한다.
    """
    return {
        "rule": rule,
        "market": market,        # 블룸버그 티커 = 고유키(온톨로지 URI 와 1:1)
        "label": label,          # 표시명
        "asset_class": cat,      # equity | bond | commodity | fx | crypto
        "metric": metric,        # dtd | wtd | mtd | range | cross | vol | streak
        "value": None if value is None else round(float(value), 2),
        # ★★방향은 value 의 부호로 **추론하면 안 되는 룰**이 있다. trend_flip 의 value 는
        #   이격도(dev60)라 크로스 방향과 무관하게 부호가 정해지고, range_break 는
        #   '연저점 대비 상승률'이라 신저가인데도 양수가 나온다. 그런 룰은 명시로 준다.
        "direction": (int(direction) if direction is not None
                      else (0 if not value else (1 if value > 0 else -1))),
        "rarity": None if rarity is None else round(float(rarity), 4),
        "severity": round(float(severity), 3),
        "note": note,
        **(extra or {}),
    }


def detect_one(ticker: str, label: str, cat: str, series: dict[date, float],
               is_yield: bool, asof: date | None = None) -> list[dict]:
    """시장 하나에 대해 1단 룰을 전부 돌린다. 걸린 시그널 목록(0~N건)."""
    m = ind.compute(series, is_yield=is_yield, asof=asof)
    if not m:
        return []
    unit = m["unit"]
    hits: list[dict] = []

    # ── R1. 급등락 — 그 시장 자신의 분위수 양쪽 꼬리 ★주력 룰 ──
    #   체제 이중 트리거: 전 구간 분위수 OR 최근 1년 분위수. 하나만 걸려도 발화한다.
    #   (금 주간 +7.12% 가 최근 1년 기준으론 안 걸렸던 사례 때문이다.)
    for h in ("dtd", "wtd", "mtd"):
        v = m.get(h)
        p_all, p_1y = m.get(f"pct_{h}"), m.get(f"pct1y_{h}")
        if v is None or (p_all is None and p_1y is None):
            continue
        ps = [p for p in (p_all, p_1y) if p is not None]
        hi = max(ps)
        lo = min(ps)
        if hi >= PCT_HI:
            tail = 1.0 - hi                      # 상위 tail 비율
        elif lo <= PCT_LO:
            tail = lo
        else:
            continue
        # severity = 얼마나 희귀한가. 0.02 → 1.0, 0.005 → 1.6 정도로 완만히 커진다.
        sev = min(3.0, (1.0 - PCT_HI) / max(tail, 0.0002))
        hits.append(_sig(
            "spike", ticker, label, cat, h, v, tail, sev,
            f"{LABEL[h]} {v:+.2f}{unit} — 과거 상위 {tail * 100:.1f}%",
            {"pct_all": p_all, "pct_1y": p_1y},
        ))

    # ── R2. 52주 신고가/신저가 **돌파** ──
    #   ★★2026-08-31 백테스트에서 이 룰이 하루 7.2건을 뱉었다(전체의 29%). 원인은
    #     "신고가에 있다"와 "신고가를 **돌파했다**"를 구분하지 않은 것이다. 추세장에서는
    #     매일이 신고가라 상태이지 사건이 아니다. 사상 최고가면 직전 극값이 아예 없어
    #     gap=None → 무조건 발화까지 했다(그 자체가 버그).
    #   → 고쳐서: **직전 CONSOLIDATION_D 일 동안 신고가가 없었어야** 발화한다.
    #     즉 '쉬다가 뚫었다'만 사건으로 본다.
    if m.get("is_high_252") or m.get("is_low_252"):
        up = bool(m.get("is_high_252"))
        # 연속 신고 구간이 언제 시작됐고, 그 앞에 얼마나 쉬었나.
        run_days, quiet = _breakout_run(series, is_high=up, asof=asof)
        if (quiet is not None and quiet >= RANGE_NEW_D
                and run_days is not None and run_days <= RANGE_RUN_D):
            v = m.get("ytd_low_gain") if up else m.get("ytd_high_drawdown")
            hits.append(_sig(
                "range_break", ticker, label, cat, "range", v, None, 1.4,
                f"{quiet}일 만에 52주 {'신고가' if up else '신저가'} 돌파"
                + ("" if run_days == 0 else f" ({run_days}일째 지속)"),
                {"is_high": up, "quiet_days": quiet, "run_days": run_days},
                direction=1 if up else -1,
            ))

    # ── R3. 추세 전환 — 20/60 이평 크로스가 방금 났다 ──
    cr = m.get("cross_20_60")
    if cr is not None and abs(cr) <= CROSS_FRESH_D:
        up = cr > 0
        hits.append(_sig(
            "trend_flip", ticker, label, cat, "cross", m.get("dev60"), None, 1.2,
            f"20/60 {'골든' if up else '데드'}크로스 ({abs(cr)}일 전)",
            {"cross_days": cr}, direction=1 if up else -1,
        ))

    # ── R4. 변동성 체제 확장 ──
    #   ★여기만 고정 컷을 쓴다. vol_ratio 는 **자기 단기/자기 장기**라 이미 자기보정된
    #     무차원 값이다 — 고정 % 수익률 임계와는 성질이 다르다(그건 시장마다 의미가 달랐다).
    vr = m.get("vol_ratio")
    if vr is not None and vr >= VOL_RATIO_CUT:
        hits.append(_sig(
            "vol_regime", ticker, label, cat, "vol", (vr - 1) * 100, None,
            min(2.0, vr / VOL_RATIO_CUT), f"단기 변동성이 1년 평균의 {vr:.1f}배",
            {"vol20": m.get("vol20"), "vol252": m.get("vol252")},
        ))

    # ── R5. 연속성 극단 ──
    st = m.get("streak")
    if st is not None and abs(st) >= STREAK_CUT:
        hits.append(_sig(
            "streak", ticker, label, cat, "streak", float(st), None,
            min(2.0, abs(st) / STREAK_CUT),
            f"{abs(st)}일 연속 {'상승' if st > 0 else '하락'}",
            {"streak": st}, direction=1 if st > 0 else -1,
        ))

    for h in hits:
        h["indicators"] = m      # 2단이 쓸 전체 지표 묶음(가설 검증 재료)
        # ★★2단이 문장을 쓸 때 반드시 필요하다. 금리는 **오르면 채권 약세**라
        #   direction 을 그대로 '강세'로 옮기면 정반대 문장이 나간다.
        h["is_yield"] = is_yield
    return hits


def _breakout_run(series: dict[date, float], is_high: bool,
                  asof: date | None) -> tuple[int | None, int | None]:
    """(연속 신고 구간이 시작된 지 며칠, 그 **앞의** 조용했던 기간).

    ★"돌파"는 하루짜리 사건이 아니다. 뚫은 다음 날도 신고면 직전 극값과의 간격이 1 이
      되어 조용해지는데, 보는 사람에게는 여전히 신고가 행진이다. 그래서 **런의 시작**을
      기준으로 판정한다 — 시작일에 얼마나 쉬었는지가 '돌파의 크기'다.
    """
    ds = [d for d in sorted(series) if asof is None or d <= asof]
    if len(ds) < 30:
        return None, None
    a = ds[-1]
    start = None
    for i in range(len(ds) - 1, 0, -1):
        d = ds[i]
        win = [series[x] for x in ds[:i] if 0 < (d - x).days <= 365]
        if not win:
            break
        ext = max(win) if is_high else min(win)
        is_ext = (series[d] >= ext - 1e-12) if is_high else (series[d] <= ext + 1e-12)
        if not is_ext:
            break
        start = d
    if start is None:
        return None, None
    return (a - start).days, _days_since_last_extreme(series, is_high, asof=start)


def _days_since_last_extreme(series: dict[date, float], is_high: bool,
                             asof: date | None) -> int | None:
    """**직전에 52주 신고(신저)를 찍은 게 며칠 전인가.** 오늘은 세지 않는다.

    ★"신고가에 있다"가 아니라 "쉬다가 뚫었다"를 재는 함수다. 어제도 신고가였으면
      1 을 돌려주고, 그러면 룰이 발화하지 않는다(추세장에서 매일 발화하던 원인).
    252일 창이 처음부터 계속 신고가면(=상장 이후 계속 오름) None — 발화하지 않는다.
    """
    ds = sorted(d for d in series if asof is None or d <= asof)
    if len(ds) < 30:
        return None
    a = ds[-1]
    for i in range(len(ds) - 2, -1, -1):
        d = ds[i]
        if (a - d).days > 400:          # 창(252영업일≈365일)보다 더 거슬러 갈 이유가 없다
            return (a - d).days
        win = [series[x] for x in ds[:i + 1] if (d - x).days <= 365]
        if not win:
            continue
        v = series[d]
        was = (v >= max(win) - 1e-12) if is_high else (v <= min(win) + 1e-12)
        if was:
            return (a - d).days
    return None


def detect_all(columns: dict[str, dict[date, float]], catalog: list[tuple],
               asof: date | None = None, top: int = 8) -> list[dict]:
    """전 시장 1단 스캔. catalog = [(ticker, label, asset_class, is_yield), ...]

    ★★**시장당 1건으로 접는다.** 87개 시장 × 5룰 × 3기간을 따로 세면 하루 수십 건이
      나온다(주간가격모니터 백테스트에서 51시장 기준 하루 16.6건 → 접어서 11.2건).
      한 시장이 여러 룰에 걸리는 건 같은 사건의 다른 얼굴이라 접는 게 맞다.
    """
    by_market: dict[str, dict] = {}
    for ticker, label, cat, is_yield in catalog:
        s = columns.get(ticker)
        if not s:
            continue
        for h in detect_one(ticker, label, cat, s, is_yield, asof):
            prev = by_market.get(ticker)
            if prev is None or h["severity"] > prev["severity"]:
                by_market[ticker] = h
    out = sorted(by_market.values(), key=lambda h: -h["severity"])
    return out[:top]


def catalog_from_price_board() -> list[tuple]:
    """price_board 의 분류표를 1단 스캔용 카탈로그로 변환. 분류 정본은 그쪽이다.

    ★★표시명에 보조라벨을 앞에 붙인다. 채권 label 이 "2Y"·"10Y" 뿐이라 그대로 쓰면
      카드가 "2Y 단독 약세"라고 나오고(어느 나라 2년물인지 없다) 뉴스 검색어도
      "2Y" 가 되어 **한 건도 안 잡힌다**(실측 뉴스점수 0.0).
      → sub("미국채")를 앞에 붙여 "미국채 2Y" 로 만든다. 주식·원자재는 sub 가 단위
        설명이라(예: "근월 (USD/bbl)") 붙이지 않는다 — 채권만 국가명이 sub 에 있다.
    """
    from collector import price_board as pb
    out = []
    for c in pb.CATEGORIES:
        for l1, _l2, label, sub, ticker in c["rows"]:
            disp = f"{sub} {label}" if (c["yield"] and sub) else label
            out.append((ticker, disp, c["key"], c["yield"]))
    return out
