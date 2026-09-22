"""알림 — 조건을 세워 두고 지금 충족하는지 본다.

★**전달(텔레그램 등)은 아직 없다.** 사용자의 텔레그램 설정이 있어야 하는 부분은
  막혀 있다. 그래도 규칙을 세우고 판정하는 부분은 지금 데이터로 전부 된다 —
  전달 경로가 생기면 이 판정 결과를 보내기만 하면 되고, 규칙을 다시 만들 필요가
  없다. 화면은 **"보냈다"고 말하지 않는다.**

⚠️판정은 언제나 **지금 시세로 다시** 한다. `last_state` 를 캐시로 쓰면 시세가
  바뀌어도 화면이 옛 상태를 말한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import alert_rules as ar
from app.core import quote_cache
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AlertRule, Asset, CurrentPosition, Order
from app.schemas import (
    AlertKindOut,
    AlertRuleIn,
    AlertRuleOut,
    AlertRulePatch,
    AlertsOut,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

_NOTES = [
    "**밖으로는 아직 보내지 않습니다.** 텔레그램 같은 전달 경로가 연결돼야"
    " 앱을 안 켜 놓은 동안에도 알림이 갑니다. 지금은 상단 바의 **종**이 유일한"
    " 전달 경로입니다 — 어느 화면에 있든 걸린 개수를 배지로 보여 주고, 종에"
    " 마우스를 올리면 무엇이 걸렸는지 나옵니다.",
    "판정은 **볼 때마다 지금 시세로 다시** 합니다. 마지막 상태를 캐시로 쓰면"
    " 시세가 바뀌어도 옛 상태를 말하게 됩니다. 종이 5분마다 이 판정을 돌리므로"
    " '언제부터 걸렸나'도 그만큼 촘촘해집니다 — 예전에는 이 화면을 연 순간에만"
    " 갱신돼서 실제보다 늦게 잡혔습니다.",
    "상태가 셋입니다 — 충족 / 미충족 / **판정 불가**. 시세를 못 받았거나 보유하지"
    " 않은 종목이면 '미충족'이 아니라 판정 불가입니다. 잴 수 없는데 괜찮다고 하면"
    " 그게 더 나쁩니다.",
    "비중·평가손익률은 **보유 종목에만** 적용됩니다. 관심종목에는 가격·등락률·"
    "52주 규칙을 거세요.",
    "최근 미체결은 **취소한 주문을 세지 않습니다.** 스스로 취소한 것은 알릴 일이"
    " 아닙니다.",
    "처음엔 '미체결이 며칠째 방치됐나'로 만들었는데 **그런 상태가 없었습니다** —"
    " 주문 145건이 전부 잔량 0 입니다. 증권사는 이미 닫힌 주문만 주고, 체결되지"
    " 않은 지정가는 장 마감에 소멸합니다. 그대로 뒀다면 '55건이 477일째 미체결'"
    "이라는, 손쓸 수도 없고 영원히 켜져 있는 알림이 됐을 것입니다.",
]


@dataclass
class _Context:
    """한 요청에서 **한 번만** 모은 사실.

    ⚠️처음에는 규칙마다 따로 시세를 받고 DB 를 물었다. 규칙 8개에 시세 조회
      8번 + 쿼리 24번이라 `/api/v1/alerts` 가 **2.1초**였다(실측). 화면이 60초
      마다 부르는 엔드포인트다 — N+1 을 그대로 두면 규칙을 늘릴수록 느려진다.
    """

    quotes: dict
    #: ticker → (평가액KRW, 매입액현지, 평가액현지, 행수)
    positions: dict[str, tuple]
    total_value_krw: Decimal | None
    #: 주문 내역. None 이면 **조회하지 않았다**(빈 목록과 다르다).
    orders: list | None
    names: dict[str, str | None]


def _build_context(db: Session, rules: list[AlertRule]) -> _Context:
    tickers = sorted({r.ticker for r in rules if r.ticker})
    needs_orders = any(r.ticker is None and r.enabled for r in rules)

    # 시세 — 종목 전부를 **한 번에** 받는다.
    quotes: dict = {}
    if tickers:
        quotes, _ = quote_cache.get_quotes(tickers, with_range=True)

    positions: dict[str, tuple] = {}
    names: dict[str, str | None] = {}
    total_value_krw = None
    if tickers:
        rows = db.execute(
            select(
                Asset.ticker,
                func.max(Asset.name),
                func.sum(CurrentPosition.market_value_krw),
                func.sum(CurrentPosition.purchase_amount_local),
                func.sum(CurrentPosition.market_value_local),
                func.count(CurrentPosition.id),
            )
            .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
            .where(Asset.ticker.in_(tickers))
            .group_by(Asset.ticker)
        ).all()
        for ticker, name, value_krw, purchase_local, value_local, count in rows:
            positions[ticker] = (value_krw, purchase_local, value_local, count)
            names[ticker] = name
        # 보유하지 않은 종목의 이름은 assets 에만 있을 수 있다.
        missing = [t for t in tickers if t not in names]
        if missing:
            for ticker, name in db.execute(
                select(Asset.ticker, Asset.name).where(Asset.ticker.in_(missing))
            ).all():
                names[ticker] = name
        total_value_krw = db.execute(
            select(func.sum(CurrentPosition.market_value_krw))
        ).scalar()

    orders = (
        db.execute(select(Order)).scalars().all() if needs_orders else None
    )
    return _Context(
        quotes=quotes, positions=positions, total_value_krw=total_value_krw,
        orders=orders, names=names,
    )


def _facts(ctx: _Context, ticker: str | None, threshold: Decimal | None) -> ar.Facts:
    """판정에 쓸 지금 사실. 없는 값은 None 으로 둔다(0 으로 채우지 않는다)."""
    if ticker is None:
        if not ctx.orders:
            # ⚠️주문 내역 자체가 없는 것과 "창 안에 주문이 없다"는 다르다.
            return ar.Facts(order_total=None)
        days = int(threshold) if threshold is not None else 7
        total, unfilled = ar.unfilled_orders(ctx.orders, days, date.today())
        return ar.Facts(order_total=total, order_unfilled=unfilled)

    quote = ctx.quotes.get(ticker)
    # ⚠️계좌가 여럿이면 같은 종목이 여러 행으로 온다 — 위에서 합산해 뒀다.
    value_krw, purchase_local, value_local, row_count = ctx.positions.get(
        ticker, (None, None, None, 0)
    )
    held = bool(row_count)

    pnl_rate = None
    if held and purchase_local and purchase_local != 0 and value_local is not None:
        # ★현지통화 기준이다 — **환율 효과가 빠져 있다.** 이 프로젝트가 계속
        #   지켜 온 구분이다: "종목이 올랐나"와 "환율로 벌었나"는 다른 질문이다.
        pnl_rate = value_local / purchase_local - Decimal("1")

    weight = None
    if held and value_krw is not None and ctx.total_value_krw:
        # ⚠️환산 못 한 종목이 있으면 분모가 작아져 비중이 부풀어 오른다.
        #   그래도 0 으로 채우는 것보다 낫고, 화면 안내에 그 사실을 적어 둔다.
        if ctx.total_value_krw > 0:
            weight = value_krw / ctx.total_value_krw

    return ar.Facts(
        price=quote.price if quote else None,
        change_rate=quote.change_rate if quote else None,
        week52_high=quote.fifty_two_week_high if quote else None,
        week52_low=quote.fifty_two_week_low if quote else None,
        pnl_rate=pnl_rate,
        weight=weight,
        held=held,
    )


def _to_out(ctx: _Context, rule: AlertRule) -> AlertRuleOut:
    spec = ar.KIND_BY_KEY.get(rule.kind)
    name = ctx.names.get(rule.ticker) if rule.ticker else None

    if not rule.enabled:
        verdict = ar.Verdict(ar.UNKNOWN, None, "꺼져 있습니다.")
    else:
        verdict = ar.evaluate(
            rule.kind, rule.threshold, _facts(ctx, rule.ticker, rule.threshold)
        )

    # ⚠️기록만 갱신한다. 다음 판정에 이 값을 쓰지 않는다.
    if rule.enabled:
        if verdict.state == ar.TRIGGERED and rule.last_state != ar.TRIGGERED:
            rule.triggered_since = ar.now_utc()
        elif verdict.state != ar.TRIGGERED:
            rule.triggered_since = None
        rule.last_state = verdict.state
        rule.last_checked_at = ar.now_utc()

    return AlertRuleOut(
        id=rule.id,
        kind=rule.kind,
        kind_label=spec.label if spec else rule.kind,
        ticker=rule.ticker,
        name=name,
        threshold=rule.threshold,
        unit=spec.unit if spec else None,
        enabled=rule.enabled,
        memo=rule.memo,
        state=verdict.state,
        actual=verdict.actual,
        message=verdict.message,
        triggered_since=rule.triggered_since,
    )


@router.get("", response_model=AlertsOut)
def list_alerts(db: Session = Depends(get_db)) -> AlertsOut:
    """규칙 목록 + **지금** 판정."""
    rules = db.execute(
        select(AlertRule).order_by(AlertRule.created_at.desc())
    ).scalars().all()
    ctx = _build_context(db, rules)
    out = [_to_out(ctx, r) for r in rules]
    db.commit()

    return AlertsOut(
        rules=out,
        kinds=[
            AlertKindOut(
                key=k.key, label=k.label, hint=k.hint,
                needs_ticker=k.needs_ticker, unit=k.unit,
            )
            for k in ar.KINDS
        ],
        triggered_count=sum(1 for r in out if r.state == ar.TRIGGERED),
        unknown_count=sum(1 for r in out if r.enabled and r.state == ar.UNKNOWN),
        disabled_count=sum(1 for r in out if not r.enabled),
        # ⚠️전달 경로가 붙기 전까지 **항상 False** 다. True 로 두면 화면이
        #   "보냈다"고 말하게 된다.
        delivery_configured=False,
        notes=_NOTES,
    )


@router.post("", response_model=AlertRuleOut, status_code=201)
def create_alert(payload: AlertRuleIn, db: Session = Depends(get_db)) -> AlertRuleOut:
    spec = ar.KIND_BY_KEY.get(payload.kind)
    if spec is None:
        raise AppError(status_code=400, code="unknown_kind", message="모르는 알림 종류입니다.")
    ticker = (payload.ticker or "").strip().upper() or None
    if spec.needs_ticker and not ticker:
        raise AppError(status_code=400, code="ticker_required", message="종목이 필요한 규칙입니다.")
    if spec.unit is not None and payload.threshold is None:
        # ⚠️기준값 없이 만들면 판정 불가 상태로만 남는다. 만들 때 막는다.
        raise AppError(status_code=400, code="threshold_required", message="기준값이 필요합니다.")

    rule = AlertRule(
        id=uuid.uuid4(),
        kind=payload.kind,
        ticker=None if not spec.needs_ticker else ticker,
        threshold=payload.threshold,
        memo=(payload.memo or "").strip() or None,
        enabled=payload.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    out = _to_out(_build_context(db, [rule]), rule)
    db.commit()
    return out


@router.patch("/{rule_id}", response_model=AlertRuleOut)
def update_alert(
    rule_id: uuid.UUID, payload: AlertRulePatch, db: Session = Depends(get_db)
) -> AlertRuleOut:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise AppError(status_code=404, code="not_found", message="규칙이 없습니다.")
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.memo is not None:
        rule.memo = payload.memo.strip() or None
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    db.commit()
    db.refresh(rule)
    out = _to_out(_build_context(db, [rule]), rule)
    db.commit()
    return out


# 관심종목·매매일지와 같은 규약 — 지우고 **남은 목록을 그대로 돌려준다.**
# 화면이 다시 조회하지 않아도 되고, 지운 뒤 판정이 어떻게 바뀌었는지 같이 온다.
@router.delete("/{rule_id}", response_model=AlertsOut)
def delete_alert(rule_id: uuid.UUID, db: Session = Depends(get_db)) -> AlertsOut:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise AppError(status_code=404, code="not_found", message="규칙이 없습니다.")
    db.delete(rule)
    db.commit()
    return list_alerts(db)
