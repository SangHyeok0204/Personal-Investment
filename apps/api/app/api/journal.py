"""매매일지 — 진입 근거 · 청산 근거 · 복기.

★일반 메모장과 다른 점은 **결과를 붙여 준다**는 것이다. "왜 샀는지" 옆에
  "그래서 어떻게 됐는지"가 없으면 복기가 안 된다. 각 메모마다:
    · 그 날 전후의 실제 체결(±3일)
    · 지금 보유 중이면 현재 평가손익
    · 이미 청산했으면 실현손익
  을 찾아 함께 내보낸다.

⚠️결과를 못 찾으면 **비워서 보낸다.** 0 으로 채우면 "본전"으로 읽힌다.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.models import Asset, CurrentPosition, JournalEntry, RealizedPnl, Trade
from app.schemas import (
    JournalCreateIn,
    JournalEntryOut,
    JournalListOut,
    JournalTradeOut,
    JournalUpdateIn,
)

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])

VALID_KINDS = ("ENTRY", "EXIT", "REVIEW", "IDEA")

# 메모 날짜 전후로 체결을 찾는 범위. 판단한 날과 실제 체결일이 며칠 어긋나는 건
# 흔하다(주문을 걸어 두고 나중에 체결되는 경우).
_TRADE_WINDOW_DAYS = 3


def _normalize(ticker: str | None) -> str | None:
    if ticker is None:
        return None
    cleaned = ticker.strip().upper()
    return cleaned or None


def _outcomes(db: Session, tickers: set[str]) -> tuple[dict, dict]:
    """티커별 (현재 평가손익, 누적 실현손익). 없으면 키가 없다."""
    if not tickers:
        return {}, {}

    held = {
        ticker: (pnl, rate)
        for ticker, pnl, rate in db.execute(
            select(
                Asset.ticker,
                CurrentPosition.unrealized_pnl_krw,
                CurrentPosition.unrealized_return,
            )
            .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
            .where(Asset.ticker.in_(tickers))
        ).all()
    }
    realized = {
        ticker: total
        for ticker, total in db.execute(
            select(RealizedPnl.ticker, func.sum(RealizedPnl.pnl_krw))
            .where(RealizedPnl.ticker.in_(tickers))
            .group_by(RealizedPnl.ticker)
        ).all()
    }
    return held, realized


def _build(entries: list[JournalEntry], db: Session) -> JournalListOut:
    tickers = {e.ticker for e in entries if e.ticker}
    held, realized = _outcomes(db, tickers)

    # 메모 날짜 ±3일 안의 체결을 한 번에 가져와 파이썬에서 짝짓는다.
    # 메모마다 쿼리를 돌리면 N+1 이 된다.
    trades_by_ticker: dict[str, list[Trade]] = {}
    if tickers:
        rows = db.execute(
            select(Trade).where(Trade.ticker.in_(tickers)).order_by(Trade.trade_date)
        ).scalars()
        for trade in rows:
            trades_by_ticker.setdefault(trade.ticker, []).append(trade)

    out: list[JournalEntryOut] = []
    for entry in entries:
        near: list[JournalTradeOut] = []
        if entry.ticker:
            window = timedelta(days=_TRADE_WINDOW_DAYS)
            for trade in trades_by_ticker.get(entry.ticker, []):
                if abs((trade.trade_date - entry.entry_date).days) <= window.days:
                    near.append(
                        JournalTradeOut(
                            trade_date=trade.trade_date,
                            side=trade.side,
                            quantity=trade.quantity,
                            price=trade.price,
                            amount_local=trade.amount_local,
                            currency=trade.currency,
                        )
                    )

        position = held.get(entry.ticker) if entry.ticker else None
        out.append(
            JournalEntryOut(
                id=entry.id,
                ticker=entry.ticker,
                asset_name=entry.asset_name,
                entry_date=entry.entry_date,
                kind=entry.kind,
                title=entry.title,
                body=entry.body,
                conviction=entry.conviction,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                nearby_trades=near,
                held=position is not None,
                # ⚠️결과가 없으면 None. 0 으로 채우면 "본전"으로 읽힌다.
                unrealized_pnl_krw=position[0] if position else None,
                unrealized_return=position[1] if position else None,
                realized_pnl_krw=realized.get(entry.ticker) if entry.ticker else None,
            )
        )

    return JournalListOut(items=out, total=len(out), kinds=list(VALID_KINDS))


def _ordered(db: Session, ticker: str | None, kind: str | None) -> list[JournalEntry]:
    statement = select(JournalEntry)
    if ticker:
        statement = statement.where(JournalEntry.ticker == _normalize(ticker))
    if kind:
        statement = statement.where(JournalEntry.kind == kind.upper())
    # 최근 판단이 위로. 같은 날이면 나중에 쓴 것이 위로.
    statement = statement.order_by(
        JournalEntry.entry_date.desc(), JournalEntry.created_at.desc()
    )
    return list(db.execute(statement).scalars())


@router.get("", response_model=JournalListOut)
def list_journal(
    ticker: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> JournalListOut:
    """일지 목록 + 각 메모의 결과(체결·평가손익·실현손익)."""
    return _build(_ordered(db, ticker, kind), db)


def _validate(kind: str, title: str, conviction: int | None) -> None:
    if kind.upper() not in VALID_KINDS:
        raise AppError(
            400, "VALIDATION_ERROR", "알 수 없는 구분입니다.", {"allowed": list(VALID_KINDS)}
        )
    if not title.strip():
        raise AppError(400, "VALIDATION_ERROR", "제목을 입력하세요.")
    if conviction is not None and not 1 <= conviction <= 5:
        raise AppError(400, "VALIDATION_ERROR", "확신도는 1~5 사이여야 합니다.")


@router.post("", response_model=JournalListOut, status_code=201)
def add_journal(payload: JournalCreateIn, db: Session = Depends(get_db)) -> JournalListOut:
    _validate(payload.kind, payload.title, payload.conviction)
    ticker = _normalize(payload.ticker)

    # 종목명을 안 줘도 보유/거래 이력에서 찾아 채운다 — 목록이 코드만 보이면 읽기 나쁘다.
    name = payload.asset_name
    if ticker and not name:
        name = db.execute(
            select(Asset.name).where(Asset.ticker == ticker).limit(1)
        ).scalar() or db.execute(
            select(Trade.asset_name).where(Trade.ticker == ticker).limit(1)
        ).scalar()

    db.add(
        JournalEntry(
            ticker=ticker,
            asset_name=name,
            entry_date=payload.entry_date,
            kind=payload.kind.upper(),
            title=payload.title.strip(),
            body=payload.body,
            conviction=payload.conviction,
        )
    )
    db.commit()
    return _build(_ordered(db, None, None), db)


@router.patch("/{entry_id}", response_model=JournalListOut)
def update_journal(
    entry_id: uuid.UUID, payload: JournalUpdateIn, db: Session = Depends(get_db)
) -> JournalListOut:
    """⚠️`exclude_unset` — 제목만 고쳐도 본문이 null 로 덮이면 안 된다."""
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise AppError(404, "NOT_FOUND", "일지를 찾을 수 없습니다.")

    changes = payload.model_dump(exclude_unset=True)
    _validate(
        changes.get("kind", entry.kind),
        changes.get("title", entry.title),
        changes.get("conviction", entry.conviction),
    )
    for field, value in changes.items():
        setattr(entry, field, value.upper() if field == "kind" else value)
    db.commit()
    return _build(_ordered(db, None, None), db)


@router.delete("/{entry_id}", response_model=JournalListOut)
def remove_journal(entry_id: uuid.UUID, db: Session = Depends(get_db)) -> JournalListOut:
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise AppError(404, "NOT_FOUND", "일지를 찾을 수 없습니다.")
    db.delete(entry)
    db.commit()
    return _build(_ordered(db, None, None), db)


@router.get("/untracked", response_model=list[str])
def list_untracked(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[str]:
    """일지가 **하나도 없는 보유 종목**.

    이 화면의 쓸모는 "무엇을 안 적었는가"를 드러내는 데 있다. 비어 있는 자리를
    보여주지 않으면 일지는 결국 안 쓰게 된다.
    """
    written = {
        ticker
        for (ticker,) in db.execute(
            select(JournalEntry.ticker).where(JournalEntry.ticker.isnot(None)).distinct()
        ).all()
    }
    held = db.execute(
        select(Asset.ticker)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .order_by(CurrentPosition.market_value_krw.desc().nullslast())
    ).all()
    return [t for (t,) in held if t not in written][:limit]
