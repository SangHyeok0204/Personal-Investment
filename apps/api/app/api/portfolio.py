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
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.core import performance_analytics as pa
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    Account,
    AccountBalance,
    Asset,
    Broker,
    BrokerageConnection,
    CurrentPosition,
    PortfolioSnapshot,
    Trade,
    AccountDailyPerformance,
    RealizedPnl,
    Dividend,
)
from app.schemas import (
    AccountListOut,
    CashByCurrencyOut,
    ContributionOut,
    DrawdownPointOut,
    MonthlyReturnOut,
    FlowShiftOut,
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

_ALLOCATION_DIMENSIONS = {
    # AI/Tech 밸류체인 3단계 — 사용자가 준 분류표(alembic 0010).
    # 전통 섹터(sector)와 **다른 축**이라 같이 제공한다.
    "tech_l1": (Asset.tech_l1, "미분류"),
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

    total = _sum([value for _, value, _, _ in rows])
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

    since = date.today() - timedelta(days=days)
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
    """
    account_ids = _active_account_ids(db, account_id)
    if not account_ids:
        return PerformanceSeriesOut(
            items=[], first_date=None, last_date=None,
            start_assets_krw=None, end_assets_krw=None,
            net_deposit_krw=None, gain_krw=None,
        )

    since = date.today() - timedelta(days=days)
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

    return PerformanceSeriesOut(
        items=items,
        first_date=items[0].base_date,
        last_date=items[-1].base_date,
        start_assets_krw=start_assets,
        end_assets_krw=end_assets,
        net_deposit_krw=net_deposit,
        gain_krw=gain.quantize(_MONEY, rounding=ROUND_HALF_UP) if gain is not None else None,
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
        )

    since = date.today() - timedelta(days=days)
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

    return RealizedPnlListOut(
        items=items,
        total=len(items),
        pnl_krw=_sum([i.pnl_krw for i in items]),
        fx_pnl_krw=_sum([i.fx_pnl_krw for i in items]),
        win_count=wins,
        loss_count=losses,
        first_sell_date=min((i.sell_date for i in items), default=None),
        last_sell_date=max((i.sell_date for i in items), default=None),
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

    since = date.today() - timedelta(days=days)
    conditions = [Dividend.account_id.in_(account_ids), Dividend.pay_date >= since]

    rows = db.execute(
        select(Dividend, Asset.sector)
        .outerjoin(Asset, Asset.id == Dividend.asset_id)
        .where(*conditions)
        .order_by(Dividend.pay_date.desc(), Dividend.ticker)
    ).all()

    items = [
        DividendOut(
            id=row.id,
            pay_date=row.pay_date,
            ticker=row.ticker,
            asset_name=row.asset_name,
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
                ticker=t, asset_name=name, amount_krw=amount, count=count
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

    since = date.today() - timedelta(days=days)
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
    평가수익률과 정확히 같아진다 — 화면에서 바로 검산할 수 있다.

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
                _ratio(position.unrealized_pnl_krw / total_purchase)
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
