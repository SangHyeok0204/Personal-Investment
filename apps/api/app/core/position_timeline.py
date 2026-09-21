"""매매 이력 → 종목별 편입 타임라인 · 편입비 · 편입/청산 이벤트.

★왜 스냅샷이 아니라 매매 이력에서 복원하는가(2026-09-22):
  `portfolio_snapshots` 에는 **오늘 것 한 줄뿐**이다. 우리가 오늘부터 매일 쌓아도
  과거는 영영 비어 있다. 반면 매매 이력은 증권사가 과거치를 그대로 준다(실측
  82건 / 2025-04-10~2026-09-16 / 25종목). 그래서 수량과 원가를 거래로 되감는다.

★편입비는 **원가(cost) 기준**이다. 평가금액 기준이 아니다.
  평가금액 비중을 과거 시점으로 계산하려면 종목별 과거 주가가 있어야 하는데
  우리는 그걸 저장하지 않는다. 없는 가격을 만들어 쓰는 대신 축을 바꿨다 —
  "내가 각 종목에 넣은 돈의 비중"은 매매 이력만으로 정확하게 복원된다.

★금액은 **USD 그대로** 다룬다. trades 의 amount_krw 는 82건 전부 비어 있고
  거래일 환율도 없다. 오늘 환율을 과거 거래에 곱하면 그 숫자는 거짓이 된다.

원가 계산은 **이동평균법**이다. 매도할 때 그 시점 평균단가만큼 원가를 덜어낸다.
증권사 실현손익(realized_pnl)도 같은 방식이라 숫자가 서로 어긋나지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

_ZERO = Decimal("0")

# 수량이 이보다 작으면 0으로 본다. 소수점 매수(0.0001주)가 남아 '청산'이 영영
# 기록되지 않는 것을 막는다.
_DUST = Decimal("0.000001")


@dataclass(frozen=True)
class TradeRow:
    trade_date: date
    ticker: str
    side: str
    quantity: Decimal
    amount: Decimal | None
    """체결금액. 없으면 수량 x 단가로 메운다."""
    price: Decimal | None = None
    asset_name: str | None = None

    @property
    def is_buy(self) -> bool:
        return self.side.upper().startswith("B")

    @property
    def value(self) -> Decimal:
        """체결금액. 둘 다 없으면 0 — 원가를 추측하지 않는다."""
        if self.amount is not None:
            return self.amount
        if self.price is not None:
            return self.price * self.quantity
        return _ZERO


@dataclass(frozen=True)
class Lot:
    """한 종목의 현재 수량과 누적 원가."""

    ticker: str
    quantity: Decimal
    cost: Decimal
    first_entry: date
    asset_name: str | None = None

    @property
    def avg_price(self) -> Decimal | None:
        if self.quantity <= _DUST:
            return None
        return self.cost / self.quantity


@dataclass(frozen=True)
class InclusionEvent:
    """편입 구조가 바뀐 순간. 화면의 '편입/청산' 목록이 이걸 그대로 쓴다."""

    event_date: date
    ticker: str
    asset_name: str | None
    kind: str
    """ENTRY(신규 편입) · ADD(추가 매수) · TRIM(일부 매도) · EXIT(전량 청산)"""
    quantity: Decimal
    amount: Decimal
    weight_before: Decimal | None
    weight_after: Decimal | None
    holdings_after: int


@dataclass(frozen=True)
class WeightPoint:
    """한 시점의 종목별 원가 비중."""

    base_date: date
    ticker: str
    weight: Decimal
    cost: Decimal


def _weights(lots: dict[str, Lot]) -> dict[str, Decimal]:
    total = sum((l.cost for l in lots.values()), _ZERO)
    if total <= _ZERO:
        return {}
    return {t: l.cost / total for t, l in lots.items()}


def build_timeline(
    trades: list[TradeRow],
) -> tuple[list[InclusionEvent], dict[date, dict[str, Lot]]]:
    """매매 이력을 되감아 이벤트 목록과 날짜별 보유 상태를 만든다.

    같은 날 여러 건이 있으면 **모두 처리한 뒤** 그 날의 상태를 한 번 기록한다 —
    같은 날 매도 후 재매수 같은 경우 중간 상태가 비중으로 잡히면 안 된다.
    """
    # ⚠️날짜로만 정렬한다(파이썬 sort 는 안정 정렬이라 같은 날 순서는 그대로다).
    #   같은 날 매수를 매도 앞으로 당기는 '안전한' 재정렬을 넣었다가, 매도 후
    #   재매수한 날의 원가가 500 대신 428.57 로 틀어졌다. 체결 순서를 바꾸면
    #   이동평균 원가가 바로 어긋난다. 호출자가 trade_no 순으로 넘겨 준다.
    ordered = sorted(trades, key=lambda t: t.trade_date)
    lots: dict[str, Lot] = {}
    events: list[InclusionEvent] = []
    history: dict[date, dict[str, Lot]] = {}

    for trade in ordered:
        before = _weights(lots)
        lot = lots.get(trade.ticker)

        if trade.is_buy:
            if lot is None:
                lot = Lot(
                    ticker=trade.ticker,
                    quantity=trade.quantity,
                    cost=trade.value,
                    first_entry=trade.trade_date,
                    asset_name=trade.asset_name,
                )
                kind = "ENTRY"
            else:
                lot = replace(
                    lot,
                    quantity=lot.quantity + trade.quantity,
                    cost=lot.cost + trade.value,
                    asset_name=lot.asset_name or trade.asset_name,
                )
                kind = "ADD"
            lots[trade.ticker] = lot
        else:
            if lot is None:
                # 편입 기록 없이 매도가 먼저 나오는 경우(조회 기간 밖에서 산 종목).
                # 없는 원가를 지어내지 않는다 — 이벤트만 남기고 넘어간다.
                events.append(
                    InclusionEvent(
                        event_date=trade.trade_date,
                        ticker=trade.ticker,
                        asset_name=trade.asset_name,
                        kind="EXIT",
                        quantity=trade.quantity,
                        amount=trade.value,
                        weight_before=None,
                        weight_after=None,
                        holdings_after=len(lots),
                    )
                )
                history[trade.trade_date] = dict(lots)
                continue

            avg = lot.avg_price or _ZERO
            sold = min(trade.quantity, lot.quantity)
            remaining = lot.quantity - sold
            if remaining <= _DUST:
                lots.pop(trade.ticker, None)
                kind = "EXIT"
            else:
                lot = replace(lot, quantity=remaining, cost=lot.cost - avg * sold)
                lots[trade.ticker] = lot
                kind = "TRIM"

        after = _weights(lots)
        events.append(
            InclusionEvent(
                event_date=trade.trade_date,
                ticker=trade.ticker,
                asset_name=trade.asset_name,
                kind=kind,
                quantity=trade.quantity,
                amount=trade.value,
                weight_before=before.get(trade.ticker),
                weight_after=after.get(trade.ticker),
                holdings_after=len(lots),
            )
        )
        history[trade.trade_date] = dict(lots)

    return events, history


def month_end_weights(history: dict[date, dict[str, Lot]]) -> list[WeightPoint]:
    """월말 기준 종목별 원가 비중.

    거래가 없던 달은 **직전 상태를 그대로 이어 붙인다** — 비중은 거래가 없어도
    유지되는 값이라, 빈 달을 건너뛰면 그래프가 끊겨 보인다.
    """
    if not history:
        return []

    ordered = sorted(history.items())
    out: list[WeightPoint] = []
    months: dict[str, dict[str, Lot]] = {}

    for day, lots in ordered:
        months[f"{day.year:04d}-{day.month:02d}"] = lots

    # 첫 달부터 마지막 달까지 빈 달 없이 채운다.
    first = ordered[0][0]
    last = ordered[-1][0]
    carried: dict[str, Lot] = {}
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        key = f"{year:04d}-{month:02d}"
        carried = months.get(key, carried)
        weights = _weights(carried)
        as_of = date(year, month, 1)
        for ticker, weight in weights.items():
            out.append(
                WeightPoint(
                    base_date=as_of,
                    ticker=ticker,
                    weight=weight,
                    cost=carried[ticker].cost,
                )
            )
        month += 1
        if month > 12:
            year, month = year + 1, 1

    return out


def holding_periods(events: list[InclusionEvent]) -> dict[str, tuple[date, date | None]]:
    """종목별 (최초 편입일, 전량 청산일). 아직 보유 중이면 청산일은 None.

    청산 후 다시 산 종목은 **최초 편입일을 유지**하고 청산일은 비운다 —
    "지금 들고 있다"가 더 중요한 사실이다.
    """
    out: dict[str, tuple[date, date | None]] = {}
    for e in events:
        if e.kind == "ENTRY":
            existing = out.get(e.ticker)
            out[e.ticker] = (
                existing[0] if existing else e.event_date,
                None,
            )
        elif e.kind == "EXIT":
            existing = out.get(e.ticker)
            out[e.ticker] = (
                existing[0] if existing else e.event_date,
                e.event_date,
            )
    return out
