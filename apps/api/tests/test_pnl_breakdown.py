"""손익 분해 — 총기간 손익 · 실현손익(누적) · 평가손익 · 총 평가액.

지키는 것:
  1) 총기간 손익은 키움 일별 손익의 **누적 합**이다. 조회 창을 줄여도 창 시작에서
     0 으로 되돌리지 않는다. 실현손익(누적)도 마찬가지.
  2) 평가손익 = 총기간 손익 − 실현손익(누적). 모든 점에서 성립한다(오늘 포함).
  3) 모르는 날은 0 이 아니라 None 이다. 주말처럼 손익 0 인 **행이 있는** 날은 전날
     값이 이어진다.
  4) 이 화면은 **첫 거래일부터** 센다 — 투자 시작일(INVESTMENT_START)로 자르지 않는다.
  5) 오늘 점 = 실현(누적) + 키움 실제 평가손익(/summary). 타일과 그래프 끝점이 같다.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core import pnl_breakdown as pb
from app.core.investing import INVESTMENT_START
from app.models import AccountDailyPerformance, Dividend, PortfolioSnapshot, RealizedPnl

from tests.test_portfolio import kiwoom  # noqa: F401 - 픽스처 재사용

D = date.fromisoformat
KST = timezone(timedelta(hours=9))


# ── 순수 함수 ────────────────────────────────────────────────────────────────

def test_total_period_is_running_sum_of_daily_pnl():
    points = pb.build_series(
        D("2026-07-01"), D("2026-07-04"),
        {D("2026-07-01"): Decimal("100"), D("2026-07-02"): Decimal("-30"),
         D("2026-07-03"): Decimal("0"), D("2026-07-04"): Decimal("5")},
        {}, {},
    )
    assert [p.total_period_pnl_krw for p in points] == [
        Decimal("100.00"), Decimal("70.00"), Decimal("70.00"), Decimal("75.00"),
    ]


def test_running_sums_are_seeded_from_before_the_window():
    """창을 줄여도 누적은 첫 거래부터다 — 창 앞의 손익·실현분이 출발값이 된다."""
    points = pb.build_series(
        D("2026-07-10"), D("2026-07-11"),
        {D("2025-04-08"): Decimal("500"), D("2026-07-10"): Decimal("1"),
         D("2026-07-11"): Decimal("2")},
        {D("2025-06-09"): Decimal("300"), D("2026-07-11"): Decimal("20")},
        {},
    )
    assert [p.total_period_pnl_krw for p in points] == [Decimal("501.00"), Decimal("503.00")]
    assert [p.realized_cum_krw for p in points] == [Decimal("300.00"), Decimal("320.00")]


def test_realized_accumulates_day_by_day():
    points = pb.build_series(
        D("2026-07-01"), D("2026-07-04"),
        {},
        {D("2026-07-01"): Decimal("100"), D("2026-07-03"): Decimal("-30")},
        {},
    )
    # 매도가 없는 날은 전날과 같다(0 이 아니다).
    assert [p.realized_cum_krw for p in points] == [
        Decimal("100.00"), Decimal("100.00"), Decimal("70.00"), Decimal("70.00"),
    ]


def test_unrealized_is_total_period_minus_realized_everywhere():
    live = pb.Live(date=D("2026-07-04"), unrealized_krw=Decimal("900"),
                   total_value_krw=Decimal("5000"))
    points = pb.build_series(
        D("2026-07-01"), D("2026-07-04"),
        {D("2026-07-01"): Decimal("1000"), D("2026-07-02"): Decimal("-200"),
         D("2026-07-03"): Decimal("50")},
        {D("2026-07-02"): Decimal("300"), D("2026-07-04"): Decimal("10")},
        {},
        live,
    )
    for p in points:
        assert p.unrealized_krw == p.total_period_pnl_krw - p.realized_cum_krw
    assert points[1].unrealized_krw == Decimal("500.00")  # 800 − 300


def test_live_point_uses_actual_unrealized():
    """오늘 = 실현(누적) + 실제 평가손익 — 일별 손익 누적이 아니다."""
    live = pb.Live(date=D("2026-07-03"), unrealized_krw=Decimal("700"),
                   total_value_krw=Decimal("12345"))
    points = pb.build_series(
        D("2026-07-02"), D("2026-07-03"),
        {D("2026-07-02"): Decimal("1000")},
        {D("2026-07-01"): Decimal("100")},
        {D("2026-07-02"): Decimal("9999")},
        live,
    )
    today = points[-1]
    assert today.unrealized_krw == Decimal("700.00")
    assert today.total_period_pnl_krw == Decimal("800.00")
    assert today.total_value_krw == Decimal("12345.00")
    # 오늘 평가손익을 모르면 총기간 손익도 모른다 — 실현손익으로 채우지 않는다.
    blind = pb.build_series(D("2026-07-03"), D("2026-07-03"), {}, {}, {},
                            pb.Live(date=D("2026-07-03"), unrealized_krw=None,
                                    total_value_krw=None))
    assert blind[0].total_period_pnl_krw is None and blind[0].unrealized_krw is None


def test_missing_days_stay_null_but_zero_rows_carry_forward():
    """행이 없는 날은 None. 손익 0 인 행(주말)은 전날 값이 이어진다."""
    points = pb.build_series(
        D("2026-07-03"), D("2026-07-07"),
        {
            D("2026-07-03"): Decimal("100"),
            D("2026-07-04"): Decimal("0"),   # 토 — 행이 있다
            D("2026-07-05"): Decimal("0"),   # 일 — 행이 있다
            # 07-06 은 행이 없다
            D("2026-07-07"): Decimal("40"),
        },
        {D("2026-07-03"): Decimal("30")},
        {D("2026-07-03"): Decimal("1000000")},
    )
    by = {p.date: p for p in points}
    assert by[D("2026-07-04")].total_period_pnl_krw == Decimal("100.00")
    assert by[D("2026-07-05")].total_period_pnl_krw == Decimal("100.00")
    gap = by[D("2026-07-06")]
    assert gap.total_period_pnl_krw is None and gap.unrealized_krw is None
    assert gap.realized_cum_krw == Decimal("30.00")
    assert gap.total_value_krw is None
    # 빈 날 뒤에도 있는 행은 계속 더한다.
    assert by[D("2026-07-07")].total_period_pnl_krw == Decimal("140.00")
    # 손익이 빈(None) 행도 0 으로 보지 않는다.
    null_row = pb.build_series(D("2026-07-01"), D("2026-07-01"),
                               {D("2026-07-01"): None}, {}, {})
    assert null_row[0].total_period_pnl_krw is None


def test_empty_when_window_is_inverted():
    assert pb.build_series(D("2026-09-22"), D("2026-09-21"), {}, {}, {}) == []


# ── API ──────────────────────────────────────────────────────────────────────

def test_breakdown_without_accounts_returns_nulls(client):
    body = client.get("/api/v1/portfolio/pnl-breakdown").json()
    assert body["items"] == []
    for key in ("realized_cum_krw", "unrealized_krw", "total_period_pnl_krw",
                "total_value_krw", "cash_krw", "since", "daily_pnl_until"):
        assert body[key] is None


def _seed(db, account_id, first: date):
    """첫 거래일(투자 시작 **앞**)부터 이틀 + 주말 0 행 + 빈 날 + 하루."""
    snap_day = first + timedelta(days=5)
    db.add_all([
        AccountDailyPerformance(id=uuid.uuid4(), account_id=account_id, base_date=first,
                                pnl_krw=Decimal("1000"), deposit_assets_krw=Decimal("500000")),
        AccountDailyPerformance(id=uuid.uuid4(), account_id=account_id,
                                base_date=first + timedelta(days=1),
                                pnl_krw=Decimal("0"), deposit_assets_krw=Decimal("500000")),
        AccountDailyPerformance(id=uuid.uuid4(), account_id=account_id,
                                base_date=first + timedelta(days=2),
                                pnl_krw=Decimal("0"), deposit_assets_krw=Decimal("500000")),
        # first+3 은 행이 없다(모르는 날).
        AccountDailyPerformance(id=uuid.uuid4(), account_id=account_id,
                                base_date=first + timedelta(days=4),
                                pnl_krw=Decimal("-200"), deposit_assets_krw=Decimal("499800")),
        # 투자 시작 전 매도 — **누적에 넣는다**(이 화면은 첫 거래부터).
        RealizedPnl(
            id=uuid.uuid4(), account_id=account_id, ticker="TSL",
            sell_date=first + timedelta(days=1), quantity=Decimal("1"), currency="USD",
            pnl_krw=Decimal("300"), commission_tax_krw=Decimal("10"),
        ),
        RealizedPnl(
            id=uuid.uuid4(), account_id=account_id, ticker="NVDA",
            sell_date=INVESTMENT_START + timedelta(days=3), quantity=Decimal("4"),
            currency="USD", pnl_krw=Decimal("50682"), commission_tax_krw=Decimal("1000"),
        ),
        Dividend(
            id=uuid.uuid4(), account_id=account_id, ticker="SCHD",
            pay_date=first + timedelta(days=4), amount_krw=Decimal("31107"), currency="KRW",
        ),
        # 일별 행이 없는 날의 총 평가액은 그날 마지막 스냅샷으로 채운다.
        PortfolioSnapshot(
            id=uuid.uuid4(), account_id=account_id,
            snapshot_at=datetime.combine(snap_day, datetime.min.time(), tzinfo=KST)
            + timedelta(hours=9),
            total_unrealized_pnl_krw=Decimal("111"), total_assets_krw=Decimal("777"),
        ),
    ])
    db.commit()


def test_breakdown_counts_from_first_trade_not_investment_start(client, db, kiwoom):  # noqa: F811
    first = INVESTMENT_START - timedelta(days=400)
    _seed(db, kiwoom["account"].id, first)

    body = client.get("/api/v1/portfolio/pnl-breakdown").json()
    summary = client.get("/api/v1/portfolio/summary").json()
    realized_screen = client.get("/api/v1/portfolio/realized?days=3650").json()

    # 첫 거래일부터 — 투자 시작일로 자르지 않는다.
    assert body["since"] == first.isoformat()
    assert body["items"][0]["date"] == first.isoformat()
    assert Decimal(body["realized_trading_krw"]) == Decimal("50982")  # 300 + 50,682
    assert Decimal(body["dividend_krw"]) == Decimal("31107")
    assert Decimal(body["realized_cum_krw"]) == Decimal("82089")
    # /realized 는 투자 시작일로 자른다 — 그 차이가 시작 전 실현분(매매 300 + 배당 31,107)이다.
    assert Decimal(body["realized_cum_krw"]) - Decimal(
        realized_screen["breakdown"]["net_krw"]
    ) == Decimal("31407")

    # 지금 값: 평가손익·총 평가액은 /summary 그대로, 총기간 = 실현 + 평가.
    assert body["unrealized_krw"] == summary["unrealized_pnl_krw"]
    assert body["total_value_krw"] == summary["total_assets_krw"]
    assert body["cash_krw"] == summary["cash_krw"]
    assert Decimal(body["total_period_pnl_krw"]) == (
        Decimal(body["realized_cum_krw"]) + Decimal(body["unrealized_krw"])
    )
    assert body["daily_pnl_until"] == (first + timedelta(days=4)).isoformat()

    items = body["items"]
    # 오늘 점은 타일과 같다.
    last = items[-1]
    for key in ("realized_cum_krw", "unrealized_krw", "total_period_pnl_krw", "total_value_krw"):
        assert last[key] == body[key]
    # 등식은 모든 점에서.
    for p in items:
        if p["total_period_pnl_krw"] is not None:
            assert Decimal(p["unrealized_krw"]) == (
                Decimal(p["total_period_pnl_krw"]) - Decimal(p["realized_cum_krw"])
            )

    by = {i["date"]: i for i in items}
    day = lambda n: by[(first + timedelta(days=n)).isoformat()]  # noqa: E731
    assert Decimal(day(0)["total_period_pnl_krw"]) == Decimal("1000")
    # 주말(손익 0 행)은 전날 값이 이어지고, 실현분만큼 평가손익이 줄어든다.
    assert Decimal(day(2)["total_period_pnl_krw"]) == Decimal("1000")
    assert Decimal(day(2)["unrealized_krw"]) == Decimal("700")
    # 행이 없는 날은 null — 0 이 아니다.
    assert day(3)["total_period_pnl_krw"] is None
    assert day(3)["unrealized_krw"] is None
    assert day(3)["total_value_krw"] is None
    assert Decimal(day(3)["realized_cum_krw"]) == Decimal("300")
    assert Decimal(day(4)["total_period_pnl_krw"]) == Decimal("800")
    assert Decimal(day(4)["realized_cum_krw"]) == Decimal("31407")
    # 일별 행이 없는 날의 총 평가액은 스냅샷, 그 뒤 일별 행도 없으면 null.
    assert Decimal(day(5)["total_value_krw"]) == Decimal("777")
    assert day(5)["total_period_pnl_krw"] is None
    assert day(6)["total_value_krw"] is None


def test_breakdown_window_keeps_running_totals(client, db, kiwoom):  # noqa: F811
    """days 로 창을 줄여도 누적은 첫 거래부터 센 값 — 오늘 점이 전체 조회와 같다."""
    first = INVESTMENT_START - timedelta(days=400)
    _seed(db, kiwoom["account"].id, first)

    full = client.get("/api/v1/portfolio/pnl-breakdown").json()
    short = client.get("/api/v1/portfolio/pnl-breakdown?days=30").json()
    assert len(short["items"]) == 31
    assert short["since"] == first.isoformat()
    assert short["items"][-1] == full["items"][-1]
    assert short["realized_cum_krw"] == full["realized_cum_krw"]
