"""시장 모니터 — 지수 · 금리 · 환율 · 원자재 · 크립토의 기간 변화.

★DailyPriceAgent 의 주간가격모니터(price_monitor)를 흡수한 것이다. 원본은
  블룸버그에서 받았는데 지금 블룸버그를 쓸 수 없어 야후로 다시 세웠다.
  대상 목록의 정본은 `database/seeds/market_universe.py` 다.

★**금리와 가격을 다르게 표시한다.** 국채금리 4.96 → 5.06 은 "+2% 상승"이 아니라
  "+10bp" 다. 전부 수익률로 묶으면 화면이 통째로 틀린 말을 하게 된다.
  price → 비율(%), rate → bp.

⚠️`/api/v1/stock-monitor` 와 다른 화면이다. 그쪽은 원본 GE 의 collector 를
  프록시하는데 이 환경에는 collector 가 없어서 503 이다. 여기는 외부 의존이
  야후뿐이라 그 자체로 동작한다.
"""

import sys
import threading
import time
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import APIRouter, Query

from app.schemas import (
    MacroMonitorOut,
    MacroRowOut,
    MarketMonitorOut,
    MarketRowOut,
)

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices import fred  # noqa: E402
from prices.history import PERIODS, base_values, changes, fetch_series  # noqa: E402

router = APIRouter(prefix="/api/v1/market", tags=["market"])

_SEED = Path(__file__).resolve().parents[4] / "database" / "seeds" / "market_universe.py"

# 시장 지표는 초 단위로 볼 값이 아니다. 화면이 5초마다 물어도 상류는 5분에 한 번.
TTL_SECONDS = 300.0

_lock = threading.Lock()
_cache: tuple[float, MarketMonitorOut] | None = None

_RATIO = Decimal("0.000001")
_BP = Decimal("0.01")


def _load_universe():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_market_universe_seed", _SEED)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_market_universe_seed"] = module
    spec.loader.exec_module(module)
    return module


def _build() -> MarketMonitorOut:
    universe = _load_universe()
    rows_def = universe.MARKET_UNIVERSE
    # ⚠️2년치를 받는다. 1년만 받으면 1Y 기준일(365일 전)이 보유 구간의 **첫 날보다
    #   앞서** 버려서 1Y 가 거의 전부 "—" 로 나온다(실측). 주식은 거래일이 주 5일
    #   이라 1년치가 365 달력일을 못 덮는다 — 주말이 열리는 FX·크립토만 값이 나왔다.
    series = fetch_series([r[0] for r in rows_def], range_="2y")

    labels = [label for label, _ in PERIODS] + ["YTD"]
    out: list[MarketRowOut] = []
    missing: list[str] = []

    for symbol, name, category, kind, note in rows_def:
        found = series.get(symbol)
        if found is None:
            missing.append(f"{name} ({symbol})")
            continue

        delta = changes(found)
        base = base_values(found)
        values: dict[str, Decimal | None] = {}
        for label in labels:
            diff, start = delta.get(label), base.get(label)
            if diff is None or start is None:
                values[label] = None
                continue
            if kind == "rate":
                # ⚠️금리는 **수준의 차이**다. 1%p = 100bp.
                values[label] = (diff * Decimal("100")).quantize(
                    _BP, rounding=ROUND_HALF_UP
                )
            elif kind == "level":
                # VIX 처럼 bp 관례가 없는 수준 — 포인트 그대로.
                values[label] = diff.quantize(_BP, rounding=ROUND_HALF_UP)
            else:
                # 분모가 0 이면 비율을 낼 수 없다(마이너스 유가 같은 예외).
                values[label] = (
                    None
                    if start == 0
                    else (diff / start).quantize(_RATIO, rounding=ROUND_HALF_UP)
                )

        out.append(
            MarketRowOut(
                symbol=symbol,
                name=name,
                category=category,
                kind=kind,
                note=note or None,
                price=found.latest,
                currency=found.currency or None,
                as_of=found.dates[-1] if found.dates else None,
                changes=values,
            )
        )

    return MarketMonitorOut(
        rows=out,
        categories=universe.CATEGORY_ORDER,
        periods=labels,
        missing=missing,
        missing_sources=universe.MISSING_SOURCES,
    )


@router.get("/monitor", response_model=MarketMonitorOut)
def get_market_monitor(refresh: bool = Query(default=False)) -> MarketMonitorOut:
    """시장 지표 한 장. 5분 캐시 — 시장 지표는 초 단위로 볼 값이 아니다."""
    global _cache
    now = time.monotonic()
    with _lock:
        if not refresh and _cache is not None and now - _cache[0] < TTL_SECONDS:
            return _cache[1]

    built = _build()
    with _lock:
        _cache = (time.monotonic(), built)
    return built


# ── 매크로 지표 ─────────────────────────────────────────────────────────────

_MACRO_SEED = (
    Path(__file__).resolve().parents[4] / "database" / "seeds" / "macro_universe.py"
)

# 매크로는 월간 발표가 대부분이다. 5분마다 받을 이유가 없다.
MACRO_TTL_SECONDS = 3600.0

_macro_lock = threading.Lock()
_macro_cache: tuple[float, "MacroMonitorOut"] | None = None


def _load_macro_universe():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_macro_universe_seed", _MACRO_SEED)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_macro_universe_seed"] = module
    spec.loader.exec_module(module)
    return module


def _macro_value(series, transform: str) -> Decimal | None:
    """지표의 **본래 읽는 값**. transform 마다 다르다.

    ⚠️전부 raw 값으로 보여 주면 틀린 말이 된다 — CPI 332.8 은 아무 의미가 없다.
    """
    if transform == "yoy":
        return series.yoy()
    if transform == "mom_diff":
        return series.mom_diff()
    latest = series.latest
    return latest[1] if latest else None


def _macro_at(series, transform: str, when):
    """과거 시점 기준의 같은 값. 기간 비교에 쓴다."""
    if transform == "yoy":
        return series.yoy(at=when)
    if transform == "mom_diff":
        return series.mom_diff(at=when)
    return series.value_on_or_before(when)


def _build_macro() -> "MacroMonitorOut":
    universe = _load_macro_universe()
    rows_def = universe.MACRO_UNIVERSE
    series_map = fred.fetch_series([r[0] for r in rows_def])

    labels = [label for label, _ in universe.PERIOD_DAYS]
    out: list[MacroRowOut] = []
    missing: list[str] = []

    for series_id, name, category, transform, unit, note in rows_def:
        series = series_map.get(series_id)
        if series is None:
            missing.append(f"{name} ({series_id})")
            continue

        current = _macro_value(series, transform)
        latest = series.latest
        anchor = latest[0] if latest else None

        changes: dict[str, Decimal | None] = {}
        for label, days in universe.PERIOD_DAYS:
            past = (
                _macro_at(series, transform, anchor - timedelta(days=days))
                if anchor is not None
                else None
            )
            # ⚠️변화는 **값의 차이**다. yoy 지표의 "변화"는 물가상승률이 몇 %p
            #   움직였나이지, 물가가 몇 % 올랐나가 아니다.
            changes[label] = (
                (current - past).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                if current is not None and past is not None
                else None
            )

        out.append(
            MacroRowOut(
                series_id=series_id,
                name=name,
                category=category,
                transform=transform,
                unit=unit,
                note=note or None,
                value=(
                    current.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                    if current is not None
                    else None
                ),
                # ⚠️CPI·고용은 발표가 한 달 이상 늦다. 기준일을 반드시 같이 낸다.
                as_of=anchor,
                changes=changes,
            )
        )

    return MacroMonitorOut(
        rows=out,
        categories=universe.CATEGORY_ORDER,
        periods=labels,
        missing=missing,
        notes=universe.MISSING_NOTES,
    )


@router.get("/macro", response_model=MacroMonitorOut)
def get_macro(refresh: bool = Query(default=False)) -> MacroMonitorOut:
    """매크로 지표 — 물가·고용·금리·성장.

    ★FRED 를 **키 없이** 쓴다. API 는 api_key 를 요구하지만(400), 그래프 CSV
      내보내기는 키 없이 200 이다(실측).
    """
    global _macro_cache
    now = time.monotonic()
    with _macro_lock:
        if (
            not refresh
            and _macro_cache is not None
            and now - _macro_cache[0] < MACRO_TTL_SECONDS
        ):
            return _macro_cache[1]

    built = _build_macro()
    with _macro_lock:
        _macro_cache = (time.monotonic(), built)
    return built
