"""손익 분해 — 실현손익(누적) · 평가손익 · 총기간 손익 · 총 평가액.

지키는 것:
  1) 실현손익은 **누적**이다. 조회 창을 줄여도 창 시작에서 0 으로 되돌리지 않는다.
  2) 총기간 손익 = 실현손익(누적) + 평가손익. 이 등식이 깨지면 그래프의 두 선 사이
     간격이 실현손익이 아니게 된다.
  3) 모르는 날은 0 이 아니라 None 이다.
  4) 지금 값은 /summary · /realized 와 **정확히** 같다.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core import pnl_breakdown as pb
from app.core.investing import INVESTMENT_START
from app.models import AccountDailyPerformance, Dividend, PortfolioSnapshot, RealizedPnl

from tests.test_portfolio import kiwoom  # noqa: F401 - 픽스처 재사용

D = date.fromisoformat


# ── 순수 함수 ────────────────────────────────────────────────────────────────

def test_realized_accumulates_day_by_day():
    points = pb.build_series(
        D("2026-07-01"), D("2026-07-04"),
        {D("2026-07-01"): Decimal("100"), D("2026-07-03"): Decimal("-30")},
        {}, {},
    )
    assert [p.date for p in points] == [
        D("2026-07-01"), D("2026-07-02"), D("2026-07-03"), D("2026-07-04"),
    ]
    # 매도가 없는 날은 전날과 같다(0 이 아니다).
    assert [p.realized_cum_krw for p in points] == [
        Decimal("100.00"), Decimal("100.00"), Decimal("70.00"), Decimal("70.00"),
    ]


def test_events_before_the_window_seed_the_running_total():
    """창을 줄여도 누적은 투자 시작부터다 — 창 앞의 실현분이 출발값이 된다."""
    points = pb.build_series(
        D("2026-07-10"), D("2026-07-11"),
        {D("2026-06-05"): Decimal("500"), D("2026-07-11"): Decimal("20")},
        {}, {},
    )
    assert [p.realized_cum_krw for p in points] == [Decimal("500.00"), Decimal("520.00")]


def test_total_period_is_realized_plus_unrealized():
    points = pb.build_series(
        D("2026-09-21"), D("2026-09-22"),
        {D("2026-09-21"): Decimal("1000")},
        {D("2026-09-21"): Decimal("2500"), D("2026-09-22"): Decimal("-400")},
        {},
    )
    for p in points:
        assert p.total_period_pnl_krw == p.realized_cum_krw + p.unrealized_krw
    assert points[1].total_period_pnl_krw == Decimal("600.00")


def test_missing_values_stay_null_not_zero():
    """평가손익이 없는 날은 총기간 손익도 None — 실현손익으로 채우지 않는다."""
    points = pb.build_series(
        D("2026-09-20"), D("2026-09-22"),
        {D("2026-09-20"): Decimal("300")},
        {D("2026-09-21"): Decimal("50"), D("2026-09-22"): None},
        {D("2026-09-20"): Decimal("1000000")},
    )
    first, second, third = points
    assert first.unrealized_krw is None and first.total_period_pnl_krw is None
    assert first.realized_cum_krw == Decimal("300.00")
    assert second.total_period_pnl_krw == Decimal("350.00")
    assert third.unrealized_krw is None and third.total_period_pnl_krw is None
    assert first.total_value_krw == Decimal("1000000.00")
    assert second.total_value_krw is None and third.total_value_krw is None


def test_empty_when_window_is_inverted():
    assert pb.build_series(D("2026-09-22"), D("2026-09-21"), {}, {}, {}) == []


# ── API ──────────────────────────────────────────────────────────────────────

def test_breakdown_without_accounts_returns_nulls(client):
    body = client.get("/api/v1/portfolio/pnl-breakdown").json()
    assert body["items"] == []
    for key in ("realized_cum_krw", "unrealized_krw", "total_period_pnl_krw",
                "total_value_krw", "cash_krw"):
        assert body[key] is None


def test_breakdown_current_values_match_summary_and_realized(client, db, kiwoom):  # noqa: F811
    account_id = kiwoom["account"].id
    start = INVESTMENT_START
    db.add_all([
        RealizedPnl(
            id=uuid.uuid4(), account_id=account_id, ticker="NVDA",
            sell_date=start + timedelta(days=3), quantity=Decimal("4"), currency="USD",
            pnl_krw=Decimal("50682"), commission_tax_krw=Decimal("1000"),
        ),
        # 투자 시작 전 매도 — 누적에 넣지 않는다(/realized 와 같은 범위).
        RealizedPnl(
            id=uuid.uuid4(), account_id=account_id, ticker="TSL",
            sell_date=start - timedelta(days=30), quantity=Decimal("1"), currency="USD",
            pnl_krw=Decimal("99999"),
        ),
        Dividend(
            id=uuid.uuid4(), account_id=account_id, ticker="SCHD",
            pay_date=start + timedelta(days=5), amount_krw=Decimal("31107"), currency="KRW",
        ),
        AccountDailyPerformance(
            id=uuid.uuid4(), account_id=account_id, base_date=start + timedelta(days=5),
            deposit_assets_krw=Decimal("2900000"),
        ),
        # 그날(한국 시각) 마지막 스냅샷의 평가손익만 쓴다.
        PortfolioSnapshot(
            id=uuid.uuid4(), account_id=account_id,
            snapshot_at=datetime.combine(start + timedelta(days=5), datetime.min.time(),
                                         tzinfo=timezone.utc) + timedelta(hours=1),
            total_unrealized_pnl_krw=Decimal("111"), total_assets_krw=Decimal("1"),
        ),
        PortfolioSnapshot(
            id=uuid.uuid4(), account_id=account_id,
            snapshot_at=datetime.combine(start + timedelta(days=5), datetime.min.time(),
                                         tzinfo=timezone.utc) + timedelta(hours=10),
            total_unrealized_pnl_krw=Decimal("222"), total_assets_krw=Decimal("2"),
        ),
    ])
    db.commit()

    body = client.get("/api/v1/portfolio/pnl-breakdown").json()
    summary = client.get("/api/v1/portfolio/summary").json()
    realized = client.get("/api/v1/portfolio/realized?days=3650").json()

    assert body["realized_cum_krw"] == realized["breakdown"]["net_krw"]
    assert Decimal(body["realized_cum_krw"]) == Decimal("81789")  # 50,682 + 31,107
    assert body["unrealized_krw"] == summary["unrealized_pnl_krw"]
    assert body["total_value_krw"] == summary["total_assets_krw"]
    assert body["cash_krw"] == summary["cash_krw"]
    assert Decimal(body["total_period_pnl_krw"]) == (
        Decimal(body["realized_cum_krw"]) + Decimal(body["unrealized_krw"])
    )

    items = body["items"]
    assert items[0]["date"] == start.isoformat()
    # 오늘 점은 지금 값과 같다 — 그래프 끝점이 타일과 맞아야 한다.
    last = items[-1]
    assert last["realized_cum_krw"] == body["realized_cum_krw"]
    assert last["unrealized_krw"] == body["unrealized_krw"]
    assert last["total_value_krw"] == body["total_value_krw"]

    by_date = {i["date"]: i for i in items}
    snap_day = by_date[(start + timedelta(days=5)).isoformat()]
    assert Decimal(snap_day["unrealized_krw"]) == Decimal("222")
    # 일별 성과가 있으면 스냅샷보다 그쪽(예탁자산)이 총 평가액이다.
    assert Decimal(snap_day["total_value_krw"]) == Decimal("2900000")
    assert Decimal(snap_day["total_period_pnl_krw"]) == Decimal("81789") + Decimal("222")
    # 스냅샷이 없는 날은 null — 0 이 아니다.
    quiet = by_date[(start + timedelta(days=4)).isoformat()]
    assert quiet["unrealized_krw"] is None
    assert quiet["total_period_pnl_krw"] is None
    assert quiet["total_value_krw"] is None
    assert Decimal(quiet["realized_cum_krw"]) == Decimal("50682")
    assert body["unrealized_since"] == (start + timedelta(days=5)).isoformat()
