import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, Select, case, cast, func, nullslast, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    Account,
    AccountBalance,
    Asset,
    Broker,
    BrokerageConnection,
    CurrentPosition,
    Job,
    PortfolioSnapshot,
    PositionSnapshot,
)
from app.schemas import (
    AccountPortfolioOut,
    AccountSummaryOut,
    AssetClassBreakdownOut,
    CashBalanceOut,
    ConnectionBriefOut,
    HistoryPointOut,
    MarketBreakdownOut,
    PortfolioHistoryOut,
    PortfolioOverviewOut,
    PortfolioSummaryOut,
    PositionListOut,
    PositionOut,
)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])
accounts_router = APIRouter(prefix="/api/v1/accounts", tags=["portfolio"])

SYNC_JOB_TYPE = "SYNC_KIWOOM_PORTFOLIO"
_ACTIVE_STATUSES = ("PENDING", "RUNNING")
ALLOWED_COUNTRIES = {"KR", "US"}
ALLOWED_CURRENCIES = {"KRW", "USD"}

# Donut classes. The first four are assets.asset_type values; CASH comes from
# account_balances. Order is fixed — the legend always shows five slots.
SECURITY_ASSET_CLASSES = ("STOCK", "BOND", "DERIVATIVE", "OTHER")
CASH_ASSET_CLASS = "CASH"


def _credentials_configured() -> bool:
    return bool(settings.KIWOOM_APP_KEY and settings.KIWOOM_SECRET_KEY)


def _krw_rate(currency: str | None, exchange_rate) -> float | None:
    """Effective FX for KRW conversion. Domestic (KRW) defaults to 1.0 when the
    worker left the rate null; a null rate on a foreign currency stays unknown."""
    if exchange_rate is not None:
        return float(exchange_rate)
    if currency == "KRW":
        return 1.0
    return None


def _position_query() -> Select:
    """Position rows joined to asset + broker; keys match PositionOut fields."""
    return (
        select(
            CurrentPosition.account_id,
            CurrentPosition.asset_id,
            Broker.code.label("broker"),
            Asset.country,
            Asset.market,
            Asset.ticker,
            Asset.name.label("asset_name"),
            Asset.asset_type,
            Asset.currency,
            CurrentPosition.quantity,
            CurrentPosition.available_quantity,
            CurrentPosition.average_purchase_price,
            CurrentPosition.purchase_amount_local,
            CurrentPosition.current_price,
            CurrentPosition.market_value_local,
            CurrentPosition.unrealized_pnl_local,
            CurrentPosition.unrealized_return,
            CurrentPosition.exchange_rate,
            CurrentPosition.market_value_krw,
            CurrentPosition.unrealized_pnl_krw,
            CurrentPosition.as_of,
            CurrentPosition.source_job_id,
        )
        .join(Account, CurrentPosition.account_id == Account.id)
        .join(Asset, CurrentPosition.asset_id == Asset.id)
        .join(Broker, Account.broker_id == Broker.id)
    )


def _positions_from(db: Session, stmt: Select) -> list[PositionOut]:
    rows = db.execute(
        stmt.order_by(nullslast(CurrentPosition.market_value_krw.desc()))
    ).all()
    return [PositionOut(**dict(row._mapping)) for row in rows]


def _cash_out(balance: AccountBalance) -> CashBalanceOut:
    return CashBalanceOut(
        account_id=balance.account_id,
        currency=balance.currency,
        cash_balance=balance.cash_balance,
        available_cash=balance.available_cash,
        exchange_rate=balance.exchange_rate,
        cash_krw=_cash_krw_value(balance),
        # DB column keeps its name; the API field says what the value actually is.
        estimated_total_assets_krw=balance.total_evaluation_amount_krw,
        as_of=balance.as_of,
    )


def _cash_krw_value(balance: AccountBalance) -> float | None:
    """KRW value of ONE cash row: cash_balance x the stored FX rate (KRW -> 1.0).

    None when the rate is unknown — FX is never guessed (contract §10).

    Deliberately does NOT read ``total_evaluation_amount_krw``: that column is
    Kiwoom's 추정예탁자산, an ACCOUNT-level total (cash + securities). Summing it as
    cash double-counts the securities and doubles 총자산.
    """
    rate = _krw_rate(balance.currency, balance.exchange_rate)
    if balance.cash_balance is None or rate is None:
        return None
    return float(balance.cash_balance) * rate


def _cash_krw(balances: list[AccountBalance]) -> float:
    """Total cash in KRW. Rows with an unknown FX rate contribute 0."""
    return sum((_cash_krw_value(b) or 0.0 for b in balances), 0.0)


def _purchase_krw(positions: list[PositionOut]) -> float:
    """Real purchase total in KRW: the stored per-position purchase amount converted
    with the stored Kiwoom FX rate.

    Never ``securities - pnl`` — Kiwoom's pnl is net of fees/taxes, so that
    derivation silently overstated the total (by 15,248 KRW against a live account).
    """
    total = 0.0
    for position in positions:
        rate = _krw_rate(position.currency, position.exchange_rate)
        if position.purchase_amount_local is not None and rate is not None:
            total += position.purchase_amount_local * rate
    return total


def _asset_class_breakdown(
    positions: list[PositionOut],
    cash_value_krw: float,
    total_assets_krw: float,
) -> list[AssetClassBreakdownOut]:
    """Fixed five-slot donut: STOCK, BOND, DERIVATIVE, OTHER, CASH.

    Empty classes are still returned with 0 so the legend never changes shape.
    An unclassified position (null/unknown asset_type) falls into OTHER rather than
    being dropped, so the slices always add up to securities + cash = total assets.
    """
    values = {asset_class: 0.0 for asset_class in SECURITY_ASSET_CLASSES}
    counts = {asset_class: 0 for asset_class in SECURITY_ASSET_CLASSES}
    for position in positions:
        asset_class = position.asset_type if position.asset_type in values else "OTHER"
        if position.market_value_krw is not None:
            values[asset_class] += position.market_value_krw
        counts[asset_class] += 1

    def weight_pct(value: float) -> float:
        if not total_assets_krw:
            return 0.0
        return round(value / total_assets_krw * 100.0, 1)

    rows = [
        AssetClassBreakdownOut(
            asset_class=asset_class,
            value_krw=values[asset_class],
            weight_pct=weight_pct(values[asset_class]),
            position_count=counts[asset_class],
        )
        for asset_class in SECURITY_ASSET_CLASSES
    ]
    rows.append(
        AssetClassBreakdownOut(
            asset_class=CASH_ASSET_CLASS,
            value_krw=cash_value_krw,
            weight_pct=weight_pct(cash_value_krw),
            position_count=None,
        )
    )
    return rows


def _sync_status(db: Session) -> str:
    active = db.execute(
        select(Job.id).where(
            Job.job_type == SYNC_JOB_TYPE, Job.status.in_(_ACTIVE_STATUSES)
        )
    ).first()
    if active is not None:
        return "RUNNING"
    last = db.execute(
        select(Job)
        .where(Job.job_type == SYNC_JOB_TYPE)
        .order_by(Job.created_at.desc())
    ).scalars().first()
    return last.status if last is not None else "NEVER_SYNCED"


@router.get("/overview", response_model=PortfolioOverviewOut)
def overview(db: Session = Depends(get_db)) -> PortfolioOverviewOut:
    positions = _positions_from(db, _position_query())
    accounts = db.execute(select(Account)).scalars().all()
    balances = db.execute(select(AccountBalance)).scalars().all()

    securities_value_krw = sum(
        p.market_value_krw for p in positions if p.market_value_krw is not None
    )
    total_unrealized_pnl_krw = sum(
        p.unrealized_pnl_krw for p in positions if p.unrealized_pnl_krw is not None
    )
    total_purchase_amount_krw = _purchase_krw(positions)
    cash_value_krw = _cash_krw(balances)
    total_assets_krw = securities_value_krw + cash_value_krw
    unrealized_return_pct = (
        total_unrealized_pnl_krw / total_purchase_amount_krw * 100.0
        if total_purchase_amount_krw
        else None
    )

    # Per-account totals: securities from positions + cash from balances.
    sec_by_account: dict[uuid.UUID, float] = {}
    for p in positions:
        if p.market_value_krw is not None:
            sec_by_account[p.account_id] = (
                sec_by_account.get(p.account_id, 0.0) + p.market_value_krw
            )
    cash_by_account: dict[uuid.UUID, float] = {}
    for b in balances:
        cash_by_account[b.account_id] = cash_by_account.get(b.account_id, 0.0) + (
            _cash_krw_value(b) or 0.0
        )

    account_items = [
        AccountSummaryOut(
            id=a.id,
            account_name=a.account_name,
            account_number_masked=a.account_number_masked,
            account_type=a.account_type,
            base_currency=a.base_currency,
            total_assets_krw=sec_by_account.get(a.id, 0.0) + cash_by_account.get(a.id, 0.0),
            last_synced_at=a.last_synced_at,
        )
        for a in accounts
    ]

    breakdown: dict[str | None, list] = {}
    for p in positions:
        entry = breakdown.setdefault(p.country, [0.0, 0])
        if p.market_value_krw is not None:
            entry[0] += p.market_value_krw
        entry[1] += 1
    market_breakdown = [
        MarketBreakdownOut(country=country, securities_value_krw=value, position_count=count)
        for country, (value, count) in sorted(
            breakdown.items(), key=lambda kv: kv[1][0], reverse=True
        )
    ]

    synced_times = [a.last_synced_at for a in accounts if a.last_synced_at is not None]
    last_synced_at = max(synced_times) if synced_times else None

    connection = db.execute(
        select(BrokerageConnection).order_by(BrokerageConnection.created_at.asc())
    ).scalars().first()
    connection_brief = (
        ConnectionBriefOut(
            id=connection.id,
            status=connection.status,
            credentials_configured=_credentials_configured(),
            last_error=connection.last_error,
        )
        if connection is not None
        else None
    )

    summary = PortfolioSummaryOut(
        total_assets_krw=total_assets_krw,
        securities_value_krw=securities_value_krw,
        cash_value_krw=cash_value_krw,
        total_purchase_amount_krw=total_purchase_amount_krw,
        total_unrealized_pnl_krw=total_unrealized_pnl_krw,
        unrealized_return_pct=unrealized_return_pct,
        position_count=len(positions),
        account_count=len(accounts),
    )

    return PortfolioOverviewOut(
        summary=summary,
        accounts=account_items,
        positions=positions,
        cash_balances=[_cash_out(b) for b in balances],
        market_breakdown=market_breakdown,
        asset_class_breakdown=_asset_class_breakdown(
            positions, cash_value_krw, total_assets_krw
        ),
        last_synced_at=last_synced_at,
        sync_status=_sync_status(db),
        connection=connection_brief,
    )


@router.get("/positions", response_model=PositionListOut)
def list_positions(
    account_id: str | None = Query(default=None),
    country: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PositionListOut:
    stmt = _position_query()

    if account_id is not None:
        try:
            parsed = uuid.UUID(account_id)
        except ValueError:
            raise AppError(
                400, "VALIDATION_ERROR", "Malformed account_id.", {"account_id": account_id}
            )
        stmt = stmt.where(CurrentPosition.account_id == parsed)

    if country is not None:
        if country not in ALLOWED_COUNTRIES:
            raise AppError(
                400,
                "VALIDATION_ERROR",
                "Invalid country filter.",
                {"allowed": sorted(ALLOWED_COUNTRIES)},
            )
        stmt = stmt.where(Asset.country == country)

    if currency is not None:
        if currency not in ALLOWED_CURRENCIES:
            raise AppError(
                400,
                "VALIDATION_ERROR",
                "Invalid currency filter.",
                {"allowed": sorted(ALLOWED_CURRENCIES)},
            )
        stmt = stmt.where(Asset.currency == currency)

    items = _positions_from(db, stmt)
    return PositionListOut(items=items, total=len(items))


def _kst_day(column):
    """KST calendar day of a UTC timestamp.

    The DB stores UTC, but the day boundary that matters is Asia/Seoul
    (UTC 15:00 = KST midnight the next day).
    """
    return cast(func.timezone("Asia/Seoul", column), Date)


def _parse_exclude_tickers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]


@router.get("/history", response_model=PortfolioHistoryOut)
def portfolio_history(
    days: int = Query(90, ge=1, le=730),
    exclude_tickers: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PortfolioHistoryOut:
    """Daily total-assets series from portfolio_snapshots.

    One point per KST day — that day's LAST sync — summed across accounts. With
    ``exclude_tickers`` the securities figures are recomputed from position_snapshots
    so a dashboard that hides those tickers shows a chart matching its own cards;
    otherwise the cards and the chart would quietly disagree.
    """
    excluded = _parse_exclude_tickers(exclude_tickers)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    kst_day = _kst_day(PortfolioSnapshot.snapshot_at)
    ranked = (
        select(
            PortfolioSnapshot.id.label("id"),
            PortfolioSnapshot.snapshot_at.label("snapshot_at"),
            PortfolioSnapshot.cash_value_krw.label("cash_value_krw"),
            PortfolioSnapshot.securities_value_krw.label("securities_value_krw"),
            PortfolioSnapshot.total_assets_krw.label("total_assets_krw"),
            PortfolioSnapshot.total_purchase_amount_krw.label("total_purchase_amount_krw"),
            PortfolioSnapshot.total_unrealized_pnl_krw.label("total_unrealized_pnl_krw"),
            kst_day.label("kst_day"),
            func.row_number()
            .over(
                partition_by=(PortfolioSnapshot.account_id, kst_day),
                order_by=(
                    PortfolioSnapshot.snapshot_at.desc(),
                    PortfolioSnapshot.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(PortfolioSnapshot.snapshot_at >= since)
        .subquery()
    )
    # Each account's last snapshot of each day: syncing six times a day still yields
    # a single point.
    chosen = select(ranked).where(ranked.c.rn == 1).subquery()

    # Span of EVERY snapshot in the window (not just the chosen ones) — the UI shows
    # "최초 기록" from this while the series is still accumulating.
    first_snapshot_at, last_snapshot_at = db.execute(
        select(
            func.min(PortfolioSnapshot.snapshot_at),
            func.max(PortfolioSnapshot.snapshot_at),
        ).where(PortfolioSnapshot.snapshot_at >= since)
    ).one()

    rows = db.execute(
        select(
            chosen.c.kst_day,
            func.max(chosen.c.snapshot_at).label("snapshot_at"),
            func.coalesce(func.sum(chosen.c.cash_value_krw), 0).label("cash"),
            func.coalesce(func.sum(chosen.c.securities_value_krw), 0).label("securities"),
            func.coalesce(func.sum(chosen.c.total_assets_krw), 0).label("total"),
            func.coalesce(func.sum(chosen.c.total_purchase_amount_krw), 0).label("purchase"),
            func.coalesce(func.sum(chosen.c.total_unrealized_pnl_krw), 0).label("pnl"),
        )
        .group_by(chosen.c.kst_day)
        .order_by(chosen.c.kst_day.asc())
    ).all()

    recomputed: dict = {}
    if excluded:
        # position_snapshots has no purchase-amount column, so purchase is derived as
        # quantity x average_purchase_price x exchange_rate. The rate is stored on the
        # row (Kiwoom's own), so this converts rather than invents FX; KRW -> 1.0.
        rate = func.coalesce(
            PositionSnapshot.exchange_rate,
            case((PositionSnapshot.currency == "KRW", 1.0)),
        )
        recomputed = {
            row.kst_day: (float(row.securities), float(row.purchase), float(row.pnl))
            for row in db.execute(
                select(
                    chosen.c.kst_day,
                    func.coalesce(func.sum(PositionSnapshot.market_value_krw), 0).label(
                        "securities"
                    ),
                    func.coalesce(
                        func.sum(
                            PositionSnapshot.quantity
                            * PositionSnapshot.average_purchase_price
                            * rate
                        ),
                        0,
                    ).label("purchase"),
                    func.coalesce(func.sum(PositionSnapshot.unrealized_pnl_krw), 0).label(
                        "pnl"
                    ),
                )
                .select_from(chosen)
                .join(
                    PositionSnapshot,
                    PositionSnapshot.portfolio_snapshot_id == chosen.c.id,
                )
                .join(Asset, Asset.id == PositionSnapshot.asset_id)
                .where(Asset.ticker.notin_(excluded))
                .group_by(chosen.c.kst_day)
            ).all()
        }

    points: list[HistoryPointOut] = []
    for row in rows:
        cash = float(row.cash)
        if excluded:
            # A ticker filter never touches cash — only securities are recomputed.
            securities, purchase, pnl = recomputed.get(row.kst_day, (0.0, 0.0, 0.0))
            total = securities + cash
        else:
            securities = float(row.securities)
            purchase = float(row.purchase)
            pnl = float(row.pnl)
            total = float(row.total)
        points.append(
            HistoryPointOut(
                date=row.kst_day,
                snapshot_at=row.snapshot_at,
                total_assets_krw=total,
                securities_value_krw=securities,
                cash_value_krw=cash,
                total_purchase_amount_krw=purchase,
                total_unrealized_pnl_krw=pnl,
                unrealized_return_pct=(pnl / purchase * 100.0) if purchase else None,
            )
        )

    return PortfolioHistoryOut(
        points=points,
        distinct_days=len(points),
        first_snapshot_at=first_snapshot_at,
        last_snapshot_at=last_snapshot_at,
        excluded_tickers=excluded,
    )


@accounts_router.get("/{account_id}/portfolio", response_model=AccountPortfolioOut)
def account_portfolio(
    account_id: str, db: Session = Depends(get_db)
) -> AccountPortfolioOut:
    try:
        parsed = uuid.UUID(account_id)
    except ValueError:
        raise AppError(
            400, "VALIDATION_ERROR", "Malformed account id.", {"account_id": account_id}
        )

    account = db.get(Account, parsed)
    if account is None:
        raise AppError(
            404, "ACCOUNT_NOT_FOUND", "Account not found.", {"account_id": account_id}
        )

    positions = _positions_from(
        db, _position_query().where(CurrentPosition.account_id == parsed)
    )
    balances = db.execute(
        select(AccountBalance).where(AccountBalance.account_id == parsed)
    ).scalars().all()

    securities = sum(p.market_value_krw for p in positions if p.market_value_krw is not None)
    total_assets_krw = securities + _cash_krw(balances)

    account_summary = AccountSummaryOut(
        id=account.id,
        account_name=account.account_name,
        account_number_masked=account.account_number_masked,
        account_type=account.account_type,
        base_currency=account.base_currency,
        total_assets_krw=total_assets_krw,
        last_synced_at=account.last_synced_at,
    )
    return AccountPortfolioOut(
        account=account_summary,
        positions=positions,
        cash_balances=[_cash_out(b) for b in balances],
        last_synced_at=account.last_synced_at,
    )
