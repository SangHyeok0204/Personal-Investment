"""알림 규칙 판정 — 조건을 지금 시세로 다시 잰다.

★**전달은 아직 없다.** 텔레그램 설정이 필요한 부분은 막혀 있지만, 규칙을 세우고
  "지금 무엇이 조건을 만족하는가"를 판정하는 부분은 지금 데이터로 전부 된다.
  전달 경로가 생기면 이 판정 결과를 보내기만 하면 된다.

⚠️**세 번째 상태가 있다.** 충족/미충족만 두면 안 된다 —
    TRIGGERED  조건을 만족한다
    OK         조건을 만족하지 않는다
    UNKNOWN    **잴 수 없었다**(시세 결측·52주 범위 없음·보유하지 않음)
  잴 수 없는데 "미충족"이라고 적으면 화면이 "괜찮다"고 거짓말을 한다. 이 프로젝트가
  반복해서 지켜 온 원칙이다 — 없는 값은 0 이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

TRIGGERED = "TRIGGERED"
OK = "OK"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RuleKind:
    key: str
    label: str
    #: 화면에 적을 한 줄 설명.
    hint: str
    #: 종목이 필요한가(아니면 포트폴리오 전체 규칙).
    needs_ticker: bool
    #: 임계값 단위 — "price" | "percent" | "days" | None
    unit: str | None


KINDS: list[RuleKind] = [
    RuleKind("PRICE_ABOVE", "목표가 도달", "현재가가 기준가 이상", True, "price"),
    RuleKind("PRICE_BELOW", "손절가 이탈", "현재가가 기준가 이하", True, "price"),
    RuleKind("DAY_MOVE_ABS", "당일 급등락", "당일 등락률 절대값이 기준 이상", True, "percent"),
    RuleKind("NEAR_52W_HIGH", "52주 신고가 근접", "52주 최고가에서 기준% 이내", True, "percent"),
    RuleKind("NEAR_52W_LOW", "52주 신저가 근접", "52주 최저가에서 기준% 이내", True, "percent"),
    RuleKind("PNL_RATE_BELOW", "평가손실 확대", "평가손익률이 기준 이하", True, "percent"),
    RuleKind("PNL_RATE_ABOVE", "평가이익 도달", "평가손익률이 기준 이상", True, "percent"),
    RuleKind("WEIGHT_ABOVE", "비중 초과", "한 종목 비중이 기준% 초과", True, "percent"),
    RuleKind(
        "ORDER_UNFILLED", "최근 미체결",
        "최근 기준일 안에 낸 주문 중 체결되지 않은 것", False, "days",
    ),
]

KIND_BY_KEY = {k.key: k for k in KINDS}


@dataclass(frozen=True)
class Verdict:
    state: str
    #: 지금 잰 값(표시용). 잴 수 없었으면 None.
    actual: Decimal | None
    #: 왜 그렇게 판정했는지 한 줄. UNKNOWN 이면 **무엇이 없어서인지** 적는다.
    message: str


@dataclass(frozen=True)
class Facts:
    """판정에 쓰는 지금 사실. 없는 값은 None 으로 들어온다(0 이 아니다)."""

    price: Decimal | None = None
    change_rate: Decimal | None = None
    week52_high: Decimal | None = None
    week52_low: Decimal | None = None
    pnl_rate: Decimal | None = None
    weight: Decimal | None = None
    held: bool = False
    #: 조회 창 안의 주문 수. None 이면 주문 내역을 못 받은 것이다(0 건과 다르다).
    order_total: int | None = None
    order_unfilled: int = 0


def _pct(value: Decimal | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _num(value: Decimal | None) -> str:
    """Numeric(20,6) 을 사람이 읽는 숫자로. "7.000000일" 이라고 쓰지 않는다."""
    if value is None:
        return "—"
    normalized = value.normalize()
    return f"{normalized:f}"


def evaluate(kind: str, threshold: Decimal | None, facts: Facts) -> Verdict:
    """한 규칙을 지금 사실에 대고 판정한다.

    ⚠️임계값이 없으면 **판정하지 않는다.** 0 으로 넣으면 모든 가격이 조건을
      만족해 알림이 늘 켜진 것처럼 보인다.
    """
    spec = KIND_BY_KEY.get(kind)
    if spec is None:
        return Verdict(UNKNOWN, None, f"모르는 규칙 종류입니다({kind}).")
    if spec.unit is not None and threshold is None:
        return Verdict(UNKNOWN, None, "기준값이 없습니다.")

    if kind == "PRICE_ABOVE":
        if facts.price is None:
            return Verdict(UNKNOWN, None, "현재가를 받지 못했습니다.")
        hit = facts.price >= threshold
        return Verdict(
            TRIGGERED if hit else OK, facts.price,
            f"현재가 {_num(facts.price)} {'≥' if hit else '<'} 기준 {_num(threshold)}",
        )

    if kind == "PRICE_BELOW":
        if facts.price is None:
            return Verdict(UNKNOWN, None, "현재가를 받지 못했습니다.")
        hit = facts.price <= threshold
        return Verdict(
            TRIGGERED if hit else OK, facts.price,
            f"현재가 {_num(facts.price)} {'≤' if hit else '>'} 기준 {_num(threshold)}",
        )

    if kind == "DAY_MOVE_ABS":
        if facts.change_rate is None:
            # ⚠️전일 종가가 없으면 등락률을 만들 수 없다. 0% 로 두면 "조용하다"는
            #   거짓이 된다.
            return Verdict(UNKNOWN, None, "당일 등락률을 계산할 수 없습니다(전일 종가 없음).")
        moved = abs(facts.change_rate)
        hit = moved >= threshold
        return Verdict(
            TRIGGERED if hit else OK, facts.change_rate,
            f"당일 {_pct(facts.change_rate)} (절대값 {_pct(moved)} vs 기준 {_pct(threshold)})",
        )

    if kind == "NEAR_52W_HIGH":
        if facts.price is None or facts.week52_high is None or facts.week52_high == 0:
            return Verdict(UNKNOWN, None, "52주 최고가를 받지 못했습니다.")
        gap = (facts.week52_high - facts.price) / facts.week52_high
        hit = gap <= threshold
        return Verdict(
            TRIGGERED if hit else OK, gap,
            f"52주 최고가 {_num(facts.week52_high)} 에서 {_pct(gap)} 아래 (기준 {_pct(threshold)} 이내)",
        )

    if kind == "NEAR_52W_LOW":
        if facts.price is None or facts.week52_low is None or facts.week52_low == 0:
            return Verdict(UNKNOWN, None, "52주 최저가를 받지 못했습니다.")
        gap = (facts.price - facts.week52_low) / facts.week52_low
        hit = gap <= threshold
        return Verdict(
            TRIGGERED if hit else OK, gap,
            f"52주 최저가 {_num(facts.week52_low)} 에서 {_pct(gap)} 위 (기준 {_pct(threshold)} 이내)",
        )

    if kind in ("PNL_RATE_BELOW", "PNL_RATE_ABOVE"):
        if not facts.held:
            # ⚠️보유하지 않은 종목의 평가손익은 **없는 것**이지 0 이 아니다.
            return Verdict(UNKNOWN, None, "보유하지 않은 종목입니다.")
        if facts.pnl_rate is None:
            return Verdict(UNKNOWN, None, "평가손익률을 계산할 수 없습니다(매입원가 환산 불가).")
        hit = (
            facts.pnl_rate <= threshold
            if kind == "PNL_RATE_BELOW"
            else facts.pnl_rate >= threshold
        )
        sign = "≤" if kind == "PNL_RATE_BELOW" else "≥"
        return Verdict(
            TRIGGERED if hit else OK, facts.pnl_rate,
            f"평가손익률 {_pct(facts.pnl_rate)} {sign if hit else '↔'} 기준 {_pct(threshold)}",
        )

    if kind == "WEIGHT_ABOVE":
        if not facts.held:
            return Verdict(UNKNOWN, None, "보유하지 않은 종목입니다.")
        if facts.weight is None:
            return Verdict(UNKNOWN, None, "비중을 계산할 수 없습니다(평가액 환산 불가).")
        hit = facts.weight > threshold
        return Verdict(
            TRIGGERED if hit else OK, facts.weight,
            f"비중 {_pct(facts.weight)} vs 기준 {_pct(threshold)}",
        )

    if kind == "ORDER_UNFILLED":
        if facts.order_total is None:
            return Verdict(UNKNOWN, None, "주문 내역을 받지 못했습니다.")
        if facts.order_total == 0:
            # ⚠️주문이 없는 것과 전부 체결된 것은 다르다. 창이 비었으면 판정하지 않는다.
            return Verdict(UNKNOWN, None, f"최근 {_num(threshold)}일에 주문이 없습니다.")
        hit = facts.order_unfilled > 0
        return Verdict(
            TRIGGERED if hit else OK, Decimal(facts.order_unfilled),
            f"최근 {_num(threshold)}일 주문 {facts.order_total}건 중 "
            f"{facts.order_unfilled}건 미체결"
            if hit
            else f"최근 {_num(threshold)}일 주문 {facts.order_total}건이 모두 체결됐습니다",
        )

    return Verdict(UNKNOWN, None, f"판정이 구현되지 않았습니다({kind}).")


def unfilled_orders(orders, window_days: int, today: date | None = None):
    """최근 `window_days` 안에 낸 주문 중 미체결. `(전체, 미체결)`.

    ⚠️처음에는 "미체결이 N일째 방치됐나"로 짰는데 **그런 상태가 존재하지 않았다.**
      실측: 주문 145건이 **전부 `remaining_quantity = 0`** 이다. 증권사 기간별
      주문내역은 이미 닫힌 주문만 주고, 체결되지 않은 지정가는 장 마감에
      소멸한다. 그대로 두면 "55건이 477일째 미체결"이라는, 아무도 손쓸 수 없고
      영원히 켜져 있는 알림이 된다.
      → **최근 창 안의 미체결**로 바꿨다. "어제 건 지정가가 안 걸렸다"는 볼 수 있다.

    ⚠️취소된 주문은 미체결로 세지 않는다 — 스스로 취소한 것은 알릴 일이 아니다.
    """
    today = today or date.today()
    total = 0
    unfilled = 0
    for order in orders:
        if (today - order.order_date).days > window_days:
            continue
        if (order.cancelled_quantity or Decimal("0")) > 0:
            continue
        ordered = order.order_quantity or Decimal("0")
        if ordered <= 0:
            continue
        total += 1
        if (order.filled_quantity or Decimal("0")) < ordered:
            unfilled += 1
    return total, unfilled


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
