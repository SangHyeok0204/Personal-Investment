"""일별 예탁자산 시계열 → 성과·위험 지표.

`ETF성과분석_양식_v2.html` 의 항목 중 **개인 계좌에서 의미가 있는 것만** 담았다.
양식에는 BM/Peer 대비 초과성과와 상대 기여도가 있지만, 개인 계좌에는 비교 대상
벤치마크가 정의돼 있지 않다 — 없는 기준을 임의로 세워 "초과수익 +3%" 라고 쓰면
그 숫자는 근거가 없다. 그래서 절대 기여도와 절대 위험지표만 낸다.

★핵심 가정(2026-09-21): 입출금은 **그 날 장 마감 시점에 일어난 것**으로 본다.
  키움 usa21670 의 예탁자산(`deposit_assets_krw`)은 일 마감 값이고 입금(`ina_amt`)
  역시 일계라, 그보다 정밀한 타이밍 정보가 없다. 따라서

      r_t = (A_t - F_t) / A_{t-1} - 1,    F_t = 입금_t - 출금_t

  로 계산한다. 이게 일별 시간가중수익률(TWR)의 표준 근사다. 하루 안에서 입금 직후
  큰 변동이 있었다면 그 날 수익률은 조금 틀리지만, 다음 날부터는 다시 맞는다.

⚠️A_{t-1} 이 없거나 0 이하인 날은 **수익률을 만들지 않는다**. 0 으로 나눌 수 없고,
  "계좌가 비어 있던 날의 수익률 0%" 를 끼워 넣으면 변동성이 실제보다 낮아진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# 연환산에 쓰는 거래일 수. 미국장 기준 관행값.
TRADING_DAYS_PER_YEAR = 252

_ZERO = Decimal("0")


@dataclass(frozen=True)
class DailyPoint:
    """하루치 예탁자산과 그 날의 순입금."""

    base_date: date
    assets_krw: Decimal | None
    deposit_krw: Decimal | None
    withdrawal_krw: Decimal | None

    @property
    def net_flow(self) -> Decimal:
        return (self.deposit_krw or _ZERO) - (self.withdrawal_krw or _ZERO)


@dataclass(frozen=True)
class DailyReturn:
    base_date: date
    ret: Decimal
    """그 날 종가 기준 누적지수(시작 = 1)."""
    index: Decimal


# 입출금이 **다음 날짜로 밀려 기록되는** 경우를 되돌리는 한계값.
#
# 키움 usa21670 에서 실제로 관측된 사례(2025-04-09/10): 자산은 04-09 에
# 971,071 → 2,329,988 로 뛰었는데 입금 1,356,290 은 04-10 에 기록돼 있었다.
# 그대로 두면 04-09 하루 수익률이 +140% 가 되어 전체 구간 변동성이 105%,
# MDD 가 -62% 로 나온다 — 전부 가짜 숫자다.
#
# ⚠️'이상하면 버린다'로 처리하지 않는다. 진짜 폭락도 같이 지워지기 때문이다.
#   **설명되지 않는 변동분과 거의 같은 금액의 입출금이 바로 다음 날 기록돼 있을 때만**
#   그 입출금을 하루 앞으로 당긴다. 금액이 맞아떨어지는지가 판정 근거다.
_UNEXPLAINED_MOVE = Decimal("0.25")
"""설명되지 않는 하루 변동이 직전 잔고의 이 비율을 넘으면 어긋남을 의심한다."""

_FLOW_MATCH_TOLERANCE = Decimal("0.02")
"""다음 날 입출금이 그 변동분과 이만큼 이내로 맞으면 '같은 건'으로 본다."""


@dataclass(frozen=True)
class FlowShift:
    """하루 앞으로 당긴 입출금 한 건. 화면에 그대로 드러낸다."""

    moved_from: date
    moved_to: date
    amount: Decimal


def reconcile_flows(
    points: list[DailyPoint],
) -> tuple[list[DailyPoint], list[FlowShift]]:
    """다음 날로 밀려 기록된 입출금을 제자리로 당긴다.

    반환값의 두 번째가 **실제로 옮긴 목록**이다. 조용히 고치지 않는다 —
    몇 건을 어떻게 건드렸는지 화면에서 확인할 수 있어야 한다.
    """
    flows = [p.net_flow for p in points]
    shifts: list[FlowShift] = []

    for i in range(1, len(points) - 1):
        prev_assets = points[i - 1].assets_krw
        assets = points[i].assets_krw
        if prev_assets is None or assets is None or prev_assets <= _ZERO:
            continue

        residual = assets - prev_assets - flows[i]
        if abs(residual) <= prev_assets * _UNEXPLAINED_MOVE:
            continue  # 평범한 등락이다. 건드리지 않는다.

        candidate = flows[i + 1]
        if candidate == _ZERO:
            continue
        if abs(candidate - residual) > abs(residual) * _FLOW_MATCH_TOLERANCE:
            continue  # 금액이 안 맞는다 — 진짜 급변일 수 있으므로 그대로 둔다.

        flows[i] += candidate
        flows[i + 1] -= candidate
        shifts.append(
            FlowShift(
                moved_from=points[i + 1].base_date,
                moved_to=points[i].base_date,
                amount=candidate,
            )
        )

    if not shifts:
        return points, []

    adjusted = [
        DailyPoint(
            base_date=p.base_date,
            assets_krw=p.assets_krw,
            # 조정 결과는 순액 한쪽에 몰아 둔다. 입금/출금을 따로 되돌릴 근거가 없다.
            deposit_krw=f if f > _ZERO else _ZERO,
            withdrawal_krw=-f if f < _ZERO else _ZERO,
        )
        for p, f in zip(points, flows)
    ]
    return adjusted, shifts


def daily_returns(points: list[DailyPoint]) -> list[DailyReturn]:
    """일별 TWR 수익률과 누적지수. 앞의 모듈 주석에 있는 가정 그대로다."""
    out: list[DailyReturn] = []
    index = Decimal("1")
    prev: Decimal | None = None

    for p in points:
        current = p.assets_krw
        if prev is not None and prev > _ZERO and current is not None:
            ret = (current - p.net_flow) / prev - Decimal("1")
            index = index * (Decimal("1") + ret)
            out.append(DailyReturn(base_date=p.base_date, ret=ret, index=index))
        # 오늘 값을 못 읽었으면 '이전 값'을 갱신하지 않는다 — 구멍을 건너뛰고
        # 이틀치 변동을 하루 수익률로 잡으면 변동성이 부풀려진다.
        if current is not None:
            prev = current

    return out


def cumulative_return(returns: list[DailyReturn]) -> Decimal | None:
    """기간 누적 수익률(비율). 비어 있으면 None."""
    if not returns:
        return None
    return returns[-1].index / _base_index(returns) - Decimal("1")


def _base_index(returns: list[DailyReturn]) -> Decimal:
    """구간 첫 수익률 **직전**의 지수. 구간을 잘라 써도 기준이 맞는다."""
    first = returns[0]
    return first.index / (Decimal("1") + first.ret)


def annualized_return(returns: list[DailyReturn]) -> Decimal | None:
    """기하 연환산. 기간이 1년 미만이면 **연환산하지 않는다**(None).

    3개월 수익률을 4제곱해 "연 +180%" 라고 쓰는 건 숫자를 부풀리는 짓이다.
    """
    cum = cumulative_return(returns)
    if cum is None or len(returns) < TRADING_DAYS_PER_YEAR:
        return None
    years = Decimal(len(returns)) / Decimal(TRADING_DAYS_PER_YEAR)
    growth = Decimal("1") + cum
    if growth <= _ZERO:
        return None  # 원금 전손 — 기하평균이 정의되지 않는다.
    try:
        return Decimal(str(float(growth) ** (1 / float(years)))) - Decimal("1")
    except (OverflowError, ValueError, InvalidOperation):
        return None


def volatility(returns: list[DailyReturn], annualize: bool = True) -> Decimal | None:
    """표본 표준편차. 2일 미만이면 None(1개짜리 표본의 분산은 의미가 없다)."""
    if len(returns) < 2:
        return None
    values = [r.ret for r in returns]
    mean = sum(values, _ZERO) / Decimal(len(values))
    var = sum(((v - mean) ** 2 for v in values), _ZERO) / Decimal(len(values) - 1)
    sd = Decimal(str(float(var) ** 0.5))
    if not annualize:
        return sd
    return sd * Decimal(str(float(TRADING_DAYS_PER_YEAR) ** 0.5))


def downside_volatility(
    returns: list[DailyReturn], annualize: bool = True
) -> Decimal | None:
    """하방 편차 — 0% 미만인 날만 본다. 소르티노의 분모."""
    losses = [r.ret for r in returns if r.ret < _ZERO]
    if len(losses) < 2:
        return None
    var = sum((v**2 for v in losses), _ZERO) / Decimal(len(losses))
    sd = Decimal(str(float(var) ** 0.5))
    if not annualize:
        return sd
    return sd * Decimal(str(float(TRADING_DAYS_PER_YEAR) ** 0.5))


@dataclass(frozen=True)
class Drawdown:
    value: Decimal
    """낙폭이 가장 깊었던 날."""
    trough_date: date
    """그 직전 고점의 날."""
    peak_date: date


def max_drawdown(returns: list[DailyReturn]) -> Drawdown | None:
    """최대낙폭(음수). 고점 대비 얼마나 빠졌는지."""
    if not returns:
        return None
    peak = _base_index(returns)
    peak_date = returns[0].base_date
    worst: Drawdown | None = None

    for r in returns:
        if r.index > peak:
            peak = r.index
            peak_date = r.base_date
        if peak > _ZERO:
            dd = r.index / peak - Decimal("1")
            if worst is None or dd < worst.value:
                worst = Drawdown(value=dd, trough_date=r.base_date, peak_date=peak_date)

    return worst


def sharpe(
    returns: list[DailyReturn], risk_free_annual: Decimal = _ZERO
) -> Decimal | None:
    """샤프 비율 = (연환산 수익률 - 무위험수익률) / 연환산 변동성.

    ⚠️연환산 수익률이 None(기간 1년 미만)이면 샤프도 내지 않는다. 짧은 기간의
      수익률을 억지로 연환산해 나눠 봐야 비율만 과장된다.
    """
    ann = annualized_return(returns)
    vol = volatility(returns)
    if ann is None or vol is None or vol <= _ZERO:
        return None
    return (ann - risk_free_annual) / vol


def sortino(
    returns: list[DailyReturn], risk_free_annual: Decimal = _ZERO
) -> Decimal | None:
    ann = annualized_return(returns)
    dvol = downside_volatility(returns)
    if ann is None or dvol is None or dvol <= _ZERO:
        return None
    return (ann - risk_free_annual) / dvol


def hit_ratio(returns: list[DailyReturn]) -> Decimal | None:
    """상승한 날의 비율. 보합(0%)은 분자에서 뺀다."""
    if not returns:
        return None
    wins = sum(1 for r in returns if r.ret > _ZERO)
    return Decimal(wins) / Decimal(len(returns))


def monthly_returns(returns: list[DailyReturn]) -> list[tuple[str, Decimal]]:
    """월별 수익률 — 그 달 일별 수익률을 곱해서 누적한다(단순 합이 아니다)."""
    buckets: dict[str, Decimal] = {}
    order: list[str] = []
    for r in returns:
        key = f"{r.base_date.year:04d}-{r.base_date.month:02d}"
        if key not in buckets:
            buckets[key] = Decimal("1")
            order.append(key)
        buckets[key] *= Decimal("1") + r.ret
    return [(k, buckets[k] - Decimal("1")) for k in order]


def window(returns: list[DailyReturn], days: int) -> list[DailyReturn]:
    """최근 `days` 달력일 구간만 잘라낸다. 데이터가 모자라면 있는 만큼."""
    if not returns:
        return []
    cutoff = returns[-1].base_date - timedelta(days=days)
    return [r for r in returns if r.base_date > cutoff]
