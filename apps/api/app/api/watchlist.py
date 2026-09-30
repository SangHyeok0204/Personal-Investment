"""관심종목 보드 — 담아 둔 종목 + 실시간 시세.

사용자가 처음부터 말한 것: "toss api 활용해서 관심 있는 종목 모니터하는 것".
시세 소스(토스/야후)가 붙은 뒤에야 의미가 생겨 이제 만든다.

★보유 종목을 저장하지 않는다. `current_positions` 가 정본이고, 복제하면 판 뒤에도
  관심종목에 남거나 둘이 어긋난다. 대신 조회할 때 **보유 여부만 표시**한다.

★목표가·손절가까지의 거리를 서버에서 계산해 내보낸다. 화면마다 계산하면 반올림이
  갈려 같은 종목이 화면마다 다르게 보인다.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import quote_cache
from app.core.naming import display_names, lookup_name
from app.core.errors import AppError
from app.db.session import get_db
from app.models import RebalanceTarget, Asset, CurrentPosition, WatchlistItem
from app.schemas import (
    WatchlistCreateIn,
    WatchlistItemOut,
    WatchlistListOut,
    WatchlistUpdateIn,
)

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])

_RATIO = Decimal("0.000001")


def _ratio(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_RATIO, rounding=ROUND_HALF_UP)


def _normalize(ticker: str) -> str:
    """티커는 대문자·공백 제거로 통일한다.

    ⚠️이걸 안 하면 "nvda" 와 "NVDA" 가 서로 다른 행이 되어 unique 제약을 우회한다.
    """
    return ticker.strip().upper()


def _held_tickers(db: Session) -> set[str]:
    return {
        ticker
        for (ticker,) in db.execute(
            select(Asset.ticker)
            .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
            .distinct()
        ).all()
    }


def _build(items: list[WatchlistItem], db: Session) -> WatchlistListOut:
    held = _held_tickers(db)
    # ★관심종목과 리밸런싱 목표를 **한 화면에서** 본다. 따로 두면 "사고 싶다"와
    #   "사면 몇 %"가 갈려, 목표를 세워 놓고도 관심종목에서 안 보인다.
    targets = {
        t: w
        for t, w in db.execute(
            select(RebalanceTarget.ticker, RebalanceTarget.target_weight)
        ).all()
    }
    quotes, fetched = quote_cache.get_quotes(
        [i.ticker for i in items], with_range=True
    )

    out: list[WatchlistItemOut] = []
    missing: list[str] = []
    for item in items:
        quote = quotes.get(item.ticker)
        if quote is None:
            missing.append(item.ticker)

        price = quote.price if quote else None
        out.append(
            WatchlistItemOut(
                id=item.id,
                ticker=item.ticker,
                # 시세 소스가 이름을 주지 않으므로 저장해 둔 이름을 쓴다.
                asset_name=item.asset_name,
                memo=item.memo,
                target_price=item.target_price,
                stop_price=item.stop_price,
                sort_order=item.sort_order,
                held=item.ticker in held,
                price=price,
                currency=quote.currency if quote else None,
                previous_close=quote.previous_close if quote else None,
                change=quote.change if quote else None,
                change_rate=_ratio(quote.change_rate) if quote else None,
                fifty_two_week_low=quote.fifty_two_week_low if quote else None,
                fifty_two_week_high=quote.fifty_two_week_high if quote else None,
                fifty_two_week_position=(
                    _ratio(quote.fifty_two_week_position) if quote else None
                ),
                # ⚠️거리는 **가격이 있을 때만** 낸다. 없으면 None — 0 으로 두면
                #   "이미 도달"처럼 보인다.
                # ⚠️목표가 없으면 None 이다. 0 으로 두면 "0% 로 두겠다"로 읽힌다.
                rebalance_weight=targets.get(item.ticker),
                to_target=(
                    _ratio((item.target_price - price) / price)
                    if price and item.target_price is not None and price > 0
                    else None
                ),
                to_stop=(
                    _ratio((item.stop_price - price) / price)
                    if price and item.stop_price is not None and price > 0
                    else None
                ),
                source=quote.source if quote else None,
                as_of=quote.as_of if quote else None,
            )
        )

    return WatchlistListOut(items=out, missing=missing, fetched=fetched)


def _ordered(db: Session) -> list[WatchlistItem]:
    return list(
        db.execute(
            select(WatchlistItem).order_by(
                WatchlistItem.sort_order, WatchlistItem.created_at
            )
        ).scalars()
    )


@router.get("", response_model=WatchlistListOut)
def list_watchlist(db: Session = Depends(get_db)) -> WatchlistListOut:
    """관심종목 + 실시간 시세. 시세를 못 받은 종목은 `missing` 으로 알린다."""
    return _build(_ordered(db), db)


@router.post("", response_model=WatchlistListOut, status_code=201)
def add_watchlist(
    payload: WatchlistCreateIn, db: Session = Depends(get_db)
) -> WatchlistListOut:
    """종목 추가.

    ⚠️시세를 못 받는 티커도 **막지 않는다.** 오타인지 소스가 잠깐 죽은 건지
      구분할 수 없고, 막아 버리면 사용자가 왜 안 되는지 알 수 없다.
      대신 목록에서 "시세 없음"으로 보인다.
    """
    ticker = _normalize(payload.ticker)
    if not ticker:
        raise AppError(400, "VALIDATION_ERROR", "종목코드를 입력하세요.")

    exists = db.execute(
        select(WatchlistItem).where(WatchlistItem.ticker == ticker)
    ).scalar_one_or_none()
    if exists is not None:
        raise AppError(409, "ALREADY_EXISTS", f"{ticker} 는 이미 관심종목에 있습니다.")

    # 새 항목은 맨 뒤로. 기존 순서를 흔들지 않는다.
    # ★티커만 넣어도 이름이 붙게 한다: 우리 표(자산·실현손익) → 네이버 순.
    #   둘 다 못 찾으면 비워 두고 화면이 티커로 떨어진다.
    name = (payload.asset_name or "").strip() or None
    if name is None:
        name = display_names(db, [ticker]).get(ticker) or lookup_name(ticker)

    last = db.execute(select(func.max(WatchlistItem.sort_order))).scalar() or 0
    db.add(
        WatchlistItem(
            ticker=ticker,
            asset_name=name,
            memo=payload.memo,
            target_price=payload.target_price,
            stop_price=payload.stop_price,
            sort_order=last + 1,
        )
    )
    db.commit()
    return _build(_ordered(db), db)


@router.patch("/{item_id}", response_model=WatchlistListOut)
def update_watchlist(
    item_id: uuid.UUID, payload: WatchlistUpdateIn, db: Session = Depends(get_db)
) -> WatchlistListOut:
    """메모·목표가·손절가 수정.

    ⚠️`exclude_unset` 을 쓴다. 안 쓰면 메모만 고치려 해도 목표가가 null 로
      덮인다(기본값 None 이 그대로 저장된다).
    """
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise AppError(404, "NOT_FOUND", "관심종목을 찾을 수 없습니다.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return _build(_ordered(db), db)


@router.delete("/{item_id}", response_model=WatchlistListOut)
def remove_watchlist(
    item_id: uuid.UUID, db: Session = Depends(get_db)
) -> WatchlistListOut:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise AppError(404, "NOT_FOUND", "관심종목을 찾을 수 없습니다.")
    db.delete(item)
    db.commit()
    return _build(_ordered(db), db)


@router.post("/import-holdings", response_model=WatchlistListOut)
def import_holdings(db: Session = Depends(get_db)) -> WatchlistListOut:
    """보유 종목을 관심종목으로 한 번에 담는다.

    ★이건 **복사가 아니라 시작점**이다. 담고 나면 보유와 독립이라, 팔아도
      관심종목에는 남는다 — 그게 이 화면의 쓸모다(판 뒤에도 계속 지켜본다).
    """
    held = db.execute(
        select(Asset.ticker, Asset.name)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .distinct()
    ).all()
    existing = {i.ticker for i in _ordered(db)}
    last = db.execute(select(func.max(WatchlistItem.sort_order))).scalar() or 0

    added = 0
    for ticker, name in held:
        key = _normalize(ticker)
        if key in existing:
            continue
        last += 1
        added += 1
        db.add(WatchlistItem(ticker=key, asset_name=name, sort_order=last))
    if added:
        db.commit()
    return _build(_ordered(db), db)
