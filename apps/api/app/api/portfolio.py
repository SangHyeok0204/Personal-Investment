"""개인 계좌 포트폴리오 — 자산 현황 · 보유 종목 · 계좌 · 자산 추이.

읽기 전용이다. 증권사 API 를 **이 라우터가 직접 때리지 않는다** — collector/worker 가
주기적으로 수집해 DB(alembic 0002 테이블)에 적재하고, 대시보드는 그 결과만 읽는다.
화면이 증권사를 직접 호출하면 새로고침할 때마다 유량제한에 걸리고, 장 마감 후에는
아무것도 못 그린다.

⚠️계좌가 아직 하나도 없을 때 0 을 내보내지 않는다. 합계는 null 이고 `connected`
  플래그가 false 다 — 프런트는 "미연동"을 띄운다. 0원과 미연동은 다른 상태다.

합계는 **DB 에 적재된 KRW 환산값**을 더한다(market_value_krw 등). 여기서 환율을 다시
곱하지 않는다 — 수집 시점 환율과 조회 시점 환율이 다르면 종목별 수치와 합계가
어긋나고, 그 차이는 화면에서 "합이 안 맞는다"로 보인다.
"""
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, delete, func, literal_column, select
from sqlalchemy.orm import Session

from app.core import performance_analytics as pa
from app.core import position_timeline as pt
from app.core.market_history import fetch_history
from app.core.etf_exposure import ETF_EXPOSURE
from app.core import quote_cache
from app.core import investing as inv
from app.core import naming
from app.core import portfolio_character as pc
from app.core import rebalance as rb
from app.core import fee_reserve as fr
from app.core import residual as rsd
from app.core import return_bridge

# 시세 소스와 같은 자리에 산다 — apps/worker 를 경로에 올려 쓴다.
_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))
from prices import filings as filings_source  # noqa: E402
from prices import news as news_source  # noqa: E402
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    RebalanceTarget,
    Account,
    AccountBalance,
    Asset,
    Broker,
    BrokerageConnection,
    CurrentPosition,
    Order,
    PortfolioSnapshot,
    Trade,
    AccountDailyPerformance,
    RealizedPnl,
    Dividend,
)
from app.schemas import (
    AccountListOut,
    CashByCurrencyOut,
    CashflowEventOut,
    CashflowMonthOut,
    BenchmarkOut,
    BenchmarkPeriodOut,
    BenchmarkPointOut,
    CashflowOut,
    CostByMonthOut,
    CostBySideOut,
    CostByTickerOut,
    FxExposureOut,
    FxPositionOut,
    FxShockOut,
    ContributionOut,
    DrawdownPointOut,
    MonthlyReturnOut,
    FlowShiftOut,
    InclusionEventOut,
    InclusionHoldingOut,
    InclusionOut,
    InclusionWeightPointOut,
    LiveQuoteOut,
    LiveQuotesOut,
    FilingOut,
    FilingTickerOut,
    FilingsOut,
    NewsArticleOut,
    LeveragePositionOut,
    PortfolioCharacterOut,
    RealizedBreakdownOut,
    RebalanceLineOut,
    RebalanceOut,
    RebalanceTargetIn,
    NewsOut,
    NewsTickerOut,
    ReportBenchmarkOut,
    ReportOut,
    ReportPeriodOut,
    ResidualBreakdownOut,
    ReportPositionChangeOut,
    ReportRealizedOut,
    MonthlyCashflowOut,
    MonthlyCashflowRowOut,
    TaxOut,
    TaxSaleOut,
    TaxYearOut,
    OrderListOut,
    OrderOut,
    TradingCostOut,
    PerformanceAnalyticsOut,
    PeriodReturnOut,
    RiskMetricsOut,
    AllocationOut,
    AllocationSliceOut,
    AccountOut,
    ConnectionOut,
    HoldingListOut,
    HoldingOut,
    HoldingSectorPatch,
    PortfolioHistoryOut,
    PortfolioSummaryOut,
    SnapshotPointOut,
    TradeListOut,
    TradeOut,
    TradeStatsOut,
    DailyPerformanceOut,
    PerformanceSeriesOut,
    ReturnBridgeOut,
    RealizedPnlListOut,
    RealizedPnlOut,
    DividendListOut,
    DividendOut,
    DividendMonthOut,
    DividendByTickerOut,
)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


# 금액은 소수 2자리(원 단위 이하 절사 없이 반올림), 비율은 6자리로 고정한다.
# 고정하지 않으면 Decimal 곱셈이 자릿수를 그대로 물고 나가 "0.14644818557147593404…"
# 같은 값이 그대로 JSON 에 실린다.
_MONEY = Decimal("0.01")
_RATIO = Decimal("0.000001")


def _sum(values: list[Decimal | None]) -> Decimal | None:
    """None 을 0 으로 치환하지 않는 합. 전부 None 이면 결과도 None 이다.

    수집이 안 된 항목을 0 으로 세면 "예수금 0원"처럼 **틀린 사실**이 화면에 뜬다.
    하나라도 값이 있으면 있는 것만 더한다(부분 수집 상태를 그대로 반영).
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, Decimal("0")).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _active_account_ids(db: Session, account_id: uuid.UUID | None) -> list[uuid.UUID]:
    stmt = select(Account.id).where(Account.is_active.is_(True))
    if account_id is not None:
        stmt = stmt.where(Account.id == account_id)
    return list(db.execute(stmt).scalars().all())


@router.get("/accounts", response_model=AccountListOut)
def list_accounts(db: Session = Depends(get_db)) -> AccountListOut:
    """상단 바 계좌 선택기의 원천. 비활성 계좌도 목록에는 실어 보낸다."""
    rows = db.execute(
        select(Account, Broker)
        .join(Broker, Broker.id == Account.broker_id)
        .order_by(Broker.name, Account.account_name)
    ).all()

    items = [
        AccountOut(
            id=account.id,
            broker_code=broker.code,
            broker_name=broker.name,
            account_name=account.account_name,
            account_number_masked=account.account_number_masked,
            account_type=account.account_type,
            base_currency=account.base_currency,
            is_active=account.is_active,
            last_synced_at=account.last_synced_at,
        )
        for account, broker in rows
    ]
    return AccountListOut(items=items, connected=bool(items))


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db)) -> list[ConnectionOut]:
    """연동 화면의 상태 칩 — 증권사별 연결 상태와 마지막 오류."""
    rows = db.execute(
        select(BrokerageConnection, Broker)
        .join(Broker, Broker.id == BrokerageConnection.broker_id)
        .order_by(Broker.name, BrokerageConnection.connection_name)
    ).all()

    return [
        ConnectionOut(
            id=conn.id,
            broker_code=broker.code,
            broker_name=broker.name,
            connection_name=conn.connection_name,
            environment=conn.environment,
            status=conn.status,
            last_connected_at=conn.last_connected_at,
            last_synced_at=conn.last_synced_at,
            last_error=conn.last_error,
        )
        for conn, broker in rows
    ]


@router.get("/summary", response_model=PortfolioSummaryOut)
def get_summary(
    account_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PortfolioSummaryOut:
    """자산 현황 상단 4칸. account_id 를 주면 그 계좌만, 없으면 전체 합산."""
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return PortfolioSummaryOut(
            as_of=None,
            account_count=0,
            position_count=0,
            total_assets_krw=None,
            securities_value_krw=None,
            cash_krw=None,
            available_cash_krw=None,
            purchase_amount_krw=None,
            unrealized_pnl_krw=None,
            unrealized_return=None,
            fee_reserve_krw=None,
            fee_reserve_modelled_krw=None,
            cash_by_currency=[],
        )

    # 종목 통화가 필요하다(매입원가는 KRW 환산 컬럼이 없어 여기서 환산해야 한다).
    rows = db.execute(
        select(CurrentPosition, Asset.currency)
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .where(CurrentPosition.account_id.in_(account_ids))
    ).all()
    positions = [position for position, _ in rows]
    balances = db.execute(
        select(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
    ).scalars().all()

    securities = _sum([p.market_value_krw for p in positions])
    # 매입원가: 원화 종목은 그대로, 외화 종목은 **수집 시점** 환율로 환산한다.
    # 환율이 없는 외화 종목은 합계에서 빠진다 — 0 으로 세면 수익률이 부풀려진다.
    purchase = _sum([_purchase_krw(p, currency) for p, currency in rows])
    pnl = _sum([p.unrealized_pnl_krw for p in positions])

    # 예수금: KRW 행은 그대로, 외화 행은 수집 시점 환율로 환산.
    cash = _sum([_cash_krw(b) for b in balances])
    available = _sum([_available_krw(b) for b in balances])

    total = _sum([securities, cash])
    ret = (
        (pnl / purchase).quantize(_RATIO, rounding=ROUND_HALF_UP)
        if (pnl is not None and purchase)
        else None
    )

    as_of_candidates = [p.as_of for p in positions] + [b.as_of for b in balances]

    return PortfolioSummaryOut(
        as_of=max(as_of_candidates) if as_of_candidates else None,
        account_count=len(account_ids),
        position_count=len(positions),
        total_assets_krw=total,
        securities_value_krw=securities,
        cash_krw=cash,
        available_cash_krw=available,
        purchase_amount_krw=purchase,
        unrealized_pnl_krw=pnl,
        unrealized_return=ret,
        fee_reserve_krw=fr.reserve_krw(securities, purchase, pnl),
        fee_reserve_modelled_krw=fr.modelled_krw(securities, purchase),
        cash_by_currency=[
            CashByCurrencyOut(
                currency=b.currency,
                cash_balance=b.cash_balance,
                available_cash=b.available_cash,
                krw_value=_cash_krw(b),
            )
            for b in sorted(balances, key=lambda x: (x.currency != "KRW", x.currency))
            if b.cash_balance
        ],
    )


def _cash_krw(balance: AccountBalance) -> Decimal | None:
    if balance.currency == "KRW":
        return balance.cash_balance
    if balance.exchange_rate is None:
        return None
    return balance.cash_balance * balance.exchange_rate


def _available_krw(balance: AccountBalance) -> Decimal | None:
    if balance.available_cash is None:
        return None
    if balance.currency == "KRW":
        return balance.available_cash
    if balance.exchange_rate is None:
        return None
    return balance.available_cash * balance.exchange_rate


def _purchase_krw(position: CurrentPosition, currency: str) -> Decimal | None:
    """매입원가의 KRW 환산. 환산할 수 없으면 None (0 이 아니다)."""
    if position.purchase_amount_local is None:
        return None
    if currency == "KRW":
        return position.purchase_amount_local
    if position.exchange_rate is None:
        return None
    return position.purchase_amount_local * position.exchange_rate


@router.get("/holdings", response_model=HoldingListOut)
def list_holdings(
    account_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HoldingListOut:
    """보유 종목 — 평가금액(KRW) 내림차순. 값이 없는 종목은 뒤로 민다."""
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return HoldingListOut(items=[], total_market_value_krw=None, as_of=None)

    rows = db.execute(
        select(CurrentPosition, Asset, Account, Broker)
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .join(Account, Account.id == CurrentPosition.account_id)
        .join(Broker, Broker.id == Account.broker_id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .order_by(CurrentPosition.market_value_krw.desc().nullslast())
    ).all()

    items = [
        HoldingOut(
            account_id=account.id,
            account_name=account.account_name,
            broker_code=broker.code,
            asset_id=asset.id,
            ticker=asset.ticker,
            name=asset.name,
            market=asset.market,
            country=asset.country,
            currency=asset.currency,
            asset_type=asset.asset_type,
            sector=asset.sector,
            industry=asset.industry,
            sector_source=asset.sector_source,
            tech_l1=asset.tech_l1,
            tech_l2=asset.tech_l2,
            tech_l3=asset.tech_l3,
            quantity=position.quantity,
            average_purchase_price=position.average_purchase_price,
            current_price=position.current_price,
            purchase_amount_local=position.purchase_amount_local,
            market_value_local=position.market_value_local,
            market_value_krw=position.market_value_krw,
            unrealized_pnl_local=position.unrealized_pnl_local,
            unrealized_pnl_krw=position.unrealized_pnl_krw,
            unrealized_return=position.unrealized_return,
            exchange_rate=position.exchange_rate,
            as_of=position.as_of,
        )
        for position, asset, account, broker in rows
    ]

    return HoldingListOut(
        items=items,
        total_market_value_krw=_sum([i.market_value_krw for i in items]),
        as_of=max((i.as_of for i in items), default=None),
    )


@router.get("/history", response_model=PortfolioHistoryOut)
def get_history(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(90, ge=1, le=1825),
    db: Session = Depends(get_db),
) -> PortfolioHistoryOut:
    """자산 추이 — 스냅샷 시계열.

    전체 합산일 때는 **같은 시점의 계좌별 스냅샷을 더해** 한 점으로 만든다.
    계좌마다 동기화 시각이 조금씩 달라 그대로 이으면 톱니가 생기므로, 날짜 단위로
    묶고 각 날짜의 계좌별 **마지막** 스냅샷만 쓴다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return PortfolioHistoryOut(items=[], days=days)

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 계좌×날짜별 최신 스냅샷 하나만 고른다.
    day = func.date_trunc("day", PortfolioSnapshot.snapshot_at).label("day")
    latest = (
        select(
            PortfolioSnapshot.account_id.label("account_id"),
            day,
            func.max(PortfolioSnapshot.snapshot_at).label("snapshot_at"),
        )
        .where(
            PortfolioSnapshot.account_id.in_(account_ids),
            PortfolioSnapshot.snapshot_at >= since,
        )
        .group_by(PortfolioSnapshot.account_id, day)
        .subquery()
    )

    rows = db.execute(
        select(
            latest.c.day,
            func.sum(PortfolioSnapshot.total_assets_krw),
            func.sum(PortfolioSnapshot.securities_value_krw),
            func.sum(PortfolioSnapshot.cash_value_krw),
            func.sum(PortfolioSnapshot.total_unrealized_pnl_krw),
        )
        .join(
            latest,
            (PortfolioSnapshot.account_id == latest.c.account_id)
            & (PortfolioSnapshot.snapshot_at == latest.c.snapshot_at),
        )
        .group_by(latest.c.day)
        .order_by(latest.c.day)
    ).all()

    return PortfolioHistoryOut(
        items=[
            SnapshotPointOut(
                snapshot_at=d,
                total_assets_krw=total,
                securities_value_krw=securities,
                cash_value_krw=cash,
                total_unrealized_pnl_krw=pnl,
            )
            for d, total, securities, cash, pnl in rows
        ],
        days=days,
    )


# ── 비중 ──────────────────────────────────────────────────────────────────────
# 비중 계산을 서버로 올린 이유(2026-09-21): 화면마다 따로 계산하면 반올림 처리가
# 갈려 같은 숫자가 화면마다 다르게 보인다. 분모(총 평가금액)도 한 곳에서 정한다.

def _exposure_expression():
    """ETF 를 대표 노출로 치환한 L1 축.

    개별주는 tech_l1 을 그대로 쓰고, ETF 만 `database/seeds/etf_exposure.py` 의
    라벨로 바꾼다. **한 ETF 는 언제나 한 조각**이다 — 구성종목 비중으로 쪼개는
    투과(look-through) 배분이 아니다(사용자가 원하지 않는다고 밝혔다).

    표에 없는 ETF 는 tech_l1 그대로("ETF")가 되어 화면에 남는다. 추측해서
    아무 섹터에나 넣지 않는다 — 모르는 건 모른다고 보여야 표를 채우게 된다.
    """
    return case(
        *[(Asset.ticker == ticker, label) for ticker, (label, _) in ETF_EXPOSURE.items()],
        else_=Asset.tech_l1,
    )


_ALLOCATION_DIMENSIONS = {
    # AI/Tech 밸류체인 3단계 — 사용자가 준 분류표(alembic 0010).
    # 전통 섹터(sector)와 **다른 축**이라 같이 제공한다.
    "tech_l1": (Asset.tech_l1, "미분류"),
    # ETF 를 대표 노출로 치환한 축. tech_l1 은 ETF 가 전부 "ETF" 한 덩어리라
    # (평가금액의 61%) 섹터 비중으로 읽히지 않는다.
    "exposure": (_exposure_expression(), "미분류"),
    "tech_l2": (Asset.tech_l2, "미분류"),
    "tech_l3": (Asset.tech_l3, "미분류"),
    "sector": (Asset.sector, "미분류"),
    "industry": (Asset.industry, "미분류"),
    "asset_type": (Asset.asset_type, "미분류"),
    "country": (Asset.country, "미상"),
    "currency": (Asset.currency, "미상"),
    "market": (Asset.market, "미상"),
}

_COUNTRY_LABELS = {"KR": "한국", "US": "미국", "JP": "일본", "CN": "중국"}


@router.get("/allocation", response_model=AllocationOut)
def get_allocation(
    dimension: str = Query("sector"),
    account_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AllocationOut:
    """평가금액(KRW) 기준 비중. dimension 으로 축을 고른다.

    ⚠️분류가 안 된 종목을 **빼지 않는다**. key=null 조각으로 같이 내려보내고
      unclassified_market_value_krw 로 규모를 따로 알린다. 미분류를 숨기면
      비중 합이 100% 로 보여서 분류가 끝난 것처럼 착각하게 된다.
    """
    if dimension not in _ALLOCATION_DIMENSIONS:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "Unknown allocation dimension.",
            {"allowed": sorted(_ALLOCATION_DIMENSIONS)},
        )

    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return AllocationOut(
            dimension=dimension,
            items=[],
            total_market_value_krw=None,
            unclassified_market_value_krw=None,
            as_of=None,
        )

    column, fallback_label = _ALLOCATION_DIMENSIONS[dimension]
    rows = db.execute(
        select(
            column,
            func.sum(CurrentPosition.market_value_krw),
            func.count(),
            func.max(CurrentPosition.as_of),
        )
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .where(
            CurrentPosition.account_id.in_(account_ids),
            CurrentPosition.market_value_krw.isnot(None),
        )
        .group_by(column)
    ).all()

    # ★2026-09-22 사용자 지정: **자산에 예수금을 포함한다.** 분모가 총자산이
    #   되므로 예수금도 한 조각으로 넣는다 — 분모에만 더하고 조각에서 빼면
    #   비중 합이 100% 가 안 되고, 사용자는 그걸 버그로 읽는다.
    cash = None
    cash_by_currency: dict[str, Decimal] = {}
    if inv.CASH_IN_ASSETS:
        balances = db.execute(
            select(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
        ).scalars().all()
        cash = _sum([_cash_krw(b) for b in balances])
        for b in balances:
            value = _cash_krw(b)
            if value:
                cash_by_currency[b.currency] = (
                    cash_by_currency.get(b.currency, Decimal("0")) + value
                )

    total = _sum([value for _, value, _, _ in rows])
    if total is not None and cash:
        total = total + cash
    if not total:
        return AllocationOut(
            dimension=dimension,
            items=[],
            total_market_value_krw=None,
            unclassified_market_value_krw=None,
            as_of=None,
        )

    items = []
    unclassified = None
    for key, value, count, as_of in rows:
        amount = (value or Decimal("0")).quantize(_MONEY, rounding=ROUND_HALF_UP)
        if key is None:
            unclassified = amount
        label = fallback_label if key is None else _COUNTRY_LABELS.get(key, key) if dimension == "country" else key
        items.append(
            AllocationSliceOut(
                key=key,
                label=label,
                market_value_krw=amount,
                weight=(amount / total).quantize(_RATIO, rounding=ROUND_HALF_UP),
                position_count=count,
            )
        )

    if cash:
        # ⚠️**통화 축에서는 예수금을 통화에 합친다.** 따로 떼어 놓으면 그 축이
        #   재려는 것을 못 재게 된다 — 실측으로 예수금 전액이 USD($982.92)인데
        #   화면은 "USD 96.50% · 예수금 3.50%" 라고 적고 있었다. 사실은 USD 100%
        #   다. 통화 비중을 보는 사람은 "내 돈의 몇 %가 달러인가"를 묻는 것이고,
        #   달러 예수금은 그 답에 들어가야 한다.
        #   다른 축(섹터·자산군·국가)에서는 합치지 않는다 — 현금에 섹터가 없고,
        #   USD 예수금이 곧 '미국 자산'이라는 것도 우리가 정할 일이 아니다.
        if dimension == "currency":
            by_key = {i.key: i for i in items}
            for currency, value in cash_by_currency.items():
                amount = value.quantize(_MONEY, rounding=ROUND_HALF_UP)
                existing = by_key.get(currency)
                if existing is None:
                    items.append(
                        AllocationSliceOut(
                            key=currency,
                            label=currency,
                            market_value_krw=amount,
                            weight=(amount / total).quantize(
                                _RATIO, rounding=ROUND_HALF_UP
                            ),
                            position_count=1,
                        )
                    )
                    continue
                merged = existing.market_value_krw + amount
                items[items.index(existing)] = AllocationSliceOut(
                    key=existing.key,
                    label=existing.label,
                    market_value_krw=merged,
                    weight=(merged / total).quantize(_RATIO, rounding=ROUND_HALF_UP),
                    # 예수금도 한 항목으로 센다 — 따로 낼 때 1 로 세던 것과 같은 규칙.
                    position_count=existing.position_count + 1,
                )
        else:
            amount = cash.quantize(_MONEY, rounding=ROUND_HALF_UP)
            # 통화를 적어 둔다. 국가 축에서 "예수금 3.5%" 만 보이면 그 돈이
            # 원화인지 달러인지 알 수 없다.
            currencies = sorted(cash_by_currency)
            label = (
                f"예수금 ({currencies[0]})" if len(currencies) == 1 else "예수금"
            )
            items.append(
                AllocationSliceOut(
                    key=CASH_TICKER,
                    label=label,
                    market_value_krw=amount,
                    weight=(amount / total).quantize(_RATIO, rounding=ROUND_HALF_UP),
                    # 현금은 '종목 수'가 없다. 0 으로 두면 "0종목"이 찍히므로 1 로 센다.
                    position_count=1,
                )
            )

    # 큰 것부터. 미분류는 크기와 무관하게 맨 뒤로 민다 — 목록의 의미가 다르다.
    items.sort(key=lambda i: (i.key is None, -i.market_value_krw))

    return AllocationOut(
        dimension=dimension,
        items=items,
        total_market_value_krw=total,
        unclassified_market_value_krw=unclassified,
        as_of=max((r[3] for r in rows if r[3]), default=None),
    )


@router.patch("/assets/{asset_id}/sector", response_model=HoldingSectorPatch)
def set_asset_sector(
    asset_id: uuid.UUID,
    body: HoldingSectorPatch,
    db: Session = Depends(get_db),
) -> HoldingSectorPatch:
    """섹터를 수기로 지정한다. 화면에서 고친 값은 MANUAL 로 표시돼 자동 분류가 덮지 않는다."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise AppError(404, "NOT_FOUND", "Asset not found.")

    asset.sector = (body.sector or "").strip() or None
    asset.industry = (body.industry or "").strip() or None
    asset.sector_source = "MANUAL" if asset.sector else None
    asset.classified_at = datetime.now(timezone.utc) if asset.sector else None
    db.commit()
    return HoldingSectorPatch(sector=asset.sector, industry=asset.industry)


# ── 매매(체결) 내역 ──────────────────────────────────────────────────────────

_SIDES = {"BUY", "SELL"}


@router.get("/trades", response_model=TradeListOut)
def list_trades(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    side: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> TradeListOut:
    """체결 내역 — 최근순.

    ⚠️합계는 **통화별로** 나눠 내보낸다. USD 거래와 KRW 거래를 한 숫자로 더하면
      의미 없는 값이 된다. 환산해서 더하려면 거래 시점 환율이 있어야 하는데,
      증권사가 해외 거래의 원화 금액을 0 으로 주므로 그 환율이 없다.
    """
    if side is not None and side.upper() not in _SIDES:
        raise AppError(
            400, "VALIDATION_ERROR", "Unknown side.", {"allowed": sorted(_SIDES)}
        )

    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return TradeListOut(
            items=[], total=0, stats=[], first_trade_date=None, last_trade_date=None
        )

    since = inv.since(days)
    conditions = [Trade.account_id.in_(account_ids), Trade.trade_date >= since]
    if side is not None:
        conditions.append(Trade.side == side.upper())
    if ticker:
        conditions.append(Trade.ticker == ticker.upper())

    rows = db.execute(
        select(Trade, Account.account_name, Asset.sector)
        .join(Account, Account.id == Trade.account_id)
        .outerjoin(Asset, Asset.id == Trade.asset_id)
        .where(*conditions)
        .order_by(Trade.trade_date.desc(), Trade.trade_no.desc())
        .limit(limit)
    ).all()

    total = db.execute(
        select(func.count()).select_from(Trade).where(*conditions)
    ).scalar_one()

    stats_rows = db.execute(
        select(
            Trade.currency,
            Trade.side,
            func.count(),
            func.sum(Trade.amount_local),
            func.sum(Trade.commission_local),
            func.sum(Trade.tax_local),
        )
        .where(*conditions)
        .group_by(Trade.currency, Trade.side)
    ).all()

    by_currency: dict[str, dict] = {}
    for currency, trade_side, count, amount, commission, tax in stats_rows:
        entry = by_currency.setdefault(
            currency,
            {
                "buy_count": 0, "sell_count": 0,
                "buy_amount": Decimal("0"), "sell_amount": Decimal("0"),
                "commission": Decimal("0"), "tax": Decimal("0"),
            },
        )
        if trade_side == "BUY":
            entry["buy_count"] = count
            entry["buy_amount"] = amount or Decimal("0")
        else:
            entry["sell_count"] = count
            entry["sell_amount"] = amount or Decimal("0")
        entry["commission"] += commission or Decimal("0")
        entry["tax"] += tax or Decimal("0")

    span = db.execute(
        select(func.min(Trade.trade_date), func.max(Trade.trade_date)).where(*conditions)
    ).one()

    return TradeListOut(
        items=[
            TradeOut(
                id=trade.id,
                account_id=trade.account_id,
                account_name=account_name,
                trade_date=trade.trade_date,
                trade_no=trade.trade_no,
                side=trade.side,
                ticker=trade.ticker,
                asset_name=trade.asset_name,
                sector=sector,
                currency=trade.currency,
                quantity=trade.quantity,
                price=trade.price,
                amount_local=trade.amount_local,
                settlement_amount_local=trade.settlement_amount_local,
                commission_local=trade.commission_local,
                tax_local=trade.tax_local,
                exchange=trade.exchange,
                channel=trade.channel,
                processed_at=trade.processed_at,
            )
            for trade, account_name, sector in rows
        ],
        total=total,
        stats=[
            TradeStatsOut(currency=currency, **values)
            for currency, values in sorted(by_currency.items())
        ],
        first_trade_date=span[0],
        last_trade_date=span[1],
    )


# ── 일별 성과 (자산 추이 · 수익률) ───────────────────────────────────────────

def _empty_bridge() -> ReturnBridgeOut:
    """계좌가 없거나 데이터가 없을 때. 0 이 아니라 **None** 이다 — '증감 없음'과
    '잴 것이 없음'은 다른 말이다."""
    return ReturnBridgeOut(
        price_pnl_krw=None, asset_change_krw=None, fx_effect_krw=None,
        twr=None, twr_days=0, unmeasured_days=0, missing_pnl_days=0,
    )



@router.get("/performance", response_model=PerformanceSeriesOut)
def get_performance(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> PerformanceSeriesOut:
    """계좌 일별 성과 시계열 — 증권사가 들고 있던 과거를 그대로 읽는다.

    계좌가 여럿이면 같은 날짜의 값을 더한다(예탁자산·주식평가는 합산 가능한 값이다).

    ⚠️기간 손익을 (끝 - 시작)으로 계산하지 않는다. 그 사이의 입금이 그대로 '수익'
      으로 보이기 때문이다. 순입금을 빼서 gain_krw 로 내보낸다.

    ⚠️그런데 gain_krw 는 **원화 기준**이다. 증권사 일별 손익(pnl_krw)은 **주가
      기준**이라, 환율이 크게 움직인 구간에서는 둘이 부호까지 갈린다(실측:
      −₩722,749 vs +₩2,469,456). 예전에는 이 둘을 한 화면에 그냥 나란히 놓아
      서로 반대되는 말을 하게 만들었다. 이제 `bridge` 가 사이를 잇고 TWR 도 낸다
      — `app.core.return_bridge` 참고.

    ⚠️`cumulative_pnl_krw` 로 기간 손익을 구하지 말 것. 조회 창 경계에서 그날
      손익으로 초기화된다(실측: 2025-09-18, 2026-09-14).
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return PerformanceSeriesOut(
            items=[], first_date=None, last_date=None,
            start_assets_krw=None, end_assets_krw=None,
            net_deposit_krw=None, gain_krw=None,
            bridge=_empty_bridge(),
        )

    since = inv.since(days)
    rows = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_assets_krw),
            func.sum(AccountDailyPerformance.stock_value_krw),
            func.sum(AccountDailyPerformance.cumulative_pnl_krw),
            func.sum(AccountDailyPerformance.pnl_krw),
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            AccountDailyPerformance.base_date >= since,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()

    items = [
        DailyPerformanceOut(
            base_date=base_date,
            deposit_assets_krw=assets,
            stock_value_krw=stock,
            cumulative_pnl_krw=cumulative,
            pnl_krw=pnl,
            deposit_krw=deposit,
            withdrawal_krw=withdrawal,
        )
        for base_date, assets, stock, cumulative, pnl, deposit, withdrawal in rows
    ]
    if not items:
        return PerformanceSeriesOut(
            items=[], first_date=None, last_date=None,
            start_assets_krw=None, end_assets_krw=None,
            net_deposit_krw=None, gain_krw=None,
            bridge=_empty_bridge(),
        )

    start_assets = items[0].deposit_assets_krw
    end_assets = items[-1].deposit_assets_krw
    # 첫날의 입출금은 시작 잔고에 이미 반영돼 있다 — 이중 계산을 피해 제외한다.
    net_deposit = _sum(
        [(i.deposit_krw or Decimal("0")) - (i.withdrawal_krw or Decimal("0")) for i in items[1:]]
    )
    gain = (
        (end_assets - start_assets - (net_deposit or Decimal("0")))
        if (start_assets is not None and end_assets is not None)
        else None
    )

    bridge = return_bridge.build(
        [
            return_bridge.Day(
                base_date=i.base_date,
                assets_krw=i.deposit_assets_krw,
                pnl_krw=i.pnl_krw,
                deposit_krw=i.deposit_krw,
                withdrawal_krw=i.withdrawal_krw,
            )
            for i in items
        ]
    )

    return PerformanceSeriesOut(
        items=items,
        first_date=items[0].base_date,
        last_date=items[-1].base_date,
        start_assets_krw=start_assets,
        end_assets_krw=end_assets,
        net_deposit_krw=net_deposit,
        gain_krw=gain.quantize(_MONEY, rounding=ROUND_HALF_UP) if gain is not None else None,
        bridge=ReturnBridgeOut(
            price_pnl_krw=bridge.price_pnl_krw,
            asset_change_krw=bridge.asset_change_krw,
            fx_effect_krw=bridge.fx_effect_krw,
            twr=bridge.twr,
            twr_days=bridge.twr_days,
            unmeasured_days=bridge.unmeasured_days,
            missing_pnl_days=bridge.missing_pnl_days,
        ),
    )


# ── 실현손익 ────────────────────────────────────────────────────────────────

@router.get("/realized", response_model=RealizedPnlListOut)
def list_realized_pnl(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> RealizedPnlListOut:
    """실현손익 — 매도 확정분. 최근순.

    ⚠️주가 손익(pnl_krw)과 환 손익(fx_pnl_krw)을 **분리해서** 내보낸다. 합치면
      "종목이 올라서 번 건지 환율로 번 건지" 구분이 사라진다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return RealizedPnlListOut(
            items=[], total=0, pnl_krw=None, fx_pnl_krw=None,
            win_count=0, loss_count=0,
            first_sell_date=None, last_sell_date=None,
            breakdown=None, trades=[], trade_stats=None,
        )

    since = inv.since(days)
    conditions = [RealizedPnl.account_id.in_(account_ids), RealizedPnl.sell_date >= since]

    rows = db.execute(
        select(RealizedPnl, Asset.sector)
        .outerjoin(Asset, Asset.id == RealizedPnl.asset_id)
        .where(*conditions)
        .order_by(RealizedPnl.sell_date.desc(), RealizedPnl.ticker)
    ).all()

    items = [
        RealizedPnlOut(
            id=row.id,
            sell_date=row.sell_date,
            ticker=row.ticker,
            asset_name=row.asset_name,
            sector=sector,
            currency=row.currency,
            quantity=row.quantity,
            avg_buy_price=row.avg_buy_price,
            avg_sell_price=row.avg_sell_price,
            buy_amount_local=row.buy_amount_local,
            sell_amount_local=row.sell_amount_local,
            commission_tax_local=row.commission_tax_local,
            pnl_local=row.pnl_local,
            pnl_krw=row.pnl_krw,
            pnl_rate=row.pnl_rate,
            buy_exchange_rate=row.buy_exchange_rate,
            sell_exchange_rate=row.sell_exchange_rate,
            fx_pnl_krw=row.fx_pnl_krw,
        )
        for row, sector in rows
    ]

    # 승패는 **주가 손익** 기준이다. 환차를 섞으면 매매 판단의 성적이 흐려진다.
    wins = sum(1 for i in items if (i.pnl_krw or 0) > 0)
    losses = sum(1 for i in items if (i.pnl_krw or 0) < 0)

    # ── 같은 기간의 체결 내역 ────────────────────────────────────────────
    # ★체결과 실현손익을 **한 화면**에서 본다. 따로 두면 "무엇을 팔았나"와
    #   "그래서 얼마 벌었나"가 갈려 매번 두 화면을 오가야 했다.
    trade_rows = db.execute(
        select(Trade)
        .where(Trade.account_id.in_(account_ids), Trade.trade_date >= since)
        .order_by(Trade.trade_date.desc(), Trade.ticker)
    ).scalars().all()
    trades_out = [
        TradeOut(
            id=t.id, account_id=t.account_id, account_name=None,
            trade_date=t.trade_date, trade_no=t.trade_no, side=t.side,
            ticker=t.ticker, asset_name=t.asset_name, sector=None,
            currency=t.currency, quantity=t.quantity, price=t.price,
            amount_local=t.amount_local,
            settlement_amount_local=t.settlement_amount_local,
            commission_local=t.commission_local, tax_local=t.tax_local,
            exchange=t.exchange, channel=t.channel, processed_at=t.processed_at,
        )
        for t in trade_rows
    ]
    zero = Decimal("0")
    stats = (
        TradeStatsOut(
            # ⚠️통화가 섞이면 합산하지 않는다. 현재 체결은 전부 USD 다.
            currency=trade_rows[0].currency,
            buy_count=sum(1 for t in trade_rows if t.side == "BUY"),
            sell_count=sum(1 for t in trade_rows if t.side == "SELL"),
            buy_amount=sum((t.amount_local or zero) for t in trade_rows if t.side == "BUY"),
            sell_amount=sum((t.amount_local or zero) for t in trade_rows if t.side == "SELL"),
            commission=sum((t.commission_local or zero) for t in trade_rows),
            tax=sum((t.tax_local or zero) for t in trade_rows),
        )
        if trade_rows and len({t.currency for t in trade_rows}) == 1
        else None
    )

    # ── 무엇으로 벌었나 ──────────────────────────────────────────────────
    # ⚠️증권사 실현손익에는 **비용이 이미 차감돼 있다**(실측: pnl_local =
    #   매도 − 매수 − 수수료·세금). 비용을 또 빼면 두 번 빼게 되므로,
    #   **되더해** 총수익을 만든 뒤 다시 뺀다.
    cost_krw = _sum([row.commission_tax_krw for row, _ in rows]) or zero
    pnl_total = _sum([i.pnl_krw for i in items]) or zero
    dividend_total = db.execute(
        select(func.sum(Dividend.amount_krw)).where(
            Dividend.account_id.in_(account_ids), Dividend.pay_date >= since
        )
    ).scalar() or zero

    breakdown = RealizedBreakdownOut(
        gross_trading_krw=pnl_total + cost_krw,
        cost_krw=cost_krw,
        # ⚠️원화로는 증권사가 합쳐서만 준다. 분리는 체결 원장의 **달러**뿐이다.
        commission_usd=stats.commission if stats else None,
        tax_usd=stats.tax if stats else None,
        dividend_krw=dividend_total,
        # ★배당을 실현손익에 **포함**한다(사용자 지정).
        net_krw=pnl_total + dividend_total,
        # ⚠️환차는 합계에 넣지 않는다 — 종목으로 번 건지 환율로 번 건지
        #   구분이 사라진다.
        fx_pnl_krw=_sum([i.fx_pnl_krw for i in items]),
    )

    return RealizedPnlListOut(
        items=items,
        total=len(items),
        pnl_krw=_sum([i.pnl_krw for i in items]),
        fx_pnl_krw=_sum([i.fx_pnl_krw for i in items]),
        win_count=wins,
        loss_count=losses,
        first_sell_date=min((i.sell_date for i in items), default=None),
        last_sell_date=max((i.sell_date for i in items), default=None),
        breakdown=breakdown,
        trades=trades_out,
        trade_stats=stats,
    )


# ── 배당 ────────────────────────────────────────────────────────────────────

@router.get("/dividends", response_model=DividendListOut)
def list_dividends(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> DividendListOut:
    """배당 수령 이력 — 최근순 + 월별/종목별 집계.

    금액은 증권사가 준 **원화**다. 이 TR(usa21730)은 외화 원금액을 주지 않아
    우리가 환산해 만들지 않는다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return DividendListOut(
            items=[], total=0, total_amount_krw=None, monthly=[], by_ticker=[],
            first_pay_date=None, last_pay_date=None,
        )

    since = inv.since(days)
    conditions = [Dividend.account_id.in_(account_ids), Dividend.pay_date >= since]

    rows = db.execute(
        select(Dividend, Asset.sector)
        .outerjoin(Asset, Asset.id == Dividend.asset_id)
        .where(*conditions)
        .order_by(Dividend.pay_date.desc(), Dividend.ticker)
    ).all()

    # ⚠️배당 원장의 종목명은 usa21730 의 `stk_nm` 이라 **영문 법인명**이다
    #   ("MICROSOFT CORP", "ISHARES 0-3 MONTH TREASURY BOND ETF"). 다른 화면은
    #   한글 이름을 쓰므로 그대로 두면 같은 종목이 다르게 보인다.
    #   `app.core.naming` 이 어느 이름을 쓸지 정한다.
    dividend_names = naming.display_names(db, {row.ticker for row, _ in rows})

    items = [
        DividendOut(
            id=row.id,
            pay_date=row.pay_date,
            ticker=row.ticker,
            asset_name=dividend_names.get(row.ticker) or row.asset_name,
            sector=sector,
            amount_krw=row.amount_krw,
            currency=row.currency,
        )
        for row, sector in rows
    ]

    # 월별 — 배당은 분기·월 주기가 뚜렷해서 월 단위가 읽기 좋다.
    # ⚠️to_char 의 포맷을 파이썬 문자열로 주면 **바인드 파라미터**가 되어 Postgres 가
    #   SELECT 절과 GROUP BY 절의 식을 같은 것으로 못 본다("must appear in the
    #   GROUP BY clause"). 식을 한 번만 만들어 재사용하고 포맷은 리터럴로 둔다.
    month_expr = func.to_char(Dividend.pay_date, literal_column("'YYYY-MM'"))
    month_rows = db.execute(
        select(month_expr, func.sum(Dividend.amount_krw), func.count())
        .where(*conditions)
        .group_by(month_expr)
        .order_by(month_expr)
    ).all()

    ticker_rows = db.execute(
        select(
            Dividend.ticker,
            func.max(Dividend.asset_name),
            func.sum(Dividend.amount_krw),
            func.count(),
        )
        .where(*conditions)
        .group_by(Dividend.ticker)
        .order_by(func.sum(Dividend.amount_krw).desc())
    ).all()

    return DividendListOut(
        items=items,
        total=len(items),
        total_amount_krw=_sum([i.amount_krw for i in items]),
        monthly=[
            DividendMonthOut(month=m, amount_krw=amount, count=count)
            for m, amount, count in month_rows
        ],
        by_ticker=[
            DividendByTickerOut(
                ticker=t,
                asset_name=dividend_names.get(t) or name,
                amount_krw=amount,
                count=count,
            )
            for t, name, amount, count in ticker_rows
        ],
        first_pay_date=min((i.pay_date for i in items), default=None),
        last_pay_date=max((i.pay_date for i in items), default=None),
    )


# ── 성과분석 ────────────────────────────────────────────────────────────────

# 화면에 세워 둘 기간 칸. 데이터가 모자란 칸은 None 으로 비워 둔다(0% 가 아니다).
_PERIODS: list[tuple[str, int]] = [
    ("1개월", 30),
    ("3개월", 91),
    ("6개월", 182),
    ("1년", 365),
    ("전체", 36500),
]

# 기간별 위험지표는 이 두 구간만 낸다. 3년 칸은 만들지 않았다 —
# 키움이 주는 일별 시계열이 약 530일(2년)이라 3년 칸은 영원히 빈 칸이 된다.
_RISK_WINDOWS: list[tuple[str, int]] = [("최근 1년", 365), ("전체", 36500)]


# 기여도는 17종목을 더해 검산하므로 반올림 오차가 눈에 띈다. 다른 비율보다
# 두 자리 더 잡는다 — 6자리면 누적 오차가 표시 정밀도 바로 아래까지 올라온다.
_CONTRIBUTION = Decimal("0.00000001")


def _contribution_ratio(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_CONTRIBUTION, rounding=ROUND_HALF_UP)


def _ratio(value: Decimal | None) -> Decimal | None:
    """비율을 소수 6자리로 자른다 — 화면에서 쓰는 정밀도보다 넉넉하다."""
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _risk_block(label: str, rows: list[pa.DailyReturn]) -> RiskMetricsOut:
    dd = pa.max_drawdown(rows)
    return RiskMetricsOut(
        label=label,
        observations=len(rows),
        annualized_return=_ratio(pa.annualized_return(rows)),
        volatility=_ratio(pa.volatility(rows)),
        downside_volatility=_ratio(pa.downside_volatility(rows)),
        max_drawdown=_ratio(dd.value) if dd else None,
        max_drawdown_peak_date=dd.peak_date if dd else None,
        max_drawdown_trough_date=dd.trough_date if dd else None,
        sharpe=_ratio(pa.sharpe(rows)),
        sortino=_ratio(pa.sortino(rows)),
        hit_ratio=_ratio(pa.hit_ratio(rows)),
    )


@router.get("/performance/analytics", response_model=PerformanceAnalyticsOut)
def get_performance_analytics(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> PerformanceAnalyticsOut:
    """성과·위험 지표 + 종목별 절대 기여도.

    `ETF성과분석_양식_v2.html` 의 구성을 따르되, 벤치마크/Peer 대비 항목은 뺐다 —
    개인 계좌에는 비교 기준이 정의돼 있지 않아서 상대성과는 만들 수 없다.

    수익률은 **일별 TWR** 로 계산한다. 입출금이 수익으로 잡히지 않게 하려는 것이고,
    계산 규칙과 그 가정은 `app.core.performance_analytics` 모듈 주석에 적어 뒀다.
    """
    empty = PerformanceAnalyticsOut(
        first_date=None, last_date=None, periods=[], risk=[], monthly=[],
        drawdown=[], contributions=[], total_purchase_krw=None,
        total_unrealized_pnl_krw=None, total_return=None,
        realized_pnl_krw=None, dividend_krw=None, flow_shifts=[],
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_assets_krw),
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            AccountDailyPerformance.base_date >= since,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()

    # ⚠️수익률을 내기 전에 **입출금 날짜 어긋남을 먼저 바로잡는다**.
    #   키움은 입금을 자산 반영일보다 하루 늦게 기록해 주는 경우가 있는데,
    #   그대로 계산하면 입금이 하루짜리 +140% 수익으로 둔갑한다(실측 사례).
    points = [
        pa.DailyPoint(base_date=d, assets_krw=a, deposit_krw=dep, withdrawal_krw=wd)
        for d, a, dep, wd in rows
    ]
    points, shifts = pa.reconcile_flows(points)
    returns = pa.daily_returns(points)

    periods = []
    for label, span in _PERIODS:
        sliced = pa.window(returns, span)
        periods.append(
            PeriodReturnOut(
                label=label,
                days=span,
                return_ratio=_ratio(pa.cumulative_return(sliced)),
                start_date=sliced[0].base_date if sliced else None,
                end_date=sliced[-1].base_date if sliced else None,
                observations=len(sliced),
            )
        )

    risk = [_risk_block(label, pa.window(returns, span)) for label, span in _RISK_WINDOWS]

    monthly = [
        MonthlyReturnOut(month=month, return_ratio=_ratio(value) or Decimal("0"))
        for month, value in pa.monthly_returns(returns)
    ]

    # 낙폭 추이 — 고점 대비 몇 % 아래인지. 차트가 0 아래로만 그려진다.
    drawdown: list[DrawdownPointOut] = []
    peak = Decimal("0")
    for r in returns:
        peak = max(peak, r.index)
        if peak > 0:
            drawdown.append(
                DrawdownPointOut(base_date=r.base_date, drawdown=_ratio(r.index / peak - Decimal("1")) or Decimal("0"))
            )

    contributions, totals = _contributions(db, account_ids)

    realized = db.execute(
        select(func.sum(RealizedPnl.pnl_krw)).where(
            RealizedPnl.account_id.in_(account_ids),
            RealizedPnl.sell_date >= since,
        )
    ).scalar()
    dividend = db.execute(
        select(func.sum(Dividend.amount_krw)).where(
            Dividend.account_id.in_(account_ids),
            Dividend.pay_date >= since,
        )
    ).scalar()

    return PerformanceAnalyticsOut(
        first_date=returns[0].base_date if returns else None,
        last_date=returns[-1].base_date if returns else None,
        periods=periods,
        risk=risk,
        monthly=monthly,
        drawdown=drawdown,
        contributions=contributions,
        total_purchase_krw=totals[0],
        total_unrealized_pnl_krw=totals[1],
        total_return=totals[2],
        realized_pnl_krw=realized,
        dividend_krw=dividend,
        flow_shifts=[
            FlowShiftOut(moved_from=f.moved_from, moved_to=f.moved_to, amount=f.amount)
            for f in shifts
        ],
    )


def _contributions(
    db: Session, account_ids: list[uuid.UUID]
) -> tuple[list[ContributionOut], tuple[Decimal | None, Decimal | None, Decimal | None]]:
    """종목별 절대 기여도.

    분모는 **전체 매입원가**다. 그래야 종목 기여도를 다 더하면 포트폴리오
    평가수익률과 같아진다 — 화면에서 바로 검산할 수 있다.

    ⚠️"정확히"는 아니다. 종목마다 반올림한 뒤 더하므로 마지막 자리에 오차가
      남는다(실측: 17종목에서 3e-6). 그래서 **기여도는 8자리로 반올림한다** —
      6자리였을 때의 오차가 표시 정밀도(소수 2자리 %) 바로 아래였다.
      과장해서 "정확히 일치"라고 쓰면 검산하다 어긋난 자리를 보고 버그로 읽는다.

    ⚠️매입원가를 KRW 로 환산할 수 없는 종목이 하나라도 있으면 그 종목의 기여도는
      None 이다. 0 으로 채우면 합계 검산이 조용히 어긋난다.
    """
    rows = db.execute(
        select(CurrentPosition, Asset)
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .order_by(CurrentPosition.unrealized_pnl_krw.desc().nullslast())
    ).all()
    if not rows:
        return [], (None, None, None)

    # 종목별 누적 배당 — 기여도 분자에는 넣지 않고 참고 열로만 보여 준다.
    # (평가손익은 '아직 안 판 것', 배당은 '이미 받은 현금'이라 성격이 다르다.)
    dividends = dict(
        db.execute(
            select(Dividend.ticker, func.sum(Dividend.amount_krw))
            .where(Dividend.account_id.in_(account_ids))
            .group_by(Dividend.ticker)
        ).all()
    )

    purchases = [_purchase_krw(p, a.currency) for p, a in rows]
    total_purchase = _sum(purchases)
    total_pnl = _sum([p.unrealized_pnl_krw for p, _ in rows])
    total_value = _sum([p.market_value_krw for p, _ in rows])

    items = [
        ContributionOut(
            asset_id=asset.id,
            ticker=asset.ticker,
            name=asset.name,
            sector=asset.sector,
            tech_l1=asset.tech_l1,
            weight=(
                _ratio(position.market_value_krw / total_value)
                if position.market_value_krw is not None and total_value
                else None
            ),
            purchase_krw=purchase,
            market_value_krw=position.market_value_krw,
            unrealized_pnl_krw=position.unrealized_pnl_krw,
            unrealized_return=position.unrealized_return,
            dividend_krw=dividends.get(asset.ticker),
            contribution=(
                _contribution_ratio(position.unrealized_pnl_krw / total_purchase)
                if position.unrealized_pnl_krw is not None and total_purchase
                else None
            ),
        )
        for (position, asset), purchase in zip(rows, purchases)
    ]

    total_return = (
        _ratio(total_pnl / total_purchase)
        if total_pnl is not None and total_purchase
        else None
    )
    return items, (total_purchase, total_pnl, total_return)


# ── 편입비 ──────────────────────────────────────────────────────────────────

@router.get("/inclusion", response_model=InclusionOut)
def get_inclusion(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> InclusionOut:
    """편입비 — 매매 이력을 되감아 종목별 원가 비중과 편입/청산 이벤트를 만든다.

    ⚠️스냅샷을 쓰지 않는다. `portfolio_snapshots` 에는 오늘 것 한 줄뿐이라
      과거 비중을 만들 수 없다. 매매 이력은 증권사가 과거치를 그대로 준다.

    ⚠️**원가(USD) 기준**이다. 평가금액 기준 과거 비중은 종목별 과거 주가가
      있어야 하는데 저장하지 않는다. trades.amount_krw 는 전부 비어 있고
      거래일 환율도 없어서, 오늘 환율을 과거 거래에 곱하는 대신 USD 로 둔다.
    """
    empty = InclusionOut(
        currency="USD", first_trade_date=None, last_trade_date=None,
        holdings=[], events=[], monthly_weights=[], total_cost=None,
        open_count=0, exited_count=0,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    # ⚠️여기만 투자 기간을 적용하지 **않는다.** 이 화면은 원가를 체결로
    #   되감는다 — 기간을 자르면 그 앞에 산 종목이 통째로 사라진다
    #   (실측: TSL 이 보유 목록에는 있는데 편입비에서 빠졌다).
    #   기간은 '얼마를 벌었나'를 자를 때 쓰는 것이지, '얼마에 샀나'를
    #   자를 때 쓰는 것이 아니다.
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(Trade)
        .where(Trade.account_id.in_(account_ids), Trade.trade_date >= since)
        # ★체결 순서를 그대로 넘긴다. trade_no 가 같은 날 안의 순서를 정한다 —
        #   순서를 바꾸면 이동평균 원가가 어긋난다.
        .order_by(Trade.trade_date, Trade.trade_no)
    ).scalars().all()
    if not rows:
        return empty

    trades = [
        pt.TradeRow(
            trade_date=t.trade_date,
            ticker=t.ticker,
            side=t.side,
            quantity=t.quantity,
            amount=t.amount_local,
            price=t.price,
            asset_name=t.asset_name,
        )
        for t in rows
    ]
    events, history = pt.build_timeline(trades)
    periods = pt.holding_periods(events)
    final = history[max(history)] if history else {}

    # ★복원 결과를 **실제 보유**와 대조한다(2026-09-22).
    #   매매 이력에 매도가 빠지면 이미 판 종목이 영영 보유 중으로 남는다.
    #   실측: SKHY 는 2026-09-18 에 팔려 realized_pnl 에 있는데 그 매도 체결만
    #   trades 에 없었다(체결 이력이 09-16 에서 끊겨 있었다). 그대로 두면
    #   편입비 분모에 $344 가 계속 섞인다.
    held_now = {
        ticker
        for (ticker,) in db.execute(
            select(Asset.ticker)
            .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
            .where(CurrentPosition.account_id.in_(account_ids))
        ).all()
    }
    # 매도 체결이 빠졌을 때 실제 청산일은 실현손익에서 가져온다.
    sold_at = dict(
        db.execute(
            select(RealizedPnl.ticker, func.max(RealizedPnl.sell_date))
            .where(RealizedPnl.account_id.in_(account_ids))
            .group_by(RealizedPnl.ticker)
        ).all()
    )
    stale = {t for t in final if t not in held_now}

    # ⚠️분모에서 STALE 을 뺀다. 안 빼면 이미 판 종목이 편입비를 갉아먹는다.
    total_cost = (
        sum((l.cost for t, l in final.items() if t not in stale), Decimal("0")) or None
    )

    buys: dict[str, int] = {}
    sells: dict[str, int] = {}
    # ★'누적 매수'와 '보유 원가'는 다른 숫자다. 실측으로 매수 $42,213 인데 보유
    #   원가는 $24,247 다 — 판 것과 이미 회수한 원금이 빠지기 때문이다. 화면이
    #   보유 원가를 "누적 투자원금"이라고 부르고 있었는데, 그 이름이면 $42,213
    #   을 기대하게 된다. 둘 다 내보내고 이름을 갈라 준다.
    total_buy = Decimal("0")
    total_sell = Decimal("0")
    for t in trades:
        (buys if t.is_buy else sells)[t.ticker] = (
            (buys if t.is_buy else sells).get(t.ticker, 0) + 1
        )
        if t.amount is not None:
            if t.is_buy:
                total_buy += t.amount
            else:
                total_sell += t.amount

    # ⚠️같은 종목이 화면마다 다른 이름으로 보이면 안 된다. 체결 원장의 종목명은
    #   증권사가 준 날것이라 띄어쓰기가 없다 — GLD 가 여기서는
    #   "SPDRGOLDSHARESHKD", 다른 화면에서는 "금 SPDR ETF" 였다.
    #   **자산 표의 이름을 먼저 쓰고**, 없을 때만 체결 원장 이름으로 떨어진다
    #   (이미 판 종목은 자산 표에 없을 수 있다).
    names = {t.ticker: t.asset_name for t in trades if t.asset_name}
    names.update(naming.display_names(db, {t.ticker for t in trades}))
    today = date.today()
    holdings = []
    for ticker, (entry, exited) in sorted(periods.items()):
        lot = final.get(ticker)
        is_stale = ticker in stale
        if is_stale:
            status = "STALE"
            # 매도 체결은 없지만 실현손익에는 있다 — 그 날짜를 청산일로 쓴다.
            exited = exited or sold_at.get(ticker)
        elif exited is not None or lot is None:
            status = "CLOSED"
        else:
            status = "OPEN"

        holdings.append(
            InclusionHoldingOut(
                ticker=ticker,
                asset_name=names.get(ticker),
                first_entry=entry,
                exited_at=exited,
                status=status,
                holding_days=((exited or today) - entry).days,
                cost=lot.cost if lot else None,
                weight=(
                    (lot.cost / total_cost).quantize(_RATIO, rounding=ROUND_HALF_UP)
                    if lot and total_cost and not is_stale
                    else None
                ),
                buy_count=buys.get(ticker, 0),
                sell_count=sells.get(ticker, 0),
            )
        )
    # 보유 중 → 이력 누락 → 청산 순. 같은 묶음 안에서는 비중 큰 순.
    _ORDER = {"OPEN": 0, "STALE": 1, "CLOSED": 2}
    holdings.sort(key=lambda h: (_ORDER[h.status], -(h.weight or Decimal("0"))))

    return InclusionOut(
        currency="USD",
        first_trade_date=trades[0].trade_date,
        last_trade_date=trades[-1].trade_date,
        holdings=holdings,
        events=[
            InclusionEventOut(
                event_date=e.event_date,
                ticker=e.ticker,
                # ⚠️`names` 가 먼저다. 이벤트의 이름은 체결 원장 날것이라
                #   띄어쓰기가 없다 — 같은 종목이 왼쪽 표와 오른쪽 목록에서
                #   다른 이름으로 보이면 다른 종목으로 읽힌다.
                asset_name=names.get(e.ticker) or e.asset_name,
                kind=e.kind,
                quantity=e.quantity,
                amount=e.amount,
                weight_before=e.weight_before,
                weight_after=e.weight_after,
                holdings_after=e.holdings_after,
            )
            # 최근 것이 위로. 편입 구조가 바뀐 순간만 본다.
            for e in reversed(events)
        ],
        monthly_weights=[
            InclusionWeightPointOut(
                base_date=w.base_date, ticker=w.ticker, weight=w.weight, cost=w.cost
            )
            for w in pt.month_end_weights(history)
        ],
        total_cost=total_cost,
        total_buy=total_buy,
        total_sell=total_sell,
        open_count=sum(1 for h in holdings if h.status == "OPEN"),
        exited_count=sum(1 for h in holdings if h.status != "OPEN"),
    )


# ── 실시간 시세 ─────────────────────────────────────────────────────────────

@router.get("/quotes", response_model=LiveQuotesOut)
def get_live_quotes(
    account_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> LiveQuotesOut:
    """보유 종목의 **실시간 현재가**와 그 가격으로 다시 계산한 평가금액.

    ★왜 따로 있나(2026-09-22): 잔고 동기화(/sync/quick)는 키움 TR 을 4개 써서
      30초 주기로만 돌린다. 그래서 가격도 30초마다만 움직였다. 여기는 시세만
      받아오므로 5초 주기로 돌려도 가볍다 — 실측 17종목 0.60초(동시 요청).

    ⚠️환율은 **마지막 동기화 때 증권사가 준 값에 고정**이다. 여기서 새로 받지
      않는다. 가격과 환율이 다른 시점 값이면 합계가 종목별 수치와 어긋난다.
      움직이는 건 가격뿐이다.

    ⚠️시세를 못 받은 종목은 0 으로 채우지 않고 `missing` 에 담아 내보낸다.

    ⚠️**평가손익은 증권사와 같은 기준으로 낸다 — 제비용을 뺀 값이다.**
      예전에는 (평가액 − 매입액) 만 냈다. 그래서 자산 현황 화면에서 실시간
      시세가 도착하는 순간 **가격이 하나도 안 움직여도 평가손익이 ₩174,262
      뛰었다**(실측: 실시간 총 손익이 증권사 대비 +515,518 인데, 평가액 차이는
      +341,256 뿐이었다 — 나머지 174,262 가 정확히 제비용이다).
      한 칸이 두 기준을 오가고 있었다.

    ⚠️여기서 빼는 제비용은 **모형**이다(`fee_reserve.modelled_krw`). 증권사가
      실시간 평가손익을 주지 않으니 실측할 방법이 없다. 얼마를 뺐는지
      `fee_reserve_krw` 로 같이 내보낸다 — 숨기고 빼지 않는다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return LiveQuotesOut(
            items=[], total_market_value_krw=None, total_unrealized_pnl_krw=None,
            total_fee_reserve_krw=None, missing=[], fetched=0, as_of=None,
        )

    rows = db.execute(
        select(CurrentPosition, Asset)
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .order_by(CurrentPosition.market_value_krw.desc().nullslast())
    ).all()
    if not rows:
        return LiveQuotesOut(
            items=[], total_market_value_krw=None, total_unrealized_pnl_krw=None,
            total_fee_reserve_krw=None, missing=[], fetched=0, as_of=None,
        )

    quotes, fetched = quote_cache.get_quotes([a.ticker for _, a in rows])

    items: list[LiveQuoteOut] = []
    missing: list[str] = []
    for position, asset in rows:
        quote = quotes.get(asset.ticker)
        if quote is None:
            missing.append(asset.ticker)
            continue

        quantity = position.quantity
        value_local = quantity * quote.price if quantity is not None else None
        rate = position.exchange_rate
        value_krw = (
            (value_local * rate).quantize(_MONEY, rounding=ROUND_HALF_UP)
            if value_local is not None and rate is not None
            else None
        )
        purchase_krw = _purchase_krw(position, asset.currency)
        # 증권사와 같은 기준을 만든다 — 제비용을 뺀 평가손익.
        reserve = fr.modelled_krw(value_krw, purchase_krw)
        items.append(
            LiveQuoteOut(
                ticker=asset.ticker,
                name=asset.name,
                price=quote.price,
                currency=quote.currency,
                previous_close=quote.previous_close,
                change=quote.change,
                change_rate=quote.change_rate,
                as_of=quote.as_of,
                source=quote.source,
                thin_session=quote_cache.is_thin_session_quote(quote),
                volume=quote.volume,
                quantity=quantity,
                market_value_local=value_local,
                market_value_krw=value_krw,
                unrealized_pnl_krw=(
                    (value_krw - purchase_krw - reserve)
                    if value_krw is not None
                    and purchase_krw is not None
                    and reserve is not None
                    else None
                ),
                fee_reserve_krw=reserve,
            )
        )

    return LiveQuotesOut(
        items=items,
        total_market_value_krw=_sum([i.market_value_krw for i in items]),
        total_unrealized_pnl_krw=_sum([i.unrealized_pnl_krw for i in items]),
        total_fee_reserve_krw=_sum([i.fee_reserve_krw for i in items]),
        missing=missing,
        fetched=fetched,
        as_of=max((i.as_of for i in items if i.as_of), default=None),
    )


# ── 주문 내역 ───────────────────────────────────────────────────────────────

def _order_status(order: Order) -> str:
    """주문 하나의 결말. 수량으로만 판정한다 — 증권사가 상태 문자열을 주지 않는다.

    CANCELLED(취소) · FILLED(전량 체결) · PARTIAL(부분 체결) · UNFILLED(미체결)
    """
    filled = order.filled_quantity or Decimal("0")
    cancelled = order.cancelled_quantity or Decimal("0")
    ordered = order.order_quantity or Decimal("0")
    if cancelled > 0 and filled <= 0:
        return "CANCELLED"
    if ordered > 0 and filled >= ordered:
        return "FILLED"
    if filled > 0:
        return "PARTIAL"
    return "UNFILLED"


def _improvement(order: Order) -> Decimal | None:
    """지정가 대비 체결가가 **얼마나 유리했나**(양수 = 유리).

    매수는 싸게 체결될수록, 매도는 비싸게 체결될수록 유리하다. 방향을 맞춰 두지
    않으면 매수·매도 부호가 반대라 평균이 의미를 잃는다.

    ⚠️미체결이면 None 이다(체결가가 없다). 0 으로 두면 "정확히 지정가에 체결"로
      읽혀서 미체결이 평균에 섞인다.
    """
    ordered, filled = order.order_price, order.filled_price
    if ordered is None or filled is None or ordered <= 0:
        return None
    raw = (ordered - filled) if order.side == "BUY" else (filled - ordered)
    return (raw / ordered).quantize(_RATIO, rounding=ROUND_HALF_UP)


@router.get("/orders", response_model=OrderListOut)
def list_orders(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(365, ge=1, le=3650),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OrderListOut:
    """주문 내역 — 체결 이력이 감추는 것들.

    체결은 성사된 것만 알려준다. 여기에는 **미체결·취소·슬리피지**가 남는다.
    """
    empty = OrderListOut(
        items=[], total=0, filled=0, partial=0, unfilled=0, cancelled=0,
        fill_rate=None, avg_improvement=None,
        first_order_date=None, last_order_date=None,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(Order)
        .where(Order.account_id.in_(account_ids), Order.order_date >= since)
        .order_by(Order.order_date.desc(), Order.order_time.desc().nullslast())
    ).scalars().all()
    if not rows:
        return empty

    # 통계는 **필터 전 전체**로 낸다 — "미체결만 보기"를 눌렀다고 체결률이
    # 0% 로 바뀌면 그 숫자는 거짓말이 된다.
    counts = {"FILLED": 0, "PARTIAL": 0, "UNFILLED": 0, "CANCELLED": 0}
    improvements: list[Decimal] = []
    for order in rows:
        counts[_order_status(order)] += 1
        gain = _improvement(order)
        if gain is not None:
            improvements.append(gain)

    wanted = status.upper() if status else None
    items = [
        OrderOut(
            id=order.id,
            ticker=order.ticker,
            asset_name=order.asset_name,
            order_date=order.order_date,
            order_time=order.order_time,
            order_no=order.order_no,
            side=order.side,
            order_type=order.order_type,
            currency=order.currency,
            status=_order_status(order),
            order_quantity=order.order_quantity,
            filled_quantity=order.filled_quantity,
            cancelled_quantity=order.cancelled_quantity,
            remaining_quantity=order.remaining_quantity,
            order_price=order.order_price,
            filled_price=order.filled_price,
            filled_amount=order.filled_amount,
            improvement=_improvement(order),
            channel=order.channel,
        )
        for order in rows
        if wanted is None or _order_status(order) == wanted
    ]

    decided = counts["FILLED"] + counts["PARTIAL"] + counts["UNFILLED"]
    return OrderListOut(
        items=items,
        total=len(rows),
        filled=counts["FILLED"],
        partial=counts["PARTIAL"],
        unfilled=counts["UNFILLED"],
        cancelled=counts["CANCELLED"],
        # ⚠️취소는 분모에서 뺀다. 내가 거둬들인 주문을 '체결 실패'로 세면 안 된다.
        fill_rate=(
            (Decimal(counts["FILLED"]) / Decimal(decided)).quantize(
                _RATIO, rounding=ROUND_HALF_UP
            )
            if decided
            else None
        ),
        avg_improvement=(
            (sum(improvements, Decimal("0")) / Decimal(len(improvements))).quantize(
                _RATIO, rounding=ROUND_HALF_UP
            )
            if improvements
            else None
        ),
        first_order_date=min(o.order_date for o in rows),
        last_order_date=max(o.order_date for o in rows),
    )


# ── 입출금 ──────────────────────────────────────────────────────────────────

@router.get("/cashflow", response_model=CashflowOut)
def get_cashflow(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> CashflowOut:
    """입출금 이력과 "넣은 돈 대비 지금".

    원천은 새 TR 이 아니라 이미 적재된 `account_daily_performance` 다
    (키움 usa21670 의 ina_amt/pymn_amt). 입출금 전용 TR 을 또 부르지 않는다.

    ★이 화면이 답해야 할 질문은 하나다: **내가 넣은 돈이 얼마고 지금 얼마인가.**
      수익률 화면은 "얼마나 잘 굴렸나"(TWR)를 보고, 여기는 "실제로 얼마가
      늘었나"(금액)를 본다. 둘은 다른 질문이라 숫자도 다르다.

    ⚠️기초 잔고를 **가정하지 않는다.** 조회 구간 첫날의 자산에서 그날 순입금을
      뺀 값이 0 이 아니면, 그건 구간 시작 전부터 있던 돈이다. 그걸 수익에
      섞으면 "넣지도 않은 돈이 불어난" 것처럼 보인다 — opening_balance 로 따로 낸다.

    ⚠️여기서는 입출금 날짜를 **증권사가 기록한 그대로** 쓴다. 수익률 계산에서
      쓰는 날짜 보정(reconcile_flows)을 적용하지 않는다 — 그건 수익률을 바로잡기
      위한 것이고, 출납 기록은 증권사 장부 그대로여야 대조가 된다.
    """
    empty = CashflowOut(
        events=[], monthly=[], total_deposit_krw=None, total_withdrawal_krw=None,
        net_deposit_krw=None, first_day_flow_krw=None,
        opening_balance_krw=None, current_assets_krw=None,
        gain_krw=None, gain_ratio=None, first_date=None, last_date=None,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
            func.sum(AccountDailyPerformance.deposit_assets_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            AccountDailyPerformance.base_date >= since,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()
    if not rows:
        return empty

    zero = Decimal("0")
    events: list[CashflowEventOut] = []
    monthly_acc: dict[str, list[Decimal]] = {}

    for base_date, deposit, withdrawal, assets in rows:
        deposit = deposit or zero
        withdrawal = withdrawal or zero
        if deposit > 0 or withdrawal > 0:
            events.append(
                CashflowEventOut(
                    base_date=base_date,
                    deposit_krw=deposit if deposit > 0 else None,
                    withdrawal_krw=withdrawal if withdrawal > 0 else None,
                    net_krw=deposit - withdrawal,
                    assets_after_krw=assets,
                )
            )
        key = f"{base_date.year:04d}-{base_date.month:02d}"
        bucket = monthly_acc.setdefault(key, [zero, zero])
        bucket[0] += deposit
        bucket[1] += withdrawal

    # ⚠️**첫날의 입출금은 시작 잔고에 이미 반영돼 있다** — 순입금에서 뺀다.
    #   수익률 추이 화면이 이미 그렇게 센다. 두 화면이 다르게 세면 같은 계좌를
    #   놓고 "순입금"이 두 값으로 나온다(실측: 9,715,029 vs 1,874,876).
    first_date = rows[0][0]
    counted = [e for e in events if e.base_date > first_date]
    total_deposit = _sum([e.deposit_krw for e in counted]) or zero
    total_withdrawal = _sum([e.withdrawal_krw for e in counted]) or zero
    net_deposit = total_deposit - total_withdrawal

    # 기간 시작 시점의 자산이 출발점이다(그날 들어온 돈까지 포함).
    opening = rows[0][3]
    first_day_flow = (rows[0][1] or zero) - (rows[0][2] or zero)
    current = rows[-1][3]
    gain = (
        current - (opening or zero) - net_deposit
        if current is not None
        else None
    )
    base = (opening or zero) + net_deposit

    return CashflowOut(
        # 최근이 위로 — 마지막에 무슨 일이 있었는지가 먼저 궁금하다.
        events=list(reversed(events)),
        monthly=[
            CashflowMonthOut(
                month=month,
                deposit_krw=values[0],
                withdrawal_krw=values[1],
                net_krw=values[0] - values[1],
            )
            for month, values in sorted(monthly_acc.items())
            # 입출금이 아예 없던 달은 빼둔다 — 0 만 늘어놓으면 목록이 안 읽힌다.
            if values[0] > 0 or values[1] > 0
        ],
        total_deposit_krw=total_deposit,
        total_withdrawal_krw=total_withdrawal,
        net_deposit_krw=net_deposit,
        first_day_flow_krw=first_day_flow,
        opening_balance_krw=opening,
        current_assets_krw=current,
        gain_krw=gain.quantize(_MONEY, rounding=ROUND_HALF_UP) if gain is not None else None,
        gain_ratio=(
            (gain / base).quantize(_RATIO, rounding=ROUND_HALF_UP)
            if gain is not None and base > 0
            else None
        ),
        first_date=rows[0][0],
        last_date=rows[-1][0],
    )


# ── 벤치마크 비교 ───────────────────────────────────────────────────────────

# 기준 지수. 보유의 47%가 컴퓨팅 인프라고 최대 비중이 SOXL(반도체 3배)이라
# 시장 전체(S&P 500)와 반도체(SOX) 둘을 세운다.
_BENCHMARKS: list[tuple[str, str]] = [
    ("^GSPC", "S&P 500"),
    ("^SOX", "필라델피아 반도체"),
]
_FX_SYMBOL = "KRW=X"

_BENCH_PERIODS: list[tuple[str, int]] = [
    ("1M", 30), ("3M", 91), ("6M", 182), ("1Y", 365), ("전체", 36500),
]


@router.get("/benchmark", response_model=BenchmarkOut)
def get_benchmark(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> BenchmarkOut:
    """내 계좌 수익률 vs 기준 지수.

    ★**통화를 맞춘다.** 내 계좌 수익률은 원화 기준(키움이 KRW 로 준다)이고 지수는
      달러 기준이다. 그대로 비교하면 환율 변동이 통째로 내 실력처럼 보인다.
      그래서 지수를 **원화로 환산해서** 비교한다 — "그 지수에 원화로 투자했다면"
      이 올바른 비교 대상이다. USD 기준 수익률도 같이 내보내 차이를 볼 수 있게 한다.

    ⚠️계좌 시계열은 주말 행까지 있고(실측 530행 중 152행) 지수는 거래일만 있다.
      **양쪽에 다 있는 날짜만** 써서 맞춘다 — 한쪽을 앞으로 채우면 없는 날의
      움직임이 생긴다.

    ⚠️기간을 자를 때마다 **그 구간 시작으로 다시 기준을 잡는다**(rebase).
      전체 구간 지수를 그대로 잘라 쓰면 1개월 수익률이 누적값 차이로 나온다.

    ⚠️기준일은 **첫 수익률 직전 날**이다. 첫 수익률일의 지수를 기준으로 삼으면
      그날 수익률이 통째로 빠진다 — 실측으로 같은 구간·같은 관측일수인데 이
      화면이 −1.21%, 성과 분석이 −1.98% 를 보였다. 값이 비슷해서 버그로
      보이지도 않았다. 지금은 `scripts/audit_consistency.py` 가 두 화면을 맞댄다.

    ★**시차 보정은 하지 않는다.** 한국 마감 기준 계좌 시계열과 미국 지수 종가를
      같은 날짜로 맞대는 게 맞는지 확인했다 — 계좌 일간수익률과 ^SOX 일간수익률의
      상관이 lag 0 에서 +0.699, lag 1 에서 +0.016, lag 2 에서 −0.212 였다(75일).
      증권사가 같은 달력날짜로 기록한다는 뜻이므로 밀지 않는다.
    """
    empty = BenchmarkOut(
        series=[], periods=[], benchmarks=[m[1] for m in _BENCHMARKS],
        currency_note="", first_date=None, last_date=None,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_assets_krw),
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            AccountDailyPerformance.base_date >= since,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()
    if not rows:
        return empty

    points, _shifts = pa.reconcile_flows(
        [
            pa.DailyPoint(base_date=d, assets_krw=a, deposit_krw=dep, withdrawal_krw=wd)
            for d, a, dep, wd in rows
        ]
    )
    returns = pa.daily_returns(points)
    if not returns:
        return empty
    mine = {r.base_date: r.index for r in returns}

    # ⚠️첫 수익률 **직전** 날짜의 지수도 넣는다. 안 넣으면 비교 시작점이 하루
    #   밀려 **첫날 수익률이 통째로 빠진다.** 실측: 같은 구간(2026-06-05~09-21)
    #   같은 관측일수(109일)인데 이 화면은 -1.21%, 성과 분석은 -1.98% 였다.
    #   지수 쪽은 그날 종가가 기준이 되는데 계좌 쪽만 그날 **종료 후** 지수가
    #   기준이 되어, 둘이 하루 어긋난 채 비교되고 있었다.
    prior = [p.base_date for p in points if p.base_date < returns[0].base_date]
    if prior:
        mine[prior[-1]] = pa.base_index(returns)

    history = fetch_history([s for s, _ in _BENCHMARKS] + [_FX_SYMBOL], range_="2y")
    fx = history.get(_FX_SYMBOL)

    # 양쪽에 다 있는 날만 쓴다.
    usable = sorted(
        d
        for d in mine
        if all(
            (series := history.get(symbol)) is not None
            and series.close_on_or_before(d) is not None
            for symbol, _ in _BENCHMARKS
        )
        and (fx is None or fx.close_on_or_before(d) is not None)
    )
    if not usable:
        return empty

    def level(symbol: str, when: date, in_krw: bool) -> Decimal | None:
        series = history.get(symbol)
        if series is None:
            return None
        value = series.close_on_or_before(when)
        if value is None or not in_krw:
            return value
        rate = fx.close_on_or_before(when) if fx else None
        return None if rate is None else value * rate

    def ratio(a: Decimal | None, b: Decimal | None) -> Decimal | None:
        if a is None or b is None or b == 0:
            return None
        return (a / b - Decimal("1")).quantize(_RATIO, rounding=ROUND_HALF_UP)

    # 차트용 시계열 — 구간 시작을 100 으로 맞춘 지수.
    base_day = usable[0]
    series_out: list[BenchmarkPointOut] = []
    for day in usable:
        values: dict[str, Decimal | None] = {}
        for symbol, name in _BENCHMARKS:
            change = ratio(level(symbol, day, True), level(symbol, base_day, True))
            values[name] = (
                (Decimal("100") * (Decimal("1") + change)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if change is not None
                else None
            )
        mine_change = ratio(mine.get(day), mine.get(base_day))
        series_out.append(
            BenchmarkPointOut(
                base_date=day,
                portfolio=(
                    (Decimal("100") * (Decimal("1") + mine_change)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if mine_change is not None
                    else None
                ),
                benchmarks=values,
            )
        )

    last = usable[-1]
    periods_out: list[BenchmarkPeriodOut] = []
    for label, span in _BENCH_PERIODS:
        cutoff = last - timedelta(days=span)
        # ⚠️구간 시작은 **usable 안에서** 고른다. 지수에 없는 날을 기준으로
        #   잡으면 내 수익률만 그 날부터 세어져 비교가 어긋난다.
        window = [d for d in usable if d >= cutoff]
        if len(window) < 2:
            continue
        start = window[0]
        mine_change = ratio(mine.get(last), mine.get(start))
        krw: dict[str, Decimal | None] = {}
        usd: dict[str, Decimal | None] = {}
        excess: dict[str, Decimal | None] = {}
        for symbol, name in _BENCHMARKS:
            in_krw = ratio(level(symbol, last, True), level(symbol, start, True))
            krw[name] = in_krw
            usd[name] = ratio(level(symbol, last, False), level(symbol, start, False))
            excess[name] = (
                (mine_change - in_krw) if mine_change is not None and in_krw is not None
                else None
            )
        periods_out.append(
            BenchmarkPeriodOut(
                label=label,
                start_date=start,
                end_date=last,
                observations=len(window),
                portfolio=mine_change,
                benchmarks_krw=krw,
                benchmarks_usd=usd,
                excess=excess,
            )
        )

    return BenchmarkOut(
        series=series_out,
        periods=periods_out,
        benchmarks=[name for _, name in _BENCHMARKS],
        currency_note=(
            "지수는 원화로 환산해 비교합니다 — 내 계좌 수익률이 원화 기준이라 "
            "달러 지수와 그대로 견주면 환율 변동이 실력처럼 보입니다."
        ),
        first_date=usable[0],
        last_date=last,
    )


# ── 환노출 ──────────────────────────────────────────────────────────────────

_FX_PAIR = "KRW=X"
# 민감도 표에 세울 환율 변동 폭.
_FX_SHOCKS = [Decimal("-0.10"), Decimal("-0.05"), Decimal("0.05"), Decimal("0.10")]


@router.get("/fx-exposure", response_model=FxExposureOut)
def get_fx_exposure(
    account_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> FxExposureOut:
    """환노출 — 원화로 살아가는 사람이 달러 자산을 들고 있을 때의 위험.

    ★이 화면이 답하는 것: **내 손익 중 얼마가 종목이고 얼마가 환율인가.**
      실측 예(NVDA, 실현): 주가로 +₩50,182 벌었는데 환율이 1,524 → 1,380 으로
      빠져 환차 -₩121,201, 합치면 -₩71,019 였다.

    ⚠️**매입 환율을 증권사가 주지 않는다.** trades.amount_krw 는 82건 전부 비어
      있고, 일별성과의 환율 칸도 530행 전부 비어 있다. 그래서 보유 종목의
      "얼마에 샀나"는 **매수 체결일의 일별 종가 환율로 추정**한다.
      추정이라는 사실을 화면에도 적는다 — 실제 체결 환율과는 다를 수 있다.

    ⚠️실현 환차손익은 추정이 아니다. 증권사가 매수·매도 환율을 함께 주므로
      그 값을 그대로 쓴다.
    """
    empty = FxExposureOut(
        base_currency="KRW", exposed_currency="USD", current_rate=None,
        exposed_value_krw=None, exposure_ratio=None, positions=[],
        estimated_entry_rate=None, rate_change_ratio=None,
        unrealized_fx_krw=None, realized_fx_krw=None, shocks=[],
        rate_as_of=None, note="",
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    rows = db.execute(
        select(CurrentPosition, Asset)
        .join(Asset, Asset.id == CurrentPosition.asset_id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .order_by(CurrentPosition.market_value_krw.desc().nullslast())
    ).all()
    if not rows:
        return empty

    # 외화 종목만 환노출이다. 원화 종목은 환율이 움직여도 그대로다.
    foreign = [(p, a) for p, a in rows if (a.currency or "USD") != "KRW"]

    # ★2026-09-23: **외화 예수금도 환노출이다.** 계좌에 달러로 남아 있는 돈은
    #   환율이 움직이면 그대로 원화 가치가 바뀐다. 예전에는 주식만 세서
    #   민감도 표가 그만큼 작게 나왔다(실측 $982.92 = ₩1,320,356 이 빠져 있었다).
    #   분모도 총자산으로 맞춘다 — 배분 화면의 통화 축과 같은 기준이다.
    #   ⚠️지금은 주식이 전부 USD 라 양쪽 다 100% 로 보여 차이가 안 드러난다.
    #     원화 종목을 하나라도 사면 두 화면이 다른 말을 하게 되므로 지금 맞춘다.
    foreign_cash = Decimal("0")
    cash_total = Decimal("0")
    if inv.CASH_IN_ASSETS:
        for balance in db.execute(
            select(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
        ).scalars():
            value = _cash_krw(balance)
            if value is None:
                continue
            cash_total += value
            if balance.currency != "KRW":
                foreign_cash += value

    exposed = _sum([p.market_value_krw for p, _ in foreign])
    if exposed is not None and foreign_cash:
        exposed = exposed + foreign_cash
    total = _sum([p.market_value_krw for p, _ in rows])
    if total is not None and cash_total:
        total = total + cash_total
    current_rate = next(
        (p.exchange_rate for p, _ in foreign if p.exchange_rate is not None), None
    )

    # 매수 체결일 환율로 종목별 평균 매입 환율을 추정한다.
    history = fetch_history([_FX_PAIR], range_="2y")
    fx = history.get(_FX_PAIR)
    buys = db.execute(
        select(Trade.ticker, Trade.trade_date, Trade.amount_local)
        .where(
            Trade.account_id.in_(account_ids),
            Trade.side == "BUY",
            Trade.ticker.in_([a.ticker for _, a in foreign]),
        )
    ).all()

    weighted: dict[str, list[Decimal]] = {}
    for ticker, trade_date, amount in buys:
        if amount is None or fx is None:
            continue
        rate = fx.close_on_or_before(trade_date)
        if rate is None:
            continue
        bucket = weighted.setdefault(ticker, [Decimal("0"), Decimal("0")])
        bucket[0] += amount * rate
        bucket[1] += amount

    def entry_rate(ticker: str) -> Decimal | None:
        bucket = weighted.get(ticker)
        if not bucket or bucket[1] == 0:
            return None
        return (bucket[0] / bucket[1]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    positions: list[FxPositionOut] = []
    fx_pnl_total = Decimal("0")
    fx_pnl_known = False
    for position, asset in foreign:
        entry = entry_rate(asset.ticker)
        value = position.market_value_krw
        # ⚠️환차손익 = 평가금액 × (1 − 매입환율/현재환율). 매입환율을 모르면 None.
        gain = None
        if entry and current_rate and value is not None and current_rate > 0:
            gain = (value * (Decimal("1") - entry / current_rate)).quantize(
                _MONEY, rounding=ROUND_HALF_UP
            )
            fx_pnl_total += gain
            fx_pnl_known = True
        positions.append(
            FxPositionOut(
                ticker=asset.ticker,
                name=asset.name,
                currency=asset.currency or "USD",
                market_value_krw=value,
                estimated_entry_rate=entry,
                estimated_fx_pnl_krw=gain,
            )
        )

    # 포트폴리오 평균 매입 환율 — 평가금액 가중.
    numerator = sum(
        (p.market_value_krw or Decimal("0")) * (entry_rate(a.ticker) or Decimal("0"))
        for p, a in foreign
        if entry_rate(a.ticker) is not None and p.market_value_krw is not None
    )
    denominator = sum(
        (p.market_value_krw or Decimal("0"))
        for p, a in foreign
        if entry_rate(a.ticker) is not None and p.market_value_krw is not None
    )
    portfolio_entry = (
        (numerator / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if denominator
        else None
    )

    realized_fx = db.execute(
        select(func.sum(RealizedPnl.fx_pnl_krw)).where(
            RealizedPnl.account_id.in_(account_ids)
        )
    ).scalar()

    return FxExposureOut(
        base_currency="KRW",
        exposed_currency="USD",
        current_rate=current_rate,
        exposed_value_krw=exposed,
        exposure_ratio=(
            (exposed / total).quantize(_RATIO, rounding=ROUND_HALF_UP)
            if exposed is not None and total
            else None
        ),
        positions=positions,
        estimated_entry_rate=portfolio_entry,
        rate_change_ratio=(
            ((current_rate - portfolio_entry) / portfolio_entry).quantize(
                _RATIO, rounding=ROUND_HALF_UP
            )
            if portfolio_entry and current_rate and portfolio_entry > 0
            else None
        ),
        unrealized_fx_krw=(
            fx_pnl_total.quantize(_MONEY, rounding=ROUND_HALF_UP)
            if fx_pnl_known
            else None
        ),
        realized_fx_krw=realized_fx,
        shocks=[
            FxShockOut(
                move=shock,
                value_krw=(
                    (exposed * (Decimal("1") + shock)).quantize(
                        _MONEY, rounding=ROUND_HALF_UP
                    )
                    if exposed is not None
                    else None
                ),
                delta_krw=(
                    (exposed * shock).quantize(_MONEY, rounding=ROUND_HALF_UP)
                    if exposed is not None
                    else None
                ),
            )
            for shock in _FX_SHOCKS
        ],
        rate_as_of=(fx.dates[-1] if fx and fx.dates else None),
        foreign_cash_krw=foreign_cash or None,
        note=(
            "매입 환율은 증권사가 주지 않아 **매수 체결일의 일별 종가 환율로 추정**한 "
            "값입니다. 실제 체결 환율과는 다를 수 있습니다. 실현 환차손익은 증권사가 "
            "매수·매도 환율을 함께 주므로 추정이 아닙니다. 외화 예수금도 노출에 "
            "넣지만, 예수금에는 '얼마에 샀나'가 없어 평가 환차손익에는 넣지 "
            "않았습니다 — 민감도 표에는 들어갑니다."
        ),
    )


# ── 거래비용 ────────────────────────────────────────────────────────────────

@router.get("/costs", response_model=TradingCostOut)
def get_trading_costs(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> TradingCostOut:
    """수수료·세금 — 매매가 실제로 얼마를 먹었나.

    ★금액은 **USD 그대로** 둔다. 편입비와 같은 이유다 — trades.amount_krw 는
      82건 전부 비어 있고 거래일 환율도 없다. 오늘 환율을 과거 거래에 곱하면
      그 숫자는 거짓이 된다.

    ⚠️비용률의 분모는 **거래대금**이다. 평가액이 아니다 — 비용은 사고팔 때
      발생하므로 얼마를 들고 있느냐가 아니라 얼마를 굴렸느냐에 붙는다.

    ⚠️실현손익과 비용을 **빼거나 더하지 않는다.** 증권사가 주는 실현손익이
      비용을 이미 반영했는지 확실하지 않다. 두 숫자를 나란히 두고 판단은
      사용자에게 맡긴다 — 확실하지 않은 계산으로 한 숫자를 만들면 그게 더 나쁘다.
    """
    empty = TradingCostOut(
        currency="USD", trade_count=0, turnover=None, commission=None, tax=None,
        total_cost=None, cost_ratio=None, by_side=[], by_month=[], by_ticker=[],
        realized_pnl_krw=None, first_trade_date=None, last_trade_date=None,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(Trade).where(
            Trade.account_id.in_(account_ids), Trade.trade_date >= since
        )
    ).scalars().all()
    if not rows:
        return empty

    zero = Decimal("0")

    def cost_of(trade) -> Decimal:
        return (trade.commission_local or zero) + (trade.tax_local or zero)

    turnover = _sum([t.amount_local for t in rows]) or zero
    commission = _sum([t.commission_local for t in rows]) or zero
    tax = _sum([t.tax_local for t in rows]) or zero
    total_cost = commission + tax

    # 매수/매도별 — 어느 쪽에서 비용이 더 나가는지.
    sides: dict[str, list] = {}
    for trade in rows:
        bucket = sides.setdefault(trade.side, [0, zero, zero, zero])
        bucket[0] += 1
        bucket[1] += trade.amount_local or zero
        bucket[2] += trade.commission_local or zero
        bucket[3] += trade.tax_local or zero

    months: dict[str, list] = {}
    tickers: dict[str, list] = {}
    display_names = naming.display_names(db, {t.ticker for t in rows})
    for trade in rows:
        key = f"{trade.trade_date.year:04d}-{trade.trade_date.month:02d}"
        month = months.setdefault(key, [0, zero, zero])
        month[0] += 1
        month[1] += trade.amount_local or zero
        month[2] += cost_of(trade)

        row = tickers.setdefault(trade.ticker, [None, 0, zero, zero])
        # ⚠️자산 표 이름이 먼저다. 체결 원장 이름은 증권사 날것이라 띄어쓰기가
        #   없다(SOXL: "미국반도체3배디렉시온ETF"). `app.core.naming` 참고.
        row[0] = display_names.get(trade.ticker) or row[0] or trade.asset_name
        row[1] += 1
        row[2] += trade.amount_local or zero
        row[3] += cost_of(trade)

    realized = db.execute(
        select(func.sum(RealizedPnl.pnl_krw)).where(
            RealizedPnl.account_id.in_(account_ids), RealizedPnl.sell_date >= since
        )
    ).scalar()

    def ratio(cost: Decimal, base: Decimal) -> Decimal | None:
        # ⚠️거래대금이 0 이면 비용률을 낼 수 없다. 0% 로 두면 "공짜"로 읽힌다.
        return (
            (cost / base).quantize(_RATIO, rounding=ROUND_HALF_UP) if base else None
        )

    return TradingCostOut(
        currency="USD",
        trade_count=len(rows),
        turnover=turnover,
        commission=commission,
        tax=tax,
        total_cost=total_cost,
        cost_ratio=ratio(total_cost, turnover),
        by_side=[
            CostBySideOut(
                side=side,
                trade_count=values[0],
                turnover=values[1],
                commission=values[2],
                tax=values[3],
                cost_ratio=ratio(values[2] + values[3], values[1]),
            )
            for side, values in sorted(sides.items())
        ],
        by_month=[
            CostByMonthOut(
                month=month,
                trade_count=values[0],
                turnover=values[1],
                cost=values[2],
            )
            for month, values in sorted(months.items())
        ],
        by_ticker=sorted(
            [
                CostByTickerOut(
                    ticker=ticker,
                    name=values[0],
                    trade_count=values[1],
                    turnover=values[2],
                    cost=values[3],
                    cost_ratio=ratio(values[3], values[2]),
                )
                for ticker, values in tickers.items()
            ],
            key=lambda x: x.cost,
            reverse=True,
        ),
        realized_pnl_krw=realized,
        first_trade_date=min(t.trade_date for t in rows),
        last_trade_date=max(t.trade_date for t in rows),
    )


# ── 월별 현금흐름 ────────────────────────────────────────────────────────────

_FX_NOTE = (
    "월초 자산 + 순납입 + 손익으로 설명되지 않는 나머지를 '그 외'로 둡니다. "
    "환차손익이라고 적지 않은 이유는 키움 일별성과의 환율 칸이 530행 전부 비어 "
    "있어 실측할 수 없기 때문입니다. 다만 전월말 주식평가액 × 월간 USD/KRW "
    "변화와 맞춰 보면 상관계수 0.937(R²=0.878), 부호 17개월 중 15개월 일치, "
    "절대합의 63%가 설명됩니다 — 대부분 환율입니다."
)


@router.get("/monthly-cashflow", response_model=MonthlyCashflowOut)
def get_monthly_cashflow(
    account_id: uuid.UUID | None = Query(default=None),
    days: int = Query(1095, ge=30, le=3650),
    db: Session = Depends(get_db),
) -> MonthlyCashflowOut:
    """월별 현금흐름 — 한 달 동안 돈이 어디서 들어오고 어디로 나갔나.

    ★원천을 `account_daily_performance` **하나로** 고정한다. 이 표는 입금·출금·
      배당·수수료·매수대금·매도대금을 증권사가 전부 **원화로** 주기 때문에
      통화를 섞을 일이 없다. trades(USD)와 합치는 순간 거래일 환율이 없어
      원화 환산이 거짓이 되는데, 여기서는 그 문제 자체가 생기지 않는다.
      → 수수료/세금 화면의 USD 금액과 여기 원화 금액은 **다른 원천**이다.
        둘을 환율로 이어 붙이지 않는다.

    ⚠️세 층을 한 숫자로 합치지 않는다. 성격이 다르다:
      · 외부 흐름(입금−출금) — 내 지갑 ↔ 계좌. **수익이 아니다.** 자산은 늘지만
        내 돈이 늘어난 게 아니라 위치만 바뀐 것이다.
      · 계좌가 만든 현금(배당−비용) — 시장이 어떻든 실제로 생기거나 사라진 현금.
      · 매매 회전(매수/매도) — 계좌 안에서 현금 ↔ 주식. 손익이 아니다.
      합치면 "이번 달 900만원 들어옴" 같은 말이 나오는데 그건 아무 뜻이 없다.

    ⚠️월말 자산 대조에서 남는 값을 **환차손익이라고 부르지 않는다**(_FX_NOTE).
      실측할 수 없는 것에 이름을 붙이면 그 순간 추정이 실측인 척하게 된다.
    """
    empty = MonthlyCashflowOut(
        rows=[], total_deposit_krw=Decimal("0"), total_withdrawal_krw=Decimal("0"),
        total_dividend_krw=Decimal("0"), total_cost_krw=Decimal("0"),
        net_cash_generated_krw=Decimal("0"), total_buy_krw=Decimal("0"),
        total_sell_krw=Decimal("0"), months_dividend_covered_cost=0, months_total=0,
        first_month=None, last_month=None, note=_FX_NOTE,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    since = inv.since(days)
    rows = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
            func.sum(AccountDailyPerformance.dividend_krw),
            func.sum(AccountDailyPerformance.commission_tax_krw),
            func.sum(AccountDailyPerformance.buy_amount_krw),
            func.sum(AccountDailyPerformance.sell_amount_krw),
            func.sum(AccountDailyPerformance.pnl_krw),
            # 자산 잔액은 **합치지 않는다** — 잔액이지 흐름이 아니다.
            # 계좌가 여럿이면 같은 날 잔액의 합이 맞으므로 그때만 합산한다.
            func.sum(AccountDailyPerformance.deposit_assets_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            AccountDailyPerformance.base_date >= since,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()
    if not rows:
        return empty

    zero = Decimal("0")
    #: 월 → [입금, 출금, 배당, 비용, 매수, 매도, 손익]
    flows: dict[str, list[Decimal]] = {}
    #: 월 → 그 달 **마지막 거래일**의 자산 잔액. 월말 잔액은 합이 아니라 끝값이다.
    closing: dict[str, Decimal | None] = {}

    for base_date, dep, wd, div, cost, buy, sell, pnl, assets in rows:
        key = f"{base_date.year:04d}-{base_date.month:02d}"
        bucket = flows.setdefault(key, [zero] * 7)
        for i, v in enumerate((dep, wd, div, cost, buy, sell, pnl)):
            bucket[i] += v or zero
        # 행이 날짜 오름차순이라 마지막으로 덮어쓴 값이 그 달의 끝값이 된다.
        closing[key] = assets

    months = sorted(flows)
    out: list[MonthlyCashflowRowOut] = []
    previous_close: Decimal | None = None

    for month in months:
        dep, wd, div, cost, buy, sell, pnl = flows[month]
        close = closing[month]
        net_flow = dep - wd
        # 첫 달은 월초 잔액을 모른다 — 0 으로 두면 "무에서 시작했다"는 거짓이 된다.
        unexplained = (
            close - previous_close - net_flow - pnl
            if close is not None and previous_close is not None
            else None
        )
        out.append(
            MonthlyCashflowRowOut(
                month=month,
                deposit_krw=dep,
                withdrawal_krw=wd,
                net_flow_krw=net_flow,
                dividend_krw=div,
                cost_krw=cost,
                net_cash_generated_krw=div - cost,
                buy_krw=buy,
                sell_krw=sell,
                pnl_krw=pnl,
                opening_assets_krw=previous_close,
                closing_assets_krw=close,
                unexplained_krw=unexplained,
            )
        )
        previous_close = close

    total_div = sum((r.dividend_krw for r in out), zero)
    total_cost = sum((r.cost_krw for r in out), zero)

    return MonthlyCashflowOut(
        # 최근이 위로 — 이번 달이 먼저 궁금하다.
        rows=list(reversed(out)),
        total_deposit_krw=sum((r.deposit_krw for r in out), zero),
        total_withdrawal_krw=sum((r.withdrawal_krw for r in out), zero),
        total_dividend_krw=total_div,
        total_cost_krw=total_cost,
        net_cash_generated_krw=total_div - total_cost,
        total_buy_krw=sum((r.buy_krw for r in out), zero),
        total_sell_krw=sum((r.sell_krw for r in out), zero),
        # ⚠️'덮었다'는 배당 > 비용인 달만 센다. 둘 다 0 인 달은 덮은 게 아니다.
        months_dividend_covered_cost=sum(
            1 for r in out if r.dividend_krw > r.cost_krw
        ),
        months_total=len(out),
        first_month=months[0],
        last_month=months[-1],
        note=_FX_NOTE,
    )


# ── 세금 (해외주식 양도소득 · 배당소득) ──────────────────────────────────────

# 해외주식 양도소득 기본공제(연 1회)와 세율(양도소득세 20% + 지방소득세 2%).
_TAX_DEDUCTION = Decimal("2500000")
_TAX_RATE = Decimal("0.22")
# 금융소득종합과세 기준. 이자+배당이 이 선을 넘으면 분리과세로 끝나지 않는다.
_COMPREHENSIVE_THRESHOLD = Decimal("20000000")

# ⚠️**숫자를 문구에 박아 두지 말 것.** 예전에 "현재 실현 내역 17건은 전부
#   해외주식입니다"라고 적어 두었는데, 한 번 더 팔면 그 순간 화면이 거짓말을
#   한다. 세는 것은 `_tax_notes()` 가 그때그때 한다.
_TAX_NOTES = [
    "이 화면은 **신고 자료가 아닙니다.** 세액이 맞는지는 증권사 양도소득 원장과"
    " 세무 전문가를 통해 확인하세요.",
    "양도차익을 **체결일 환율**로 계산했습니다(양도가액은 매도일, 취득가액은"
    " 매수일 환율). 세법이 쓰는 기준환율과 증권사가 준 체결 환율이 다를 수 있습니다.",
    "**환차손익을 양도차익에 포함했습니다.** 다른 화면에서는 주가 손익과 환차를"
    " 섞지 않지만, 세법의 양도차익은 원화 기준 양도가액 − 취득가액이라 환율 변동이"
    " 과세 대상 그 자체입니다.",
    "증권사가 준 값(주가손익 + 환차손익)과 체결일 환율로 계산한 값이 조금 다릅니다."
    " 둘 다 적어 두었으니 차이를 보고 판단하세요.",
    "배당이 **세전인지 세후인지 확인할 수 없습니다.** 키움에는 배당 전용 TR 이"
    " 없어 일별 **종목**수익률(usa21730)의 배당금액만 골라 쓰는데, 원천징수액은"
    " 그 응답에 없습니다. 미국 배당은 통상 15%가 현지에서 원천징수됩니다.",
    "손실은 **같은 해 안에서만** 통산되고 다음 해로 이월되지 않습니다.",
]


def _tax_notes(db: Session) -> list[str]:
    """한계 설명. **세는 것은 그때그때 센다.**

    ⚠️국내주식 문구에 건수를 박아 두었다가 다음 매도에 거짓이 될 뻔했다.
      실현 내역의 통화를 실제로 세서 적는다 — 원화 종목을 팔면 문구가 바뀐다.
    """
    rows = db.execute(
        select(RealizedPnl.currency, func.count())
        .group_by(RealizedPnl.currency)
    ).all()
    total = sum(count for _, count in rows)
    domestic = sum(count for currency, count in rows if currency == "KRW")

    if total == 0:
        tail = "(아직 실현 내역이 없습니다)."
    elif domestic == 0:
        tail = f"(현재 실현 내역 {total}건은 전부 해외주식입니다)."
    else:
        tail = (
            f"(실현 내역 {total}건 중 {domestic}건이 원화 종목이라 이 화면의"
            f" 합계에서 빠져 있습니다)."
        )
    return [
        *_TAX_NOTES,
        "국내주식은 대주주가 아니면 양도세 대상이 아니라 여기에 넣지 않았습니다 "
        + tail,
    ]


@router.get("/tax", response_model=TaxOut)
def get_tax(
    account_id: uuid.UUID | None = Query(default=None),
    year: int | None = Query(default=None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> TaxOut:
    """해외주식 양도소득세 · 배당소득 추정.

    ★취득가액을 `realized_pnl.buy_amount_krw` 로 잡지 않는다. 그 칸은 매수·매도를
      **같은 환율**로 환산한 값이다(실측: NVDA 매수 836.37달러 → 1,147,793원이면
      환율 1,372 인데, 실제 매수일 환율은 1,524.85 로 따로 들어와 있다).
      세법의 취득가액은 **매수일 환율**로 환산한 값이므로 체결 환율을 직접 쓴다.

    ★**환차를 양도차익에 더한다.** 다른 화면에서는 절대 섞지 말라고 한 두 값이다.
      모순이 아니라 질문이 다르다 — "종목 선택이 좋았나"는 주가만 봐야 하고,
      "세금을 얼마 내나"는 원화 기준 차익이라 환율이 과세 대상에 들어온다.
      실측 NVDA: 주가로 +50,182 벌었지만 환율로 −121,201 이라 양도차익은 −70,420.

    ⚠️세액이 0 이어도 "신고 안 해도 된다"고 말하지 않는다. 기본공제는 신고를
      통해 적용되는 것이고, 이 화면은 세무 판단을 할 수 있는 자리가 아니다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return TaxOut(years=[], current=None, notes=_tax_notes(db))

    rows = db.execute(
        select(RealizedPnl).where(RealizedPnl.account_id.in_(account_ids))
    ).scalars().all()
    dividends = db.execute(
        select(Dividend).where(Dividend.account_id.in_(account_ids))
    ).scalars().all()

    years = sorted(
        {r.sell_date.year for r in rows} | {d.pay_date.year for d in dividends},
        reverse=True,
    )
    if not years:
        return TaxOut(years=[], current=None, notes=_tax_notes(db))

    target = year if year in years else years[0]
    zero = Decimal("0")

    proceeds = cost_basis = expense = zero
    broker_gain = zero
    sales: list[TaxSaleOut] = []

    for r in rows:
        if r.sell_date.year != target:
            continue
        # 환율이 없으면 그 건은 **세금 계산에서 뺀다.** 오늘 환율로 메우면
        # 과세표준이 거짓이 된다(현재 17건 전부 환율이 들어와 있다).
        if r.buy_exchange_rate is None or r.sell_exchange_rate is None:
            continue
        sell_local = r.sell_amount_local or zero
        buy_local = r.buy_amount_local or zero
        cost_local = r.commission_tax_local or zero

        sale_proceeds = (sell_local * r.sell_exchange_rate).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        sale_cost = (buy_local * r.buy_exchange_rate).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        # 필요경비(수수료·세금)는 매도 시점에 나간 돈이므로 매도일 환율로 본다.
        sale_expense = (cost_local * r.sell_exchange_rate).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )

        proceeds += sale_proceeds
        cost_basis += sale_cost
        expense += sale_expense
        broker_gain += (r.pnl_krw or zero) + (r.fx_pnl_krw or zero)

        sales.append(
            TaxSaleOut(
                ticker=r.ticker,
                name=r.asset_name,
                sell_date=r.sell_date,
                quantity=r.quantity,
                proceeds_krw=sale_proceeds,
                cost_basis_krw=sale_cost,
                expense_krw=sale_expense,
                gain_krw=sale_proceeds - sale_cost - sale_expense,
            )
        )

    gain = proceeds - cost_basis - expense
    # ⚠️과세표준은 음수가 되지 않는다. 손실이면 0 이고, **다음 해로 이월되지 않는다.**
    taxable = max(gain - _TAX_DEDUCTION, zero)
    dividend_rows = [d for d in dividends if d.pay_date.year == target]

    return TaxOut(
        years=years,
        current=TaxYearOut(
            year=target,
            sale_count=len(sales),
            proceeds_krw=proceeds,
            cost_basis_krw=cost_basis,
            expense_krw=expense,
            gain_krw=gain,
            gain_krw_broker=broker_gain,
            method_diff_krw=gain - broker_gain,
            deduction_krw=_TAX_DEDUCTION,
            taxable_base_krw=taxable,
            tax_rate=_TAX_RATE,
            tax_krw=(taxable * _TAX_RATE).quantize(_MONEY, rounding=ROUND_HALF_UP),
            headroom_krw=_TAX_DEDUCTION - gain,
            dividend_krw=sum((d.amount_krw for d in dividend_rows), zero),
            dividend_count=len(dividend_rows),
            comprehensive_threshold_krw=_COMPREHENSIVE_THRESHOLD,
            # 손실이 큰 건이 위로 — 통산에 무엇이 들어갔는지가 먼저 궁금하다.
            sales=sorted(sales, key=lambda s: s.gain_krw),
        ),
        notes=_tax_notes(db),
    )


# ── 공시 (SEC EDGAR) ─────────────────────────────────────────────────────────

# 공시는 초 단위로 바뀌지 않고, 보유 종목 수만큼 SEC 를 두드려야 한다. 1시간 캐시.
FILINGS_TTL_SECONDS = 3600.0
FILINGS_WINDOW_DAYS = 180
FILINGS_INSIDER_WINDOW_DAYS = 90

_filings_lock = threading.Lock()
_filings_cache: dict[tuple[str, ...], tuple[float, FilingsOut]] = {}


def _build_filings(tickers: list[str], names: dict[str, str]) -> FilingsOut:
    results = filings_source.fetch_filings(
        tickers,
        days=FILINGS_WINDOW_DAYS,
        insider_days=FILINGS_INSIDER_WINDOW_DAYS,
    )

    rows: list[FilingOut] = []
    summary: list[FilingTickerOut] = []
    for r in results:
        for f in r.filings:
            rows.append(
                FilingOut(
                    ticker=f.ticker,
                    # 화면에 쓰는 이름은 우리 DB 의 한글 종목명이다. SEC 의 영문
                    # 법인명은 상세에서만 쓴다("NVIDIA CORP"보다 "엔비디아"가 읽힌다).
                    company=names.get(f.ticker) or f.company,
                    form=f.form,
                    form_label=f.form_label,
                    category=f.category,
                    filed_date=f.filed_date,
                    report_date=f.report_date,
                    items=f.items,
                    item_labels=f.item_labels,
                    url=f.url,
                )
            )
        summary.append(
            FilingTickerOut(
                ticker=r.ticker,
                name=names.get(r.ticker),
                cik=r.cik,
                ok=r.ok,
                reason=r.reason,
                filing_count=len(r.filings),
                insider_count=r.insider_count,
                truncated=r.truncated,
            )
        )

    rows.sort(key=lambda f: (f.filed_date, f.ticker), reverse=True)
    summary.sort(key=lambda t: (-t.filing_count, t.ticker))

    # ⚠️'실패'와 '대상 아님'을 같이 세지 않는다. covered 는 실제로 조회된 종목이다.
    covered = [t for t in summary if t.ok and t.cik is not None]
    not_covered = [t for t in summary if t.cik is None]

    return FilingsOut(
        filings=rows,
        tickers=summary,
        # 표시 순서를 서버가 정한다 — 읽을 순서대로다(실적 → 수시 → 지분 → 기타).
        categories=[
            filings_source.CATEGORY_RESULTS,
            filings_source.CATEGORY_EVENT,
            filings_source.CATEGORY_OWNERSHIP,
            filings_source.CATEGORY_OTHER,
        ],
        window_days=FILINGS_WINDOW_DAYS,
        insider_window_days=FILINGS_INSIDER_WINDOW_DAYS,
        insider_total=sum(t.insider_count for t in summary),
        covered_count=len(covered),
        not_covered_count=len(not_covered),
        # CIK 를 하나도 못 받았으면 SEC 자체가 안 된 것이다 — "공시 없음"이 아니다.
        source_ok=any(t.cik is not None for t in summary) if summary else False,
        user_agent_is_default=filings_source.user_agent()
        == filings_source._DEFAULT_UA,
    )


@router.get("/filings", response_model=FilingsOut)
def get_filings(
    account_id: uuid.UUID | None = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> FilingsOut:
    """보유 종목의 SEC 공시 — 무엇을 신고했나.

    ★**키가 필요 없다.** 다만 SEC 는 연락처가 담긴 User-Agent 를 요구한다
      (`www.sec.gov` 는 일반 UA 에 403). `.env` 의 `SEC_USER_AGENT` 로 바꿀 수
      있고, 안 넣으면 앱 이름만으로 요청한다 — 사용자 이메일을 말없이 보내지 않는다.

    ★**내부자 서식을 나열하지 않는다.** 실측(NVDA 최근 1001건): Form 4 가 556건,
      Form 144 가 247건으로 803건이 임원 서류다. 읽을 만한 건 8-K 62 · 10-Q 19 ·
      10-K 6 뿐이다. 그대로 쏟으면 중요한 공시가 묻히므로 **건수로만** 낸다.

    ⚠️ETF 는 SEC 개별 공시 대상이 **아니다**(신탁 단위로 낸다). 보유 17종목 중
      8개가 ETF 라, 이걸 "공시 없음"으로 적으면 거짓말이 된다.
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return FilingsOut(
            filings=[], tickers=[], categories=[], window_days=FILINGS_WINDOW_DAYS,
            insider_window_days=FILINGS_INSIDER_WINDOW_DAYS, insider_total=0,
            covered_count=0, not_covered_count=0, source_ok=False,
            user_agent_is_default=filings_source.user_agent()
            == filings_source._DEFAULT_UA,
        )

    holdings = db.execute(
        select(Asset.ticker, Asset.name)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .distinct()
    ).all()
    tickers = sorted({t for t, _ in holdings if t})
    names = {t: n for t, n in holdings if t}
    if not tickers:
        return FilingsOut(
            filings=[], tickers=[], categories=[], window_days=FILINGS_WINDOW_DAYS,
            insider_window_days=FILINGS_INSIDER_WINDOW_DAYS, insider_total=0,
            covered_count=0, not_covered_count=0, source_ok=False,
            user_agent_is_default=filings_source.user_agent()
            == filings_source._DEFAULT_UA,
        )

    key = tuple(tickers)
    now = time.monotonic()
    with _filings_lock:
        hit = _filings_cache.get(key)
        if not refresh and hit is not None and now - hit[0] < FILINGS_TTL_SECONDS:
            return hit[1]

    built = _build_filings(tickers, names)
    with _filings_lock:
        _filings_cache[key] = (time.monotonic(), built)
    return built


# ── 기간 리포트 ──────────────────────────────────────────────────────────────

_REPORT_NOTES = [
    "**기간별 평가 기여도는 내지 않았습니다.** 종목마다 '이번 달 얼마 기여했나'를"
    " 계산하려면 보유 종목의 일별 시계열이 필요한데, 스냅샷이 6건뿐입니다."
    " 만들면 그럴듯해 보이지만 근거가 없으므로 실현손익(증권사 실측)만 종목별로 냅니다.",
    "**신규/청산은 체결 기록으로 판단합니다.** 그 기간에 처음 산 종목을 신규,"
    " 기간 끝에 보유가 없는 종목을 청산으로 봅니다 — 기간 전에 샀다가 그 안에"
    " 추가 매수만 한 종목은 신규가 아닙니다.",
    "**거래대금은 원화입니다**(일별성과 원천). 수수료/세금 화면의 달러 금액과"
    " 출처가 달라 이어 붙이지 마세요.",
    "**'그 외'를 환차손익이라고 적지 않았습니다.** 일별성과의 환율 칸이 비어 있어"
    " 종목별로 실측할 수 없습니다(월별 현금흐름 화면과 같은 이유). 대신 그 기간의"
    " 환율 변동을 옆에 적어 두었으니 직접 견주시면 됩니다 — 방향은 매달 같지만"
    " 크기가 안 맞는 달이 있습니다(시작자산 대비 잔차 vs 환율: 7월 -6.44% vs"
    " -8.27%, 8월 -4.68% vs -3.80%, 9월 +0.52% vs +1.33%).",
    "**기간 수익률(TWR)의 기준일은 구간 첫 수익률 직전 날입니다.** 첫 수익률일을"
    " 기준으로 삼으면 그날치가 통째로 빠집니다 — 실제로 그 상태였고 2026년 9월이"
    " +11.33% 로 나왔습니다(같은 화면의 자산 변화는 순납입 0 에 +9.02%)."
    " 지금은 순납입이 0 인 달마다 두 값이 같은지 검사합니다.",
]


def _report_periods(first: date, last: date) -> list[ReportPeriodOut]:
    """고를 수 있는 기간. **데이터가 있는 구간만** 만든다."""
    out: list[ReportPeriodOut] = []

    def add(key: str, label: str, start: date, end: date) -> None:
        start = max(start, first)
        end = min(end, last)
        if start <= end:
            out.append(ReportPeriodOut(key=key, label=label, start_date=start, end_date=end))

    # 최근 달부터 12개월.
    year, month = last.year, last.month
    for _ in range(12):
        start = date(year, month, 1)
        end = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1))
        if end < first:
            break
        add(f"{year:04d}-{month:02d}", f"{year}년 {month}월", start, end)
        month -= 1
        if month == 0:
            year, month = year - 1, 12

    # 분기 — 최근 4개.
    q_year, q = last.year, (last.month - 1) // 3 + 1
    for _ in range(4):
        start = date(q_year, (q - 1) * 3 + 1, 1)
        end_month = q * 3
        end = date(q_year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
        if end < first:
            break
        add(f"{q_year:04d}-Q{q}", f"{q_year}년 {q}분기", start, end)
        q -= 1
        if q == 0:
            q_year, q = q_year - 1, 4

    # 연도.
    for y in range(last.year, first.year - 1, -1):
        add(f"{y:04d}", f"{y}년", date(y, 1, 1), date(y, 12, 31))

    return out


def _report_benchmarks(
    points: list[pa.DailyPoint],
    start: date,
    end: date,
    history: dict[str, object],
) -> tuple[Decimal | None, list[ReportBenchmarkOut], Decimal | None]:
    """기간 TWR · 벤치마크 대비 · 그 기간의 환율 변동.

    ★환율 변동을 같이 내보내는 이유: 화면의 **'그 외'** 칸을 사용자가 스스로
      판단할 수 있게 하려는 것이다. 그 칸은 잔차라 무엇이라고 단정하지 않는데,
      옆에 환율 변동이 있으면 "이게 환율이구나"를 눈으로 확인할 수 있다.
      실측(시작자산 대비 잔차 vs 환율): 7월 −6.44% vs −8.27%, 8월 −4.68% vs
      −3.80%, 9월 +0.52% vs +1.33%. 방향은 매달 같지만 **크기는 안 맞는 달도
      있다**(8월). 그래서 여전히 '환차손익'이라 부르지 않는다.

    ⚠️구간 시작으로 **다시 기준을 잡는다**(rebase). 전체 구간 지수를 그대로
      잘라 쓰면 1개월 수익률이 누적값 차이로 나온다.
    ⚠️양쪽에 다 있는 날짜만 쓴다. 한쪽을 앞으로 채우면 없는 날의 움직임이 생긴다.

    ⚠️기준일은 **구간 첫 수익률 직전 날**이다. 첫 수익률일의 지수를 기준으로
      삼으면 그날 수익률이 통째로 빠진다 — 실측(2026-09): 자산이 순납입 0 으로
      34,904,085 → 38,052,092(+9.02%) 였는데 이 칸은 +11.33% 를 적고 있었다.
      같은 화면의 '자산 변화' 칸과 어긋나는데도 둘 다 그럴듯해 보였다.
      벤치마크 화면에서 같은 실수를 고쳤고(`base_index`), 여기도 같은 실수였다.
    """
    all_returns = pa.daily_returns(points)
    returns = [r for r in all_returns if start <= r.base_date <= end]
    if len(returns) < 2:
        return None, [], None

    mine = {r.base_date: r.index for r in returns}
    prior = [p.base_date for p in points if p.base_date < returns[0].base_date]
    if prior:
        mine[prior[-1]] = pa.base_index(returns)
    fx = history.get(_FX_SYMBOL)

    usable = sorted(
        d for d in mine
        if all(
            (series := history.get(symbol)) is not None
            and series.close_on_or_before(d) is not None
            for symbol, _ in _BENCHMARKS
        )
        and (fx is None or fx.close_on_or_before(d) is not None)
    )
    cum = pa.cumulative_return(returns)
    twr = cum.quantize(_RATIO, rounding=ROUND_HALF_UP) if cum is not None else None

    # 환율 변동은 **TWR 과 같은 창**에서 잰다 — 기준일부터 마지막 날까지.
    fx_base_day = min(mine)
    fx_change: Decimal | None = None
    if fx is not None:
        a = fx.close_on_or_before(returns[-1].base_date)
        b = fx.close_on_or_before(fx_base_day)
        if a is not None and b is not None and b != 0:
            fx_change = (a / b - Decimal("1")).quantize(
                _RATIO, rounding=ROUND_HALF_UP
            )

    if len(usable) < 2:
        return twr, [], fx_change

    def level(symbol: str, when: date) -> Decimal | None:
        series = history.get(symbol)
        value = series.close_on_or_before(when) if series else None
        rate = fx.close_on_or_before(when) if fx else None
        return None if value is None or rate is None else value * rate

    b_start, b_end = usable[0], usable[-1]
    # ⚠️벤치마크와 비교할 때는 내 수익률도 **같은 날짜 범위**로 다시 잰다.
    #   지수에 없는 날을 포함해 버리면 비교가 어긋난다.
    mine_change = (
        (mine[b_end] / mine[b_start] - Decimal("1")).quantize(
            _RATIO, rounding=ROUND_HALF_UP
        )
        if mine.get(b_start) and mine.get(b_end)
        else None
    )

    out: list[ReportBenchmarkOut] = []
    for symbol, name in _BENCHMARKS:
        a, b = level(symbol, b_end), level(symbol, b_start)
        ret = (
            (a / b - Decimal("1")).quantize(_RATIO, rounding=ROUND_HALF_UP)
            if a is not None and b is not None and b != 0
            else None
        )
        out.append(
            ReportBenchmarkOut(
                name=name,
                return_krw=ret,
                excess=(
                    mine_change - ret
                    if mine_change is not None and ret is not None
                    else None
                ),
            )
        )
    return twr, out, fx_change


@router.get("/report", response_model=ReportOut)
def get_report(
    account_id: uuid.UUID | None = Query(default=None),
    period: str | None = Query(default=None, description="2026-09 · 2026-Q3 · 2026"),
    db: Session = Depends(get_db),
) -> ReportOut:
    """기간 리포트 — 그 기간에 무슨 일이 있었나.

    ★다른 화면과 겹치지 않는 부분은 **기간을 고른다**는 것이다. 성과 분석은
      전체를, 월별 현금흐름은 흐름만 본다. 여기는 한 달/분기/연도를 잘라
      자산 변화 · 수익률 · 매매 · 실현손익 · 신규/청산을 한 장에 모은다.

    ⚠️**기간별 평가 기여도를 만들지 않는다.** 종목별로 "이번 달 얼마 기여했나"를
      내려면 보유 종목의 일별 시계열이 있어야 하는데 스냅샷이 6건뿐이다(실측).
      그럴듯한 숫자를 만드는 대신 실현손익만 종목별로 낸다.
    """
    empty = ReportOut(
        periods=[], period=None, opening_assets_krw=None, closing_assets_krw=None,
        net_flow_krw=Decimal("0"), pnl_krw=Decimal("0"), unexplained_krw=None,
        twr=None, benchmarks=[], fx_change_ratio=None,
        residual=ResidualBreakdownOut(
            total_krw=None, fx_estimate_krw=None, dividend_krw=Decimal('0'),
            cost_krw=Decimal('0'), leftover_krw=None, fx_days=0, fx_missing_days=0,
        ),
        buy_count=0, sell_count=0,
        turnover_krw=Decimal("0"), cost_krw=Decimal("0"), dividend_krw=Decimal("0"),
        realized=[], realized_total_krw=Decimal("0"), changes=[],
        best_day=None, best_day_krw=None, worst_day=None, worst_day_krw=None,
        trading_days=0, notes=_REPORT_NOTES,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    daily = db.execute(
        select(
            AccountDailyPerformance.base_date,
            func.sum(AccountDailyPerformance.deposit_assets_krw),
            func.sum(AccountDailyPerformance.deposit_krw),
            func.sum(AccountDailyPerformance.withdrawal_krw),
            func.sum(AccountDailyPerformance.pnl_krw),
            func.sum(AccountDailyPerformance.dividend_krw),
            func.sum(AccountDailyPerformance.commission_tax_krw),
            func.sum(AccountDailyPerformance.buy_amount_krw),
            func.sum(AccountDailyPerformance.sell_amount_krw),
            # '그 외' 분해용. 환율 영향의 모형이 **전일 주식평가액** × 환율 변동률이다.
            func.sum(AccountDailyPerformance.stock_value_krw),
        )
        .where(
            AccountDailyPerformance.account_id.in_(account_ids),
            # ⚠️투자 기간 밖은 다루지 않는다 — 기간 선택지도 그 안에서만 만든다.
            AccountDailyPerformance.base_date >= inv.INVESTMENT_START,
        )
        .group_by(AccountDailyPerformance.base_date)
        .order_by(AccountDailyPerformance.base_date)
    ).all()
    if not daily:
        return empty

    periods = _report_periods(daily[0][0], daily[-1][0])
    if not periods:
        return empty
    chosen = next((p for p in periods if p.key == period), periods[0])

    zero = Decimal("0")
    opening: Decimal | None = None
    closing: Decimal | None = None
    net_flow = pnl = dividend = cost = buy = sell = zero
    best = worst = None
    best_v = worst_v = None
    trading_days = 0

    for row in daily:
        d, assets, dep, wd, day_pnl, div, day_cost, day_buy, day_sell, _stock = row
        if d < chosen.start_date:
            # 기간 시작 **직전** 자산이 월초 잔액이다. 0 으로 두면 "무에서
            # 시작했다"는 거짓이 된다.
            opening = assets if assets is not None else opening
            continue
        if d > chosen.end_date:
            break
        if opening is None:
            # ⚠️기간 앞에 아무 날도 없을 때(첫 달·연도) **첫날을 기준선으로 쓴다.**
            #   예전에는 opening 을 None 으로 둬서 자산 분해가 통째로 비었다 —
            #   '그 외'가 안 보이는데 분해 팝업에는 숫자가 있는 모양이었다.
            #   0 으로 두는 것도 거짓이다(2026-06-04 마감 자산은 36,899,965 인데
            #   그날 입금은 7,840,153 뿐이라 "무에서 시작"이 성립하지 않는다).
            #   투자 시작일 규칙과도 같다 — 첫날 입금은 시작 잔고에 포함한다.
            opening = assets
            continue
        trading_days += 1
        closing = assets if assets is not None else closing
        net_flow += (dep or zero) - (wd or zero)
        pnl += day_pnl or zero
        dividend += div or zero
        cost += day_cost or zero
        buy += day_buy or zero
        sell += day_sell or zero
        v = day_pnl or zero
        if best_v is None or v > best_v:
            best_v, best = v, d
        if worst_v is None or v < worst_v:
            worst_v, worst = v, d

    points, _ = pa.reconcile_flows(
        [
            pa.DailyPoint(base_date=d, assets_krw=a, deposit_krw=dep, withdrawal_krw=wd)
            for d, a, dep, wd, *_ in daily
        ]
    )
    history = fetch_history([s for s, _ in _BENCHMARKS] + [_FX_SYMBOL], range_="2y")
    twr, benchmarks, fx_change = _report_benchmarks(
        points, chosen.start_date, chosen.end_date, history
    )

    # ── '그 외' 분해 ────────────────────────────────────────────────────────
    # ★잔차를 그냥 '그 외'로 두면 사용자가 판단할 근거가 없다. 환율(추정)·
    #   배당(실측)·수수료(실측)로 쪼개고 남는 것까지 그대로 내놓는다.
    #   실측 전체 구간: 잔차 -3,121,093 = 환율 -3,043,025 + 배당 121,611
    #   - 수수료 128,189 + 남는 것 -71,490(잔차의 2.3%).
    fx_series = history.get(_FX_SYMBOL)

    def _rate_on(when: date) -> Decimal | None:
        value = fx_series.close_on_or_before(when) if fx_series else None
        return None if value is None else Decimal(str(value))

    # 기간 **직전** 하루를 기준선으로 함께 넣는다 — 첫날 변동을 놓치지 않으려고.
    before = [r for r in daily if r[0] < chosen.start_date]
    window = ([before[-1]] if before else []) + [
        r for r in daily if chosen.start_date <= r[0] <= chosen.end_date
    ]
    breakdown = rsd.decompose(
        [
            rsd.Day(
                base_date=r[0], assets_krw=r[1], stock_value_krw=r[9], pnl_krw=r[4],
                deposit_krw=r[2], withdrawal_krw=r[3],
                dividend_krw=r[5], commission_tax_krw=r[6],
            )
            for r in window
        ],
        _rate_on,
    )

    # ── 실현손익 (종목별, 증권사 실측) ──────────────────────────────────────
    realized_rows = db.execute(
        select(RealizedPnl).where(
            RealizedPnl.account_id.in_(account_ids),
            RealizedPnl.sell_date >= chosen.start_date,
            RealizedPnl.sell_date <= chosen.end_date,
        )
    ).scalars().all()
    by_ticker: dict[str, list] = {}
    for r in realized_rows:
        acc = by_ticker.setdefault(r.ticker, [r.asset_name, zero, zero, 0])
        acc[1] += r.pnl_krw or zero
        acc[2] += r.fx_pnl_krw or zero
        acc[3] += 1

    realized = sorted(
        [
            ReportRealizedOut(
                ticker=t, name=v[0], pnl_krw=v[1], fx_pnl_krw=v[2], sell_count=v[3]
            )
            for t, v in by_ticker.items()
        ],
        key=lambda x: x.pnl_krw,
        reverse=True,
    )

    # ── 신규 편입 / 전량 청산 ───────────────────────────────────────────────
    # ⚠️체결 기록으로 판단한다. 기간 전에 이미 있던 종목은 신규가 아니다.
    before = {
        t for (t,) in db.execute(
            select(Trade.ticker).where(
                Trade.account_id.in_(account_ids),
                Trade.trade_date < chosen.start_date,
            ).distinct()
        ).all()
    }
    held_now = {
        t for (t,) in db.execute(
            select(Asset.ticker)
            .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
            .where(CurrentPosition.account_id.in_(account_ids))
            .distinct()
        ).all()
    }
    in_period = db.execute(
        select(Trade).where(
            Trade.account_id.in_(account_ids),
            Trade.trade_date >= chosen.start_date,
            Trade.trade_date <= chosen.end_date,
        )
    ).scalars().all()

    buy_count = sum(1 for t in in_period if t.side == "BUY")
    sell_count = sum(1 for t in in_period if t.side == "SELL")

    grouped: dict[str, list] = {}
    for t in in_period:
        g = grouped.setdefault(t.ticker, [t.asset_name, t.trade_date, t.trade_date, 0])
        g[1] = min(g[1], t.trade_date)
        g[2] = max(g[2], t.trade_date)
        g[3] += 1

    changes: list[ReportPositionChangeOut] = []
    for ticker, (name, first_d, last_d, count) in grouped.items():
        if ticker not in before:
            kind = "NEW"
        elif ticker not in held_now:
            # ⚠️'지금 없다'는 것만 안다. 이 기간 이후에 팔았을 수도 있으므로
            #   기간 안에 매도가 있었을 때만 청산으로 적는다.
            if not any(t.ticker == ticker and t.side == "SELL" for t in in_period):
                continue
            kind = "CLOSED"
        else:
            continue
        changes.append(
            ReportPositionChangeOut(
                ticker=ticker, name=name, kind=kind,
                first_date=first_d, last_date=last_d, trade_count=count,
            )
        )
    changes.sort(key=lambda c: (c.kind, c.first_date))

    return ReportOut(
        periods=periods,
        period=chosen,
        opening_assets_krw=opening,
        closing_assets_krw=closing,
        net_flow_krw=net_flow,
        pnl_krw=pnl,
        unexplained_krw=(
            closing - opening - net_flow - pnl
            if closing is not None and opening is not None
            else None
        ),
        twr=twr,
        benchmarks=benchmarks,
        fx_change_ratio=fx_change,
        residual=ResidualBreakdownOut(
            total_krw=breakdown.total_krw,
            fx_estimate_krw=breakdown.fx_estimate_krw,
            dividend_krw=breakdown.dividend_krw,
            cost_krw=breakdown.cost_krw,
            leftover_krw=breakdown.leftover_krw,
            fx_days=breakdown.fx_days,
            fx_missing_days=breakdown.fx_missing_days,
        ),
        buy_count=buy_count,
        sell_count=sell_count,
        turnover_krw=buy + sell,
        cost_krw=cost,
        dividend_krw=dividend,
        realized=realized,
        realized_total_krw=sum((r.pnl_krw for r in realized), zero),
        changes=changes,
        best_day=best, best_day_krw=best_v,
        worst_day=worst, worst_day_krw=worst_v,
        trading_days=trading_days,
        notes=_REPORT_NOTES,
    )


# ── 보유 종목 뉴스 ───────────────────────────────────────────────────────────

NEWS_TTL_SECONDS = 1800.0
NEWS_WINDOW_DAYS = 7

_news_lock = threading.Lock()
_news_cache: dict[tuple[str, ...], tuple[float, NewsOut]] = {}

_NEWS_NOTES = [
    "검색어를 **영문 법인명**으로 만듭니다. 실측(10종목 각 100건에서 제목 언급"
    " 비율): 법인명 97.3% · 티커 96.1% · 한국어 82.8%(최저 32%)."
    " 한국어는 소형주에서 무너져서 쓰지 않았습니다.",
    "**제목에 종목이 언급된 기사만** 남깁니다. 걸러낸 건수를 아래에 적어 두었으니"
    " 너무 많이 걸러졌다면 그 종목은 검색어가 맞지 않는 것입니다.",
    "**ETF 는 넣지 않았습니다.** 실측 제목 언급 비율이 EETH 15% · TSL 33% ·"
    " GLD 43% 였고, TSL 검색은 아예 다른 회사 기사를 물어 왔습니다. ETF 의 관련"
    " 뉴스는 기초자산 뉴스인데 그걸 그 ETF 뉴스라고 붙이면 우리가 만들어 낸"
    " 편집 판단이 됩니다.",
    "같은 기사가 여러 매체로 중복돼 오므로 제목으로 한 번 더 걸러 냅니다.",
    "구글 뉴스 피드는 **개인 피드리더에서 개인적·비상업적 용도**로 제공됩니다"
    " — 이 대시보드는 본인 비공개 화면이라 그 용도에 맞습니다.",
]


@router.get("/news", response_model=NewsOut)
def get_news(
    account_id: uuid.UUID | None = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> NewsOut:
    """보유 종목 뉴스 — 내 포지션에 걸린 일.

    ★키가 필요 없다(구글 뉴스 RSS). 검색어는 **영문 법인명**으로 만드는데,
      그 이름은 공시 화면이 이미 받는 SEC company_tickers 에서 가져온다 —
      같은 사실을 두 군데서 따로 관리하지 않는다.

    ⚠️ETF 는 대상이 아니다. 공시 화면과 같은 판단 기준(SEC 에 CIK 가 있는가)을
      쓰므로, GLD 처럼 상품신탁이라 SEC 에 등록된 ETF 는 자동으로 포함된다.
    """
    empty = NewsOut(
        articles=[], tickers=[], window_days=NEWS_WINDOW_DAYS,
        covered_count=0, not_covered_count=0, filtered_total=0,
        source_ok=False, notes=_NEWS_NOTES,
    )
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return empty

    holdings = db.execute(
        select(Asset.ticker, Asset.name)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .where(CurrentPosition.account_id.in_(account_ids))
        .distinct()
    ).all()
    tickers = sorted({t for t, _ in holdings if t})
    names = {t: n for t, n in holdings if t}
    if not tickers:
        return empty

    key = tuple(tickers)
    now = time.monotonic()
    with _news_lock:
        hit = _news_cache.get(key)
        if not refresh and hit is not None and now - hit[0] < NEWS_TTL_SECONDS:
            return hit[1]

    cik_map = filings_source.fetch_cik_map()
    # ⚠️SEC 목록을 못 받았으면 **티커로 대신 검색하지 않는다.** 정확도가 떨어지는
    #   검색을 조용히 섞으면 화면이 왜 이상한지 알 수 없게 된다.
    if not cik_map:
        built = NewsOut(
            articles=[], tickers=[], window_days=NEWS_WINDOW_DAYS,
            covered_count=0, not_covered_count=len(tickers), filtered_total=0,
            source_ok=False, notes=_NEWS_NOTES,
        )
        with _news_lock:
            _news_cache[key] = (time.monotonic(), built)
        return built

    covered = [(t, cik_map[t][1]) for t in tickers if t in cik_map]
    uncovered = [t for t in tickers if t not in cik_map]

    results = news_source.fetch_news(covered, days=NEWS_WINDOW_DAYS) if covered else []

    # ⚠️한 기사가 여러 종목에 걸리면 **합친다.** 두 줄로 늘어놓으면 화면이
    #   고장 난 것처럼 보이고(실측: 같은 알파벳 기사 2건), 하나를 지우면 다른
    #   종목의 뉴스가 사라진다.
    merged: dict[str, NewsArticleOut] = {}
    summary: list[NewsTickerOut] = []
    for r in results:
        for a in r.articles:
            key = news_source.title_key(a.title)
            label = names.get(a.ticker) or a.company or a.ticker
            existing = merged.get(key)
            if existing is not None:
                if a.ticker not in existing.tickers:
                    existing.tickers.append(a.ticker)
                    existing.companies.append(label)
                continue
            merged[key] = NewsArticleOut(
                tickers=[a.ticker],
                # 화면에 쓰는 이름은 우리 DB 의 한글 종목명이다.
                companies=[label],
                title=a.title,
                publisher=a.publisher,
                published_at=a.published_at,
                url=a.url,
            )
        summary.append(
            NewsTickerOut(
                ticker=r.ticker, name=names.get(r.ticker), company=r.company,
                covered=True, ok=r.ok, reason=r.reason,
                article_count=len(r.articles), filtered_out=r.filtered_out,
            )
        )
    for t in uncovered:
        summary.append(
            NewsTickerOut(
                ticker=t, name=names.get(t), company=None, covered=False, ok=True,
                reason="개별 기업 뉴스 대상이 아닙니다 (ETF 등)",
                article_count=0, filtered_out=0,
            )
        )

    # 날짜를 모르는 기사는 **뒤로** 보낸다. 지금 시각으로 채우면 최신인 척한다.
    articles = list(merged.values())
    articles.sort(
        key=lambda a: (a.published_at is not None, a.published_at), reverse=True
    )
    summary.sort(key=lambda t: (-t.article_count, t.ticker))

    built = NewsOut(
        articles=articles,
        tickers=summary,
        window_days=NEWS_WINDOW_DAYS,
        covered_count=sum(1 for t in summary if t.covered),
        not_covered_count=sum(1 for t in summary if not t.covered),
        filtered_total=sum(t.filtered_out for t in summary),
        source_ok=any(t.ok and t.covered for t in summary),
        notes=_NEWS_NOTES,
    )
    with _news_lock:
        _news_cache[key] = (time.monotonic(), built)
    return built


# ── 리밸런싱 ─────────────────────────────────────────────────────────────────

#: 예수금을 종목처럼 한 줄로 넣을 때 쓰는 가짜 티커.
CASH_TICKER = "__CASH__"

_REBALANCE_NOTES = [
    "**비중의 분모는 총자산입니다 — 주식 평가액 + 예수금.** 예수금이 많으면"
    " 종목 비중이 그만큼 낮게 나옵니다. 예수금도 한 줄로 표시해 비중 합이"
    " 100% 가 되게 했습니다.",
    "**주수는 0 방향으로 내립니다.** 반올림하면 목표를 넘겨 사거나 넘겨 팝니다."
    " 주수로 못 맞춘 나머지는 '잔여'로 적어 둡니다.",
    "**밴드 안의 차이는 거래하지 않습니다.** 실측 거래비용이 거래대금의 0.250%"
    " 라, 작은 어긋남을 맞추려다 비용이 교정 효과보다 커집니다. 밴드는 화면에서"
    " 바꿀 수 있습니다.",
    "**목표가 없는 보유 종목을 0% 로 치지 않습니다.** 그렇게 하면 '아직 목표를"
    " 안 적은 종목을 전부 팔아라'가 되는데, 그건 시키신 적 없는 말입니다."
    " 따로 모아 보여 주기만 합니다.",
    "**목표 합이 100% 가 아니어도 고치지 않습니다.** 조용히 정규화하면 적으신"
    " 목표와 화면이 쓰는 목표가 달라집니다 — 차이만 알려 드립니다.",
    "목표를 적지 않은 보유가 자리를 차지하고 있으면 **살 돈이 안 나옵니다.**"
    " 목표합과 '목표 없음' 비중을 더해 100% 를 넘으면 그만큼 팔 것을 먼저"
    " 정해야 합니다 — 화면이 부족액을 알려 드립니다.",
    "여기는 **계획**만 냅니다. 주문을 내지 않습니다.",
]


def _leverage_seed() -> tuple[dict, str]:
    """ETF 배수 시드. 섹터 노출 시드와 같은 파일에 있다."""
    import importlib.util

    seed_path = (
        Path(__file__).resolve().parents[4]
        / "database" / "seeds" / "etf_exposure.py"
    )
    spec = importlib.util.spec_from_file_location("_etf_exposure_seed", seed_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_etf_exposure_seed"] = module
    spec.loader.exec_module(module)
    return module.ETF_LEVERAGE, module.LEVERAGE_NOTE


def _character(plan: rb.Plan) -> PortfolioCharacterOut:
    """목표를 정하기 전에 보는 '지금 어떤 모양인가'.

    ★비중만 보면 SOXL 이 20% 지만, 3배 상품이라 **하루 움직임으로는 60%** 를
      들고 있는 것과 같다. 목표를 정할 때 그 사실이 같이 보여야 한다.
    """
    leverage_map, note = _leverage_seed()
    holdings = [
        pc.Holding(ticker=line.ticker, name=line.name, weight=line.current_weight)
        for line in (plan.lines + plan.untargeted)
        if line.current_weight is not None
    ]
    character = pc.build(holdings, leverage_map, cash_ticker=CASH_TICKER)
    return PortfolioCharacterOut(
        leverage=[
            LeveragePositionOut(
                ticker=p.ticker, name=p.name, weight=p.weight,
                multiplier=p.multiplier, effective_weight=p.effective_weight,
                source=p.source, disputed=p.disputed,
            )
            for p in character.leverage
        ],
        leveraged_weight=character.leveraged_weight,
        effective_exposure=character.effective_exposure,
        top1_ticker=character.top1_ticker,
        top1_weight=character.top1_weight,
        top3_weight=character.top3_weight,
        herfindahl=character.herfindahl,
        effective_count=character.effective_count,
        cash_weight=character.cash_weight,
        leverage_note=note,
    )


def _to_line(line: rb.Line) -> RebalanceLineOut:
    return RebalanceLineOut(
        ticker=line.ticker, name=line.name, quantity=line.quantity,
        current_value_krw=line.current_value_krw, current_weight=line.current_weight,
        target_weight=line.target_weight, target_value_krw=line.target_value_krw,
        drift=line.drift, delta_value_krw=line.delta_value_krw,
        price_krw=line.price_krw, delta_shares=line.delta_shares,
        residual_krw=line.residual_krw, action=line.action,
        within_band=line.within_band, est_cost_krw=line.est_cost_krw, memo=line.memo,
    )


def _rebalance_plan(
    db: Session, account_ids: list[uuid.UUID], band: Decimal
) -> RebalanceOut:
    rows = db.execute(
        select(Asset.ticker, Asset.name, CurrentPosition.quantity,
               CurrentPosition.market_value_krw)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .where(CurrentPosition.account_id.in_(account_ids))
    ).all() if account_ids else []
    positions = [
        rb.Position(ticker=t, name=n, quantity=q, market_value_krw=v)
        for t, n, q, v in rows
    ]

    cash = None
    if account_ids:
        balances = db.execute(
            select(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
        ).scalars().all()
        cash = _sum([_cash_krw(b) for b in balances])

    # ★2026-09-22 사용자 지정: **자산에 예수금을 포함한다.** 비중의 분모도 같은
    #   총자산이다 — 예수금이 많으면 종목 비중이 그만큼 낮게 나온다.
    #   ⚠️현금을 **종목처럼** 한 줄로 넣는다. 분모에만 더하고 목록에서 빼면
    #     비중 합이 100% 가 안 되고, 사용자는 그걸 버그로 읽는다.
    if inv.CASH_IN_ASSETS and cash is not None and cash > 0:
        positions.append(
            rb.Position(
                ticker=CASH_TICKER, name="예수금",
                # 현금은 주수가 없다 — 수량 0 이면 가격이 None 이 되어
                # "몇 주 사고팔라"는 말을 하지 않는다(그게 맞다).
                quantity=Decimal("0"), market_value_krw=cash,
            )
        )
    targets = [
        rb.Target(
            ticker=r.ticker, name=r.asset_name, weight=r.target_weight, memo=r.memo
        )
        for r in db.execute(
            select(RebalanceTarget).order_by(
                RebalanceTarget.target_weight.desc(), RebalanceTarget.ticker
            )
        ).scalars().all()
    ]
    plan = rb.build_plan(positions, targets, band=band)

    cash = None
    if account_ids:
        balances = db.execute(
            select(AccountBalance).where(AccountBalance.account_id.in_(account_ids))
        ).scalars().all()
        cash = _sum([_cash_krw(b) for b in balances])

    # ⚠️목표합만 보면 안 된다. 목표를 적지 않은 보유가 자리를 차지하고 있으면
    #   "팔 것을 정하지 않은 채 사라"는 계획이 나온다(실측: 목표 80% + 목표없음
    #   51% = 131% → 매수 860만인데 예수금 133만).
    untargeted_weight = sum(
        (line.current_weight for line in plan.untargeted if line.current_weight),
        Decimal("0"),
    )
    net_buy = plan.buy_krw - plan.sell_krw
    shortfall = (
        max(net_buy - cash, Decimal("0")) if cash is not None else None
    )

    return RebalanceOut(
        lines=[_to_line(line) for line in plan.lines],
        untargeted=[_to_line(line) for line in plan.untargeted],
        base_value_krw=plan.base_value_krw,
        # 예수금은 분모에 넣지 않지만, 매수 여력을 보려면 알아야 한다.
        cash_krw=cash,
        target_sum=plan.target_sum, target_gap=plan.target_gap, band=plan.band,
        untargeted_weight=untargeted_weight.quantize(_RATIO, rounding=ROUND_HALF_UP),
        net_buy_krw=net_buy,
        shortfall_krw=shortfall,
        buy_krw=plan.buy_krw, sell_krw=plan.sell_krw, est_cost_krw=plan.est_cost_krw,
        cost_rate=rb.MEASURED_COST_RATE, trade_count=plan.trade_count,
        character=_character(plan),
        notes=_REBALANCE_NOTES,
    )


@router.get("/rebalance", response_model=RebalanceOut)
def get_rebalance(
    account_id: uuid.UUID | None = Query(default=None),
    band: Decimal = Query(default=Decimal("0.01"), ge=0, le=1),
    db: Session = Depends(get_db),
) -> RebalanceOut:
    """리밸런싱 — 목표 비중과 지금 보유의 차이를 **주수**로 바꾼다.

    ★알림이 "SOXL 비중 21.32% > 20%" 를 잡아 준다. 여기는 그 다음 질문에
      답한다 — **그래서 몇 주를 팔아야 하나.**

    ⚠️분모는 주식 평가액이다(예수금 제외) — 섹터/자산 배분 화면과 같은 분모여야
      두 화면의 비중이 같은 말을 한다.
    """
    return _rebalance_plan(db, _active_account_ids(db, account_id), band)


@router.put("/rebalance/targets/{ticker}", response_model=RebalanceOut)
def upsert_rebalance_target(
    ticker: str,
    payload: RebalanceTargetIn,
    account_id: uuid.UUID | None = Query(default=None),
    band: Decimal = Query(default=Decimal("0.01"), ge=0, le=1),
    db: Session = Depends(get_db),
) -> RebalanceOut:
    """종목 하나의 목표 비중을 세우거나 고친다.

    ★관심종목 화면에서 "사게 되면 몇 %"를 적을 때 쓴다. 전체를 갈아끼우는
      `PUT /rebalance/targets` 와 달리 **다른 목표를 건드리지 않는다** —
      관심종목에서 한 줄 고치려다 세워 둔 목표가 통째로 날아가면 안 된다.

    ⚠️합이 100% 를 넘어도 막지 않는다(전체 저장과 같은 이유). 화면이 말한다.
    """
    key = (ticker or "").strip().upper()
    if not key:
        raise AppError(status_code=400, code="ticker_required", message="종목이 필요합니다.")
    if payload.target_weight < 0 or payload.target_weight > 1:
        raise AppError(
            status_code=400, code="weight_out_of_range",
            message="비중이 0~100% 를 벗어났습니다.",
        )

    existing = db.execute(
        select(RebalanceTarget).where(RebalanceTarget.ticker == key)
    ).scalar_one_or_none()
    name = db.execute(
        select(Asset.name).where(Asset.ticker == key)
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            RebalanceTarget(
                id=uuid.uuid4(), ticker=key, asset_name=name,
                target_weight=payload.target_weight,
                memo=(payload.memo or "").strip() or None,
            )
        )
    else:
        existing.target_weight = payload.target_weight
        if payload.memo is not None:
            existing.memo = payload.memo.strip() or None
        if name and not existing.asset_name:
            existing.asset_name = name
    db.commit()
    return _rebalance_plan(db, _active_account_ids(db, account_id), band)


@router.delete("/rebalance/targets/{ticker}", response_model=RebalanceOut)
def delete_rebalance_target(
    ticker: str,
    account_id: uuid.UUID | None = Query(default=None),
    band: Decimal = Query(default=Decimal("0.01"), ge=0, le=1),
    db: Session = Depends(get_db),
) -> RebalanceOut:
    """종목 하나의 목표를 지운다. 나머지는 그대로 둔다."""
    key = (ticker or "").strip().upper()
    db.execute(delete(RebalanceTarget).where(RebalanceTarget.ticker == key))
    db.commit()
    return _rebalance_plan(db, _active_account_ids(db, account_id), band)


@router.put("/rebalance/targets", response_model=RebalanceOut)
def put_rebalance_targets(
    payload: list[RebalanceTargetIn],
    account_id: uuid.UUID | None = Query(default=None),
    band: Decimal = Query(default=Decimal("0.01"), ge=0, le=1),
    db: Session = Depends(get_db),
) -> RebalanceOut:
    """목표 비중을 **통째로** 갈아끼운다.

    ★한 건씩 고치지 않고 전체를 바꾼다 — 비중은 서로 묶여 있어서, 한 줄만
      바꾸는 중간 상태가 저장되면 합이 이상한 채로 남는다.

    ⚠️합이 100% 가 아니어도 **거부하지 않는다.** 목표를 옮기는 중간 단계를
      저장할 수 없게 되기 때문이다. 대신 화면이 차이를 말한다.
    """
    seen: set[str] = set()
    cleaned: list[tuple[str, Decimal, str | None]] = []
    for item in payload:
        ticker = (item.ticker or "").strip().upper()
        if not ticker:
            continue
        if ticker in seen:
            raise AppError(
                status_code=400, code="duplicate_ticker",
                message=f"{ticker} 가 두 번 들어 있습니다.",
            )
        if item.target_weight < 0 or item.target_weight > 1:
            raise AppError(
                status_code=400, code="weight_out_of_range",
                message=f"{ticker} 의 비중이 0~100% 를 벗어났습니다.",
            )
        seen.add(ticker)
        cleaned.append((ticker, item.target_weight, (item.memo or "").strip() or None))

    names = {
        t: n
        for t, n in db.execute(
            select(Asset.ticker, Asset.name).where(Asset.ticker.in_(list(seen)))
        ).all()
    } if seen else {}

    db.execute(delete(RebalanceTarget))
    for order, (ticker, weight, memo) in enumerate(cleaned):
        db.add(
            RebalanceTarget(
                id=uuid.uuid4(), ticker=ticker, asset_name=names.get(ticker),
                target_weight=weight, memo=memo, sort_order=order,
            )
        )
    db.commit()
    return _rebalance_plan(db, _active_account_ids(db, account_id), band)
