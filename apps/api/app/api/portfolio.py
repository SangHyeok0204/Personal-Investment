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
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    Account,
    AccountBalance,
    Asset,
    Broker,
    BrokerageConnection,
    CurrentPosition,
    PortfolioSnapshot,
)
from app.schemas import (
    AccountListOut,
    AccountOut,
    ConnectionOut,
    HoldingListOut,
    HoldingOut,
    PortfolioHistoryOut,
    PortfolioSummaryOut,
    SnapshotPointOut,
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
