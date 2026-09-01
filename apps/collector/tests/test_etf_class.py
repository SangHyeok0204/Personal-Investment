"""etf_class 회귀 테스트 — 국내상장 ETF 분류별 자금·수익률의 정의부.

워크북 판독(openpyxl)은 겨누지 않는다. 여기서 지키는 건 **정의** 넷이고, 넷 다
이 화면이 틀린 말을 하게 되는 자리다:

  1) 네 창(1주·1개월·3개월·6개월)은 전부 오늘로 끝나 서로 포갠다. 구간 분해는
     누적끼리 빼서 만들어야 하고, Σ구간 == 누적6m 이 성립해야 한다.
  2) 구간 수익률은 **복리 체인**이다. 빼기가 아니다 — Π(1+구간) == 1+누적6m.
  3) 분류 수익률은 종목 단위로 구간을 만든 뒤 가중한다. 결측 종목의 시총은 분모에서
     빠져야 한다(안 그러면 그 분류만 0 쪽으로 끌려 내려간다).
  4) 강도(net/시총 %)는 절대 억원과 순위가 실제로 갈린다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import etf_class as ec  # noqa: E402


def _etf(**kw):
    base = dict(
        code="000000", name="ETF", listed="2020-01-01", country="한국",
        gubun="시장&전략", big="시장형", mid="코스피", small="코스피200",
        amt=100.0, net=10.0, chg=0.01, price=10000.0, mcap=1000.0,
        mmt_1w=0.02, mmt_1m=0.05, mmt_3m=0.10, mmt_6m=0.20,
        ff_1w=100.0, ff_1m=300.0, ff_3m=900.0, ff_6m=1500.0,
        interest=False,
    )
    base.update(kw)
    return base


# ── 1) 겹치는 창 → 겹치지 않는 구간 ────────────────────────────────────────

def test_interval_net_is_difference_not_the_cumulative_itself():
    """1주 100 · 1개월 300 · 3개월 900 · 6개월 1500 이면 구간은 100/200/600/600."""
    m = ec._etf_metrics(_etf())
    assert m["net_iv"]["1w"] == pytest.approx(100.0)
    assert m["net_iv"]["1m"] == pytest.approx(200.0)
    assert m["net_iv"]["3m"] == pytest.approx(600.0)
    assert m["net_iv"]["6m"] == pytest.approx(600.0)
    # ★항등식 — 이게 깨지면 같은 돈을 두 번 센 것이다.
    assert sum(m["net_iv"].values()) == pytest.approx(m["net_cum"]["6m"])


def test_interval_return_is_a_compound_chain_not_a_subtraction():
    m = ec._etf_metrics(_etf())
    # 1주~1개월 = (1.05/1.02)-1 = +2.94%  (빼기였다면 +3.00%)
    assert m["ret_iv"]["1m"] == pytest.approx(1.05 / 1.02 - 1)
    assert m["ret_iv"]["1m"] != pytest.approx(0.03)
    prod = 1.0
    for k in ("1w", "1m", "3m", "6m"):
        prod *= 1 + m["ret_iv"][k]
    assert prod == pytest.approx(1 + m["ret_cum"]["6m"])


def test_missing_cumulative_does_not_invent_a_value():
    m = ec._etf_metrics(_etf(ff_3m=None, mmt_3m=None))
    assert m["net_iv"]["3m"] is None
    assert m["ret_iv"]["3m"] is None
    # -100% 는 나눌 수 없다 — 체인 대신 결측을 낸다.
    assert ec._chain(0.1, -1.0) is None


# ── 2) 집계 ────────────────────────────────────────────────────────────────

def test_group_return_is_cap_weighted_and_skips_missing_in_the_denominator():
    """수익률이 없는 종목의 시총은 분모에 남으면 안 된다."""
    etfs = [
        _etf(code="A", mcap=1000.0, chg=0.10),
        _etf(code="B", mcap=9000.0, chg=None),   # 결측 — 분모에서 빠져야 한다
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    (row,) = rows
    assert row["ret_cum"]["d"] == pytest.approx(0.10)   # 0.10, 0.01 이 아니다
    assert row["ret_cum_eq"]["d"] == pytest.approx(0.10)
    assert row["mcap"] == pytest.approx(10000.0)        # 시총 합계는 그대로


def test_group_net_is_a_plain_sum_and_ratio_is_scaled_by_group_cap():
    etfs = [
        _etf(code="A", mcap=1000.0, net=30.0),
        _etf(code="B", mcap=3000.0, net=-10.0),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    (row,) = rows
    assert row["net_cum"]["d"] == pytest.approx(20.0)
    assert row["ratio_cum"]["d"] == pytest.approx(20.0 / 4000.0 * 100)


def test_amount_and_intensity_actually_reorder_the_ranking():
    """작은 분류에 몰린 돈이 큰 분류의 절대 금액에 묻히는 자리 — 강도가 그걸 뒤집는다."""
    etfs = [
        _etf(code="BIG", mid="큰분류", mcap=1_000_000.0, net=5000.0),
        _etf(code="SML", mid="작은분류", mcap=1_000.0, net=500.0),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    by_amount = sorted(rows, key=lambda r: -r["net_cum"]["d"])[0]["label"]
    by_ratio = sorted(rows, key=lambda r: -r["ratio_cum"]["d"])[0]["label"]
    assert by_amount == "큰분류"
    assert by_ratio == "작은분류"


def test_group_key_carries_the_ancestor_path_so_same_names_do_not_merge():
    """소분류 이름은 중분류가 다르면 겹칠 수 있다 — 키가 조상 경로를 물고 있어야 한다."""
    etfs = [
        _etf(code="A", big="시장형", mid="코스피", small="반도체"),
        _etf(code="B", big="AI 테크", mid="AI 컴퓨팅", small="반도체"),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "small")
    assert len(rows) == 2
    assert {r["key"] for r in rows} == {
        "시장&전략 / 시장형 / 코스피 / 반도체",
        "시장&전략 / AI 테크 / AI 컴퓨팅 / 반도체",
    }
    # 라벨은 둘 다 '반도체' — 화면은 path 로 구별한다.
    assert {r["label"] for r in rows} == {"반도체"}


def test_blank_classification_becomes_its_own_bucket_not_a_silent_drop():
    etfs = [_etf(code="A", mid=""), _etf(code="B", mid="코스피")]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    assert {r["label"] for r in rows} == {"미분류", "코스피"}
    assert sum(r["n"] for r in rows) == 2
