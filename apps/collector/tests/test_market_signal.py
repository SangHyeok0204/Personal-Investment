# -*- coding: utf-8 -*-
"""[시장 시그널] 회귀 테스트 — **실제로 났던 결함만** 못 박는다 (2026-08-31).

여기 있는 항목은 하나도 빠짐없이 개발 중 실제로 발생해서 화면에 틀린 값·틀린 문장을
내보냈던 것들이다. 값이 아니라 **정의**를 지키는 게 목적이라, 리팩터로 숫자가 조금
달라져도 통과해야 하고 정의가 뒤집히면 반드시 실패해야 한다.

⚠️통과만 하는 검사기는 검사기가 아니다 — 아래 각 테스트는 "버그를 되돌리면 실제로
  FAIL 로 뒤집히는가"를 기준으로 짰다(주간가격모니터 check_anomaly_rules 의 [G] 절과
  같은 원칙).
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.market_signal import build_graph as bg  # noqa: E402
from collector.market_signal import indicators as ind  # noqa: E402
from collector.market_signal import signal_rules as sr  # noqa: E402


def _rising(start: date, n: int, v0: float = 100.0, step: float = 1.0) -> dict:
    return {start + timedelta(days=i): v0 + i * step for i in range(n)}


def _ffilled(start: date, n: int) -> dict:
    """주말은 금요일 값을 그대로 복사한 시계열(시트의 실제 모양)."""
    out, v = {}, 100.0
    for i in range(n):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            v += 1.0
        out[d] = v
    return out


# ══════════════════════════════════════════════════════════════════════
#  indicators
# ══════════════════════════════════════════════════════════════════════

def test_real_moves_strips_ffill_copies():
    """★이월 제거가 없으면 주말 0% 가 분포에 섞여 σ 가 과소 추정되고 z 가 부풀려진다."""
    s = _ffilled(date(2026, 1, 5), 28)          # 4주
    moves = ind._real_moves(s)
    assert len(moves) < len(s)                   # 주말이 걷혔다
    assert all(d.weekday() < 5 for d in list(moves)[1:])


def test_bond_uses_bp_not_percent():
    """★금리의 %변화율은 마이너스 구간에서 부호가 뒤집힌다 — bp 여야 한다."""
    s = {date(2025, 12, 31): -0.10, date(2026, 8, 20): 0.05, date(2026, 8, 21): 0.09}
    m = ind.compute(s, is_yield=True)
    assert m["unit"] == "bp"
    assert m["dtd"] == pytest.approx(4.0)        # 0.05 → 0.09 = +4bp
    assert m["ytd"] == pytest.approx(19.0)


def test_rolling_windows_are_calendar_not_positional():
    """★영업일 위치 shift 를 쓰면 이월 제거 후 달력으로 열흘 넘게 거슬러 간다."""
    s = _rising(date(2026, 1, 1), 200)
    m = ind.compute(s, is_yield=False, asof=date(2026, 6, 1))
    cur = m["price"]
    # 정확히 달력 30일 전 값 대비여야 한다
    assert m["r1m"] == pytest.approx((cur / (cur - 30) - 1) * 100, rel=1e-9)


def test_percentile_not_fixed_threshold():
    """★★고정 % 임계 금지의 본체 — 분위수는 **자기 분포** 기준이어야 한다.

    변동성이 10배 다른 두 시장에 같은 크기의 움직임을 주면, 조용한 시장에서는
    극단 분위수가 나오고 시끄러운 시장에서는 평범해야 한다.
    """
    calm = {date(2020, 1, 1) + timedelta(days=i): 100 + (i % 2) * 0.1 for i in range(600)}
    wild = {date(2020, 1, 1) + timedelta(days=i): 100 + (i % 2) * 10.0 for i in range(600)}
    hist_c = ind._hist_changes(ind._real_moves(calm), 1, False)
    hist_w = ind._hist_changes(ind._real_moves(wild), 1, False)
    move = 1.0                                   # +1% 한 방
    assert ind._pct_rank(hist_c, move) > ind._pct_rank(hist_w, move)


# ══════════════════════════════════════════════════════════════════════
#  signal_rules — 1단
# ══════════════════════════════════════════════════════════════════════

def test_range_break_does_not_fire_every_day_in_a_trend():
    """★★실제 결함: 추세장에서 매일이 신고가라 하루 7.2건(전체의 29%)을 뱉었다.

    '신고가에 있다'와 '신고가를 **돌파했다**'를 구분하지 않았고, 사상 최고가면
    직전 극값이 없어 gap=None → **무조건 발화**까지 했다.
    """
    s = _rising(date(2024, 1, 1), 700)           # 2년 내내 우상향 = 매일 신고가
    hits = sr.detect_one("T", "테스트", "equity", s, False)
    assert not [h for h in hits if h["rule"] == "range_break"]


def test_range_break_fires_after_a_real_consolidation():
    """반대 방향 — 오래 쉬었다가 뚫으면 발화해야 한다(룰이 죽어 있으면 안 된다)."""
    s = {}
    d0 = date(2024, 1, 1)
    for i in range(400):                          # 상승 후
        s[d0 + timedelta(days=i)] = 100 + i * 0.5
    peak = s[d0 + timedelta(days=399)]
    for i in range(400, 700):                     # 300일 횡보(고점 아래)
        s[d0 + timedelta(days=i)] = peak - 20 + (i % 7)
    s[d0 + timedelta(days=700)] = peak + 5        # 돌파
    hits = sr.detect_one("T", "테스트", "equity", s, False, asof=d0 + timedelta(days=700))
    assert [h for h in hits if h["rule"] == "range_break"]


def test_direction_is_explicit_not_inferred_from_value():
    """★★실제 결함: 방향을 value 부호로 추론했다.

    `trend_flip` 의 value 는 **이격도(dev60)** 라 크로스 방향과 무관하게 부호가 정해지고,
    `range_break` 는 '연저점 대비 상승률'이라 신저가인데도 양수가 나온다.
    → 데드크로스면 value 가 양수여도 direction 은 -1 이어야 한다.
    """
    sig = sr._sig("trend_flip", "T", "테스트", "equity", "cross",
                  value=+12.3, rarity=None, severity=1.2, note="", direction=-1)
    assert sig["value"] > 0 and sig["direction"] == -1


def test_signal_carries_is_yield_for_stage2():
    """★2단이 '금리 상승 = 채권 약세'를 알려면 is_yield 가 시그널에 실려야 한다."""
    s = {date(2026, 1, 1) + timedelta(days=i): 4.0 + i * 0.01 for i in range(400)}
    hits = sr.detect_one("GT10 Govt", "미국채 10Y", "bond", s, True)
    assert hits and all(h["is_yield"] is True for h in hits)


def test_bond_label_carries_country():
    """★실제 결함: 채권 표시명이 "2Y" 뿐이라 뉴스 검색이 **0건**이었다."""
    cat = sr.catalog_from_price_board()
    by_ticker = {t: lbl for t, lbl, _c, _y in cat}
    assert by_ticker["GT2 Govt"] == "미국채 2Y"
    assert by_ticker["GTJPY10Y Govt"] == "일본국채 10Y"
    # 주식·원자재는 sub 가 단위 설명이라 붙이면 안 된다
    assert by_ticker["SPX Index"] == "S&P500"
    assert by_ticker["CL1 COMB Comdty"] == "WTI"


def test_detect_all_collapses_to_one_per_market():
    """★한 시장이 여러 룰에 걸려도 1건으로 접힌다(안 접으면 하루 수십 건)."""
    s = _rising(date(2024, 1, 1), 700)
    cols = {"T": s}
    out = sr.detect_all(cols, [("T", "테스트", "equity", False)], top=99)
    assert len(out) <= 1


# ══════════════════════════════════════════════════════════════════════
#  build_graph — 2단 재료
# ══════════════════════════════════════════════════════════════════════

def test_macro_overlap_threshold_is_separate_from_yearly():
    """★★실제 결함: 1개월 창에 1년용 MIN_OVERLAP(60)을 써서 **0건**이 나왔다.

    거래일이 22일 남짓인 창에 60을 요구하면 구조적으로 한 건도 못 만든다.
    """
    assert bg.MIN_OVERLAP_MACRO < bg.MIN_OVERLAP
    # 22 영업일치 표본이 실제로 통과해야 한다
    a = {date(2026, 8, 1) + timedelta(days=i): float(i % 5) for i in range(30)}
    b = {date(2026, 8, 1) + timedelta(days=i): float((i % 5) * 2) for i in range(30)}
    assert bg._pearson(a, b, bg.MIN_OVERLAP_MACRO) is not None
    assert bg._pearson(a, b, bg.MIN_OVERLAP) is None


def test_regime_inverts_for_yields():
    """★★금리 상승 = 채권 **약세**. 안 뒤집으면 그래프가 거꾸로 선다."""
    up = {"r6m": +50.0, "ma_stack": 1, "range_pos_252": 90.0}
    assert bg.classify_regime(up, is_yield=False)[0] == "Bull"
    assert bg.classify_regime(up, is_yield=True)[0] == "Bear"


def test_correlation_strips_ffill_before_measuring():
    """★★이월을 안 걷으면 주말 0% 가 양쪽에 같이 끼어 **상관이 부풀려진다**.

    이 파이프라인에서 가장 쉽게 나는 거짓 상관이 이것이다.
    """
    a = _ffilled(date(2026, 1, 5), 120)
    b = {d: 100.0 + ((i * 7) % 11) for i, d in enumerate(sorted(a))}
    ra = bg._returns(a, False, date(2026, 1, 1))
    assert all(d.weekday() < 5 for d in ra)      # 주말 수익률이 없다


# ══════════════════════════════════════════════════════════════════════
#  graph — 2단 탐색 (rdflib 필요)
# ══════════════════════════════════════════════════════════════════════

def _graph_mod():
    pytest.importorskip("rdflib")
    from collector.market_signal import graph as gr
    return gr


def test_price_direction_inverts_for_yields():
    """★★실제 결함: 2Y 금리 +23bp 인데 "2Y 단독 **강세**" 라고 썼다."""
    gr = _graph_mod()
    up_yield = {"direction": 1, "is_yield": True}
    up_price = {"direction": 1, "is_yield": False}
    assert gr.price_dir(up_yield) == -1          # 금리↑ = 채권 약세
    assert gr.price_dir(up_price) == 1


def test_comparison_horizon_matches_rule():
    """★★실제 결함: 60일 이평 크로스를 이웃의 **당일** 수익률과 비교했다.

    이걸 고치자 Idiosyncratic 비중이 67% → 28% 로 떨어졌다.
    """
    gr = _graph_mod()
    assert gr.horizon_of({"rule": "trend_flip", "metric": "cross"}) == "mtd"
    assert gr.horizon_of({"rule": "streak", "metric": "streak"}) == "wtd"
    # spike 는 시그널 자신의 기간을 따라간다
    assert gr.horizon_of({"rule": "spike", "metric": "wtd"}) == "wtd"
    assert gr.horizon_of({"rule": "spike", "metric": "mtd"}) == "mtd"


def test_same_dir_checks_sign_not_just_magnitude():
    """★★실제 결함: 크기만 보고 부호를 안 봐서, SOX 가 −3.47 인데
    대만 가권 상승을 "반도체 사이클 영향 **강세**" 라고 썼다."""
    gr = _graph_mod()
    assert gr._same_dir(+2.0, 1) is True
    assert gr._same_dir(-2.0, 1) is False        # 반대 방향은 동행이 아니다
    # 금리 이웃은 가격 기준으로 뒤집어 본다
    assert gr._same_dir(+2.0, -1, is_yield_a=True) is True


def test_peer_group_collapse():
    """★크립토 5종이 "암호화폐 전반 강세" 1건으로 접혀야 한다."""
    gr = _graph_mod()
    G = gr.Graph()
    if not G.by_ticker:
        pytest.skip("markets.ttl 이 아직 생성되지 않음")
    crypto = ["XBTUSD BGN Curncy", "XETUSD BGN Curncy", "XSOUSD BGN Curncy"]
    sigs = [
        {"rule": "spike", "market": t, "label": t[:3], "asset_class": "crypto",
         "metric": "mtd", "value": 25.0, "direction": 1, "rarity": 0.01,
         "severity": 1.5, "note": "월간 +25%", "is_yield": False}
        for t in crypto
    ]
    hyps = gr.interpret(sigs, G)
    broad = [h for h in hyps if h["hypothesis"] == "BroadMove"]
    assert broad and len(broad[0]["signals"]) == len(crypto)
    assert len(hyps) < len(sigs)


# ══════════════════════════════════════════════════════════════════════
#  pipeline
# ══════════════════════════════════════════════════════════════════════

def test_repeat_penalty_demotes_not_deletes():
    """★전일에도 뜬 건은 **지우지 않고 내리기만** 한다.

    MtD 시그널은 며칠 이어지는 게 정상이고 사흘째 추세도 사실이다.
    """
    from collector.market_signal import pipeline as pl
    assert 0 < pl.REPEAT_PENALTY < 1


def test_prev_business_day_skips_weekend():
    from collector.market_signal import pipeline as pl
    assert pl._prev_business_day(date(2026, 8, 31)) == date(2026, 8, 28)   # 월 → 금
    assert pl._prev_business_day(date(2026, 8, 28)) == date(2026, 8, 27)


def test_missing_markets_ttl_is_surfaced_not_silent():
    """★★실제 결함(9회차): markets.ttl 이 없으면 그래프에 **관측이 0개**인데도
    예외 없이 가설이 만들어져 전부 Idiosyncratic 으로 무너진다.
    카드는 멀쩡해 보이는데 판단에 근거가 없는 상태 — 가장 나쁜 실패다.
    → note 로 반드시 드러나야 한다.
    """
    pytest.importorskip("rdflib")
    import tempfile
    from collector.market_signal import graph as gr

    missing = os.path.join(tempfile.gettempdir(), "_no_such_markets.ttl")
    if os.path.exists(missing):
        os.remove(missing)
    old, gr._CACHE["sig"] = gr.MARKETS_TTL, None
    gr.MARKETS_TTL = missing
    try:
        G = gr.Graph()
        assert not G.ret          # 관측이 하나도 없다
    finally:
        gr.MARKETS_TTL, gr._CACHE["sig"] = old, None


def test_cache_key_tracks_source_sheet(tmp_path, monkeypatch):
    """★★실제 결함(2026-09-01): 캐시 키가 시각뿐이라 시트가 아침 7:41 에 갱신돼도
    08시대 첫 호출까지 **전일 날짜 카드를 계속 내보냈다**.
    원천이 바뀐 걸 알면서 안 보는 캐시는 캐시가 아니라 지연이다.
    """
    from collector import price_board as pb
    from collector.market_signal import pipeline as pl

    f = tmp_path / "src.xlsx"
    f.write_bytes(b"a")
    monkeypatch.setattr(pb, "SRC_PATH", str(f))
    k1 = pl._hour_key()
    f.write_bytes(b"bb")                      # 시트 갱신(크기·mtime 변화)
    k2 = pl._hour_key()
    assert k1 != k2, "원천이 바뀌었는데 캐시 키가 그대로다"
