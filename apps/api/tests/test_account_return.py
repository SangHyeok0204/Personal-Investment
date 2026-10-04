"""내 계좌 수익률 — ★2026-10-04 사용자 지정, 성과 분석 화면들의 정본.

    수익률(t) = (총기간 손익(t) − unrealized_at_start) ÷ (A0 + 순외부입금 누적(t))

지키는 것:
  1) 기준점(시작일 − 1일)은 손익 0 · 원금 A0 · 수익률 0 이다.
  2) 입금 날 수익률이 꺾이지 않는다 — 입금은 분모만 올리고 손익은 그대로다.
  3) 출금은 분모를 내린다.
  4) 모르는 날(손익 None · 흐름 칸이 빈 행)은 0 이 아니라 None 이다.
  5) 오늘 점은 /pnl-breakdown 의 live 점(실현 + 키움 실제 평가)과 같은 손익을 쓴다.
  6) 숫자가 맞물린다: 손익 = 실현 + (평가 − 시작 평가), 원금 − A0 = 흐름 누적,
     수익률 × 원금 = 손익.
  7) 원화 실질(환차 포함) = (총자산 − 원금) ÷ 원금. 기준점 0, 총자산·원금을 모르면 None.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core import account_return as ar
from app.core import pnl_breakdown as pb
from app.core.investing import INVESTMENT_START
from app.models import AccountDailyPerformance

from tests.test_pnl_breakdown import _seed
from tests.test_portfolio import kiwoom  # noqa: F401 - 픽스처 재사용

D = date.fromisoformat
S = D("2026-06-01")


def _pnl(values: list[Decimal | None]) -> list[pb.Point]:
    """총기간 손익만 의미가 있는 pnl_breakdown 점(시작일부터 하루씩)."""
    return [
        pb.Point(date=S + timedelta(days=i), realized_cum_krw=Decimal("0"),
                 unrealized_krw=None, total_period_pnl_krw=v, total_value_krw=None)
        for i, v in enumerate(values)
    ]


# ── 순수 함수 ────────────────────────────────────────────────────────────────

def test_baseline_is_zero_and_unrealized_at_start_is_removed():
    # 시작 시점 평가익 1,000 이 총기간 손익에 이미 들어 있다 — 빼야 첫날이 0 근처다.
    points = ar.build(_pnl([Decimal("1000"), Decimal("1100")]), Decimal("1000"),
                      Decimal("10000"), {S: Decimal("0"), S + timedelta(days=1): Decimal("0")})
    base = points[0]
    assert base.date == S - timedelta(days=1)
    assert base.pnl_since_start_krw == Decimal("0")
    assert base.invested_krw == Decimal("10000")
    assert base.return_ratio == Decimal("0")
    # 시작일 손익이 0 이면 수익률도 0 — 시작 평가익(1,000 ÷ 10,000 = +10%)이 새지 않는다.
    assert points[1].return_ratio == Decimal("0")
    assert points[2].pnl_since_start_krw == Decimal("100")
    assert points[2].return_ratio == Decimal("0.01")


def test_deposit_does_not_drop_the_return():
    """입금 5,000 이 들어온 날: 손익은 그대로(+100), 분모만 10,000 → 15,000."""
    points = ar.build(
        _pnl([Decimal("100"), Decimal("100"), Decimal("100")]), Decimal("0"), Decimal("10000"),
        {S: Decimal("0"), S + timedelta(days=1): Decimal("5000"),
         S + timedelta(days=2): Decimal("0")},
    )
    _, d0, d1, d2 = points
    assert d0.return_ratio == Decimal("0.01")
    assert d1.net_flow_krw == Decimal("5000")
    assert d1.invested_krw == Decimal("15000")
    assert d1.cum_net_flow_krw == Decimal("5000")
    assert d1.pnl_since_start_krw == Decimal("100")
    # 희석될 뿐 음수가 되지 않는다.
    assert d1.return_ratio is not None and d1.return_ratio > 0
    assert d1.return_ratio == Decimal("0.006667")
    assert d2.invested_krw == Decimal("15000")


def test_withdrawal_lowers_the_denominator():
    points = ar.build(
        _pnl([Decimal("200"), Decimal("200")]), Decimal("0"), Decimal("10000"),
        {S: Decimal("0"), S + timedelta(days=1): Decimal("-2000")},
    )
    assert points[1].return_ratio == Decimal("0.02")
    assert points[2].net_flow_krw == Decimal("-2000")
    assert points[2].invested_krw == Decimal("8000")
    assert points[2].return_ratio == Decimal("0.025")


def test_unknown_days_stay_null_not_zero():
    points = ar.build(
        _pnl([Decimal("100"), None, Decimal("300"), Decimal("400")]), Decimal("0"),
        Decimal("10000"),
        # S+1 행 없음(손익도 None), S+2 행은 있으나 흐름 칸이 비었다.
        {S: Decimal("0"), S + timedelta(days=2): None, S + timedelta(days=3): Decimal("0")},
    )
    _, d0, d1, d2, d3 = points
    assert d0.return_ratio == Decimal("0.01")
    # 손익을 모르는 날은 수익률도 None. 행이 없는 날 원금은 앞 값이 이어진다.
    assert d1.pnl_since_start_krw is None and d1.return_ratio is None
    assert d1.invested_krw == Decimal("10000")
    # 흐름을 모르는 날부터 뒤로 원금·수익률 모두 None — 0 으로 읽지 않는다.
    for p in (d2, d3):
        assert p.cum_net_flow_krw is None
        assert p.invested_krw is None
        assert p.return_ratio is None
        assert p.pnl_since_start_krw is not None  # 손익 자체는 안다


def test_unknown_start_assets_or_unrealized_is_null():
    no_a0 = ar.build(_pnl([Decimal("100")]), Decimal("0"), None, {S: Decimal("0")})
    assert no_a0[0].return_ratio is None
    assert no_a0[1].invested_krw is None and no_a0[1].return_ratio is None
    no_base = ar.build(_pnl([Decimal("100")]), None, Decimal("10000"), {S: Decimal("0")})
    assert no_base[1].pnl_since_start_krw is None and no_base[1].return_ratio is None
    assert ar.build([], Decimal("0"), Decimal("1"), {}) == []


def test_numbers_reconcile_on_every_point():
    daily = {S + timedelta(days=i): Decimal(v) for i, v in enumerate(["50", "-20", "70", "10"])}
    realized = {S + timedelta(days=2): Decimal("40")}
    before = {S - timedelta(days=3): Decimal("500")}
    pnl_points = pb.build_series(S, S + timedelta(days=3), {**before, **daily}, realized, {})
    at_start = pb.unrealized_at_start(S, {**before, **daily}, realized)
    flows = {S: Decimal("0"), S + timedelta(days=1): Decimal("3000"),
             S + timedelta(days=2): Decimal("-500"), S + timedelta(days=3): Decimal("0")}
    a0 = Decimal("20000")
    points = ar.build(pnl_points, at_start, a0, flows)
    for pnl_p, p in zip(pnl_points, points[1:]):
        # 손익 = 실현(시작일~) + (평가 − 시작 평가) = 총기간 − 시작 평가.
        assert p.pnl_since_start_krw == (
            pnl_p.realized_cum_krw + pnl_p.unrealized_krw - at_start
        )
        assert p.invested_krw - a0 == p.cum_net_flow_krw
        # 수익률은 소수 6자리로 반올림한다 — 원금 × 0.5e-6 안에서 맞는다.
        assert abs(p.return_ratio * p.invested_krw - p.pnl_since_start_krw) <= (
            p.invested_krw * Decimal("0.0000005")
        )
    assert points[-1].cum_net_flow_krw == Decimal("2500")
    # 일별 손익 합(110)이 시작일 이후 손익이다.
    assert points[-1].pnl_since_start_krw == Decimal("110")


def _with_assets(values: list[tuple[Decimal | None, Decimal | None]]) -> list[pb.Point]:
    """(총기간 손익, 총자산) 짝으로 만든 pnl_breakdown 점."""
    return [
        pb.Point(date=S + timedelta(days=i), realized_cum_krw=Decimal("0"),
                 unrealized_krw=None, total_period_pnl_krw=pnl, total_value_krw=assets)
        for i, (pnl, assets) in enumerate(values)
    ]


def test_krw_real_return_uses_total_assets_minus_invested():
    """키움 손익은 +100(+1%)인데 환산 손실로 총자산은 9,700 — 원화 실질은 −3%.
    입금 5,000 날: 총자산 14,800 − 원금 15,000 = −200 → −1.3333%."""
    points = ar.build(
        _with_assets([(Decimal("100"), Decimal("9700")), (Decimal("100"), Decimal("14800"))]),
        Decimal("0"), Decimal("10000"),
        {S: Decimal("0"), S + timedelta(days=1): Decimal("5000")},
    )
    base, d0, d1 = points
    assert base.krw_pnl_since_start_krw == Decimal("0")
    assert base.krw_return_ratio == Decimal("0")
    assert d0.return_ratio == Decimal("0.01")  # 환율 제외는 그대로
    assert d0.krw_pnl_since_start_krw == Decimal("-300")
    assert d0.krw_return_ratio == Decimal("-0.03")
    assert d1.krw_pnl_since_start_krw == Decimal("-200")
    assert d1.krw_return_ratio == Decimal("-0.013333")


def test_krw_real_unknown_stays_null():
    points = ar.build(
        _with_assets([(Decimal("100"), None), (Decimal("100"), Decimal("10100")),
                      (Decimal("100"), Decimal("10100"))]),
        Decimal("0"), Decimal("10000"),
        # S+2 흐름 칸이 비었다 → 원금을 모른다.
        {S: Decimal("0"), S + timedelta(days=1): Decimal("0"), S + timedelta(days=2): None},
    )
    _, d0, d1, d2 = points
    # 총자산을 모르면 None — 0 으로 읽어 −100% 가 되지 않는다.
    assert d0.krw_pnl_since_start_krw is None and d0.krw_return_ratio is None
    assert d1.krw_return_ratio == Decimal("0.01")
    # 원금을 모르면 None.
    assert d2.krw_pnl_since_start_krw is None and d2.krw_return_ratio is None
    # A0 를 모르면 기준점부터 None.
    no_a0 = ar.build(_with_assets([(Decimal("1"), Decimal("1"))]), Decimal("0"), None,
                     {S: Decimal("0")})
    assert no_a0[0].krw_return_ratio is None and no_a0[1].krw_return_ratio is None


# ── API ──────────────────────────────────────────────────────────────────────

def test_account_return_without_accounts_is_null(client):
    body = client.get("/api/v1/portfolio/account-return").json()
    assert body["start"] == INVESTMENT_START.isoformat()
    assert body["items"] == []
    for key in ("return_ratio", "pnl_since_start_krw", "invested_krw", "start_assets_krw"):
        assert body[key] is None


def test_today_point_matches_live_values(client, db, kiwoom):  # noqa: F811
    first = INVESTMENT_START - timedelta(days=400)
    account_id = kiwoom["account"].id
    _seed(db, account_id, first)
    # 시작일 두 번째 날(S+2) 입금 100,000 · S+3 출금 20,000.
    rows = {
        r.base_date: r for r in db.query(AccountDailyPerformance).filter(
            AccountDailyPerformance.base_date >= INVESTMENT_START
        )
    }
    for day, row in rows.items():
        row.deposit_krw = Decimal("100000") if day == INVESTMENT_START + timedelta(days=2) else 0
        row.withdrawal_krw = Decimal("20000") if day == INVESTMENT_START + timedelta(days=3) else 0
    db.commit()

    body = client.get("/api/v1/portfolio/account-return").json()
    pnl = client.get("/api/v1/portfolio/pnl-breakdown").json()

    # A0 = 시작일 앞 마지막 일별 행의 총자산(first+4 의 499,800).
    assert Decimal(body["start_assets_krw"]) == Decimal("499800")
    assert body["unrealized_at_start_krw"] == pnl["unrealized_at_start_krw"]
    assert body["flows_until"] == (INVESTMENT_START + timedelta(days=3)).isoformat()

    # 지금 값 = 오늘 live 점 = (pnl-breakdown 총기간 − 시작 평가) ÷ (A0 + 80,000).
    expected_pnl = Decimal(pnl["total_period_pnl_krw"]) - Decimal(pnl["unrealized_at_start_krw"])
    assert Decimal(body["pnl_since_start_krw"]) == expected_pnl
    assert Decimal(body["cum_net_flow_krw"]) == Decimal("80000")
    assert Decimal(body["invested_krw"]) == Decimal("579800")
    assert Decimal(body["return_ratio"]) == (expected_pnl / Decimal("579800")).quantize(
        Decimal("0.000001")
    )
    last = body["items"][-1]
    assert last["date"] == pnl["items"][-1]["date"] == body["return_date"]
    assert last["return_ratio"] == body["return_ratio"]
    # 원화 실질 = (오늘 총자산(pnl-breakdown live) − 원금) ÷ 원금.
    expected_krw = Decimal(pnl["total_value_krw"]) - Decimal("579800")
    assert Decimal(body["krw_pnl_since_start_krw"]) == expected_krw
    assert Decimal(body["krw_return_ratio"]) == (expected_krw / Decimal("579800")).quantize(
        Decimal("0.000001")
    )
    assert last["krw_return_ratio"] == body["krw_return_ratio"]

    by = {i["date"]: i for i in body["items"]}
    day = lambda n: by[(INVESTMENT_START + timedelta(days=n)).isoformat()]  # noqa: E731
    base = by[(INVESTMENT_START - timedelta(days=1)).isoformat()]
    assert Decimal(base["return_ratio"]) == 0 and Decimal(base["pnl_since_start_krw"]) == 0
    # 시작일 손익 50 ÷ 499,800.
    assert Decimal(day(0)["pnl_since_start_krw"]) == Decimal("50")
    # 행이 없는 날은 null.
    assert day(1)["return_ratio"] is None
    # 입금 날: 손익은 그대로(50), 분모만 오른다 — 음수가 되지 않는다.
    assert Decimal(day(2)["net_flow_krw"]) == Decimal("100000")
    assert Decimal(day(2)["pnl_since_start_krw"]) == Decimal("50")
    assert Decimal(day(2)["return_ratio"]) > 0
    assert Decimal(day(3)["invested_krw"]) == Decimal("579800")
    # S+3 행 총자산 599,980 − 원금 579,800 = 20,180.
    assert Decimal(day(3)["krw_pnl_since_start_krw"]) == Decimal("20180")
    assert Decimal(base["krw_return_ratio"]) == 0


# ── 벤치마크(투자 시작일 이후) ────────────────────────────────────────────────

def test_benchmark_shows_usd_and_krw_with_latest_index_close(client, db, kiwoom, monkeypatch):  # noqa: F811
    """★2026-10-04: USD(지수 자체)와 원화 환산을 둘 다 낸다. 지수의 끝은 **그 지수의 마지막
    종가**다 — 계좌 마지막 일별 행(S+3)에 묶이지 않는다."""
    from prices.history import Series

    _seed(db, kiwoom["account"].id, INVESTMENT_START - timedelta(days=400))
    for row in db.query(AccountDailyPerformance):
        row.deposit_krw = row.withdrawal_krw = Decimal("0")
    db.commit()
    base = INVESTMENT_START - timedelta(days=3)  # 시작일 앞 마지막 종가(금요일 같은 날)
    last = INVESTMENT_START + timedelta(days=10)  # 계좌 마지막 일별 행(S+3)보다 뒤
    spx = Series(symbol="^GSPC", dates=[base, INVESTMENT_START + timedelta(days=2), last],
                 closes=[Decimal("100"), Decimal("101"), Decimal("110")],
                 currency="USD", latest=Decimal("110"))
    fx = Series(symbol="KRW=X", dates=[base, last],
                closes=[Decimal("1500"), Decimal("1350")], currency="KRW",
                latest=Decimal("1350"))
    monkeypatch.setattr(
        "app.api.portfolio.fetch_history", lambda *a, **k: {"^GSPC": spx, "KRW=X": fx}
    )

    body = client.get("/api/v1/portfolio/benchmark").json()
    ss = body["since_start"]
    assert ss["base_date"] == (INVESTMENT_START - timedelta(days=1)).isoformat()
    (spx_out,) = ss["indices"]
    assert spx_out["base_date"] == base.isoformat()
    assert spx_out["end_date"] == last.isoformat()  # 지수 자신의 마지막 종가
    assert spx_out["fx_end_date"] == last.isoformat()
    assert Decimal(spx_out["return_usd"]) == Decimal("0.1")
    # 원화 = 110 × 1,350 ÷ (100 × 1,500) − 1 = −1%. 환율 −10%.
    assert Decimal(spx_out["return_krw"]) == Decimal("-0.01")
    assert Decimal(spx_out["fx_change"]) == Decimal("-0.1")

    # 계좌는 /account-return 과 같은 값 — 자기 마지막 점(오늘).
    acct = client.get("/api/v1/portfolio/account-return").json()
    assert acct["return_ratio"] is not None
    assert ss["account_return"] == acct["return_ratio"]
    assert ss["account_date"] == acct["return_date"] == acct["items"][-1]["date"]
    # 원화 실질(환차 포함)도 같은 출처 — 지수 원화 환산과 짝.
    assert ss["account_return_krw"] == acct["krw_return_ratio"]
    assert ss["account_krw_date"] == acct["items"][-1]["date"]

    by = {p["date"]: p for p in ss["series"]}
    first = ss["series"][0]
    assert first["date"] == ss["base_date"]
    assert Decimal(first["account"]) == Decimal("100")
    assert Decimal(first["account_krw"]) == Decimal("100")
    assert Decimal(first["benchmarks_usd"]["S&P 500"]) == Decimal("100")
    end = by[last.isoformat()]
    assert Decimal(end["benchmarks_usd"]["S&P 500"]) == Decimal("110")
    assert Decimal(end["benchmarks_krw"]["S&P 500"]) == Decimal("99")
    # 지수 마지막 종가 뒤는 null — 앞 값을 끌어오지 않는다.
    after = by.get((last + timedelta(days=1)).isoformat())
    if after is not None:
        assert after["benchmarks_usd"]["S&P 500"] is None
