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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import APIRouter, Query

from app.schemas import MarketMonitorOut, MarketRowOut

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

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
