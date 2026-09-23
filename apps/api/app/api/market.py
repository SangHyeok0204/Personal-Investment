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
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Asset, CurrentPosition

from app.schemas import (
    MarketNewsOut,
    TopicArticleOut,
    TopicOut,
    AcceleratorOut,
    AiDataOut,
    EarningsEventOut,
    EarningsOut,
    EpsHistoryOut,
    MacroMonitorOut,
    MacroRowOut,
    ManufacturerCountOut,
    PackageDownloadsOut,
    MarketMonitorOut,
    MarketRowOut,
)

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices import ai_data as ai_source  # noqa: E402
from prices import earnings as earnings_source  # noqa: E402
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


# ── 실적 발표 일정 ──────────────────────────────────────────────────────────

# 실적 일정은 초 단위로 바뀌지 않는다. 6시간 캐시.
EARNINGS_TTL_SECONDS = 6 * 3600.0

# ⚠️60일을 본다. 14일·30일 창에서는 **내 보유 종목이 한 건도 안 걸렸다**(실측) —
#   미국 대형주는 분기 실적이라 한 달 창으로는 비는 구간이 길다.
EARNINGS_WINDOW_DAYS = 60

# 근시일 시장 맥락용. 전체는 4,201건이라 그대로 내보낼 수 없다.
_MAJOR_WINDOW_DAYS = 14
_MAJOR_LIMIT = 25

_earnings_lock = threading.Lock()
_earnings_cache: dict[str, tuple[float, "EarningsOut"]] = {}


def _to_event(event, mine: bool) -> EarningsEventOut:
    return EarningsEventOut(
        report_date=event.report_date,
        ticker=event.ticker,
        company=event.company,
        timing=event.timing,
        eps_forecast=event.eps_forecast,
        estimate_count=event.estimate_count,
        last_year_eps=event.last_year_eps,
        market_cap=event.market_cap,
        held=mine,
    )


def _build_earnings(mine_tickers: set[str]) -> "EarningsOut":
    today = date.today()
    events = earnings_source.fetch_calendar(today, EARNINGS_WINDOW_DAYS)

    my_events = [_to_event(e, True) for e in events if e.ticker in mine_tickers]

    # 근시일 대형주 — 시장 맥락. 내 종목은 위에 따로 있으니 여기서 뺀다.
    horizon = today + timedelta(days=_MAJOR_WINDOW_DAYS)
    major = [
        e
        for e in events
        if e.report_date <= horizon
        and e.ticker not in mine_tickers
        and e.market_cap is not None
    ]
    major.sort(key=lambda e: e.market_cap or Decimal("0"), reverse=True)

    return EarningsOut(
        mine=my_events,
        major=[_to_event(e, False) for e in major[:_MAJOR_LIMIT]],
        window_days=EARNINGS_WINDOW_DAYS,
        major_window_days=_MAJOR_WINDOW_DAYS,
        total_scanned=len(events),
        first_date=today,
        last_date=today + timedelta(days=EARNINGS_WINDOW_DAYS),
    )


@router.get("/earnings", response_model=EarningsOut)
def get_earnings(
    tickers: str | None = Query(default=None, description="쉼표로 구분. 내 종목 표시용"),
    refresh: bool = Query(default=False),
) -> EarningsOut:
    """미국 실적 발표 일정 — **키 없이** Nasdaq 공개 API.

    ★야후는 막혔다(실측): v7 quote 401, v10 quoteSummary 는 "Invalid Crumb".
      Nasdaq `api.nasdaq.com/api/calendar/earnings` 는 키 없이 200 이다.

    ⚠️어느 종목이 '내 것'인지는 **호출부가 알려 준다**. 이 라우터는 계좌 DB 를
      보지 않는다 — 시장 데이터 라우터가 포트폴리오에 의존하면 둘이 얽힌다.
    """
    wanted = {
        t.strip().upper() for t in (tickers or "").split(",") if t.strip()
    }
    key = ",".join(sorted(wanted))
    now = time.monotonic()
    with _earnings_lock:
        hit = _earnings_cache.get(key)
        if not refresh and hit is not None and now - hit[0] < EARNINGS_TTL_SECONDS:
            return hit[1]

    built = _build_earnings(wanted)
    with _earnings_lock:
        _earnings_cache[key] = (time.monotonic(), built)
    return built


@router.get("/earnings/{symbol}/history", response_model=list[EpsHistoryOut])
def get_eps_history(symbol: str) -> list[EpsHistoryOut]:
    """분기별 컨센서스 vs 실제. 서프라이즈를 눈으로 본다."""
    return [
        EpsHistoryOut(
            period=row.period,
            kind=row.kind,
            consensus=row.consensus,
            actual=row.actual,
            surprise=row.surprise,
        )
        for row in earnings_source.fetch_eps_history(symbol)
    ]


# ── AI 생태계 지표 ──────────────────────────────────────────────────────────

# 가속기 목록은 하루에 한 번 바뀔까 말까 하고, npm 다운로드는 하루 단위 집계다.
AI_DATA_TTL_SECONDS = 6 * 3600.0

# 추적할 AI SDK. "모델을 실제로 쓰고 있나"의 대리 지표다 — 매출은 분기에 한 번
# 나오지만 이건 매일 나온다.
_AI_PACKAGES: list[tuple[str, str]] = [
    ("openai", "OpenAI"),
    ("@anthropic-ai/sdk", "Anthropic"),
    ("@google/genai", "Google"),
    ("ai", "Vercel AI SDK"),
    ("langchain", "LangChain"),
    ("@huggingface/inference", "HuggingFace"),
]

_ai_lock = threading.Lock()
_ai_cache: tuple[float, "AiDataOut"] | None = None


def _build_ai_data() -> "AiDataOut":
    accelerators = ai_source.fetch_accelerators()
    downloads = ai_source.fetch_downloads(_AI_PACKAGES)

    # ⚠️두 수집 함수는 실패해도 **빈 목록**을 돌려준다. 그대로 두면 화면이
    #   "0종"이라고 말하는데 그건 데이터가 없다는 뜻이 아니라 못 받았다는
    #   뜻이다. 평소 176종·6패키지가 오므로 비어 있으면 실패로 본다.
    missing: list[str] = []
    if not accelerators:
        missing.append("Epoch AI 가속기")
    if not downloads:
        missing.append("npm 다운로드")

    dated = [a for a in accelerators if a.release_date is not None]
    dated.sort(key=lambda a: a.release_date, reverse=True)

    # 제조사별 집계 — 누가 몇 종을 내놓았나. NVIDIA 의 비중이 곧 이 시장이다.
    by_maker: dict[str, int] = {}
    for a in accelerators:
        by_maker[a.manufacturer] = by_maker.get(a.manufacturer, 0) + 1

    return AiDataOut(
        missing=missing,
        # ⚠️"시장의 최신"이 아니라 **이 데이터셋이 아는 최신**이다.
        latest_release_date=(dated[0].release_date if dated else None),
        accelerators=[
            AcceleratorOut(
                name=a.name,
                manufacturer=a.manufacturer,
                kind=a.kind or None,
                release_date=a.release_date,
                price_usd=a.price_usd,
                fp16_flops=a.fp16_flops,
                fp8_flops=a.fp8_flops,
                memory_bytes=a.memory_bytes,
                bandwidth_bytes=a.bandwidth_bytes,
                tdp_watts=a.tdp_watts,
                flops_per_watt=a.flops_per_watt,
            )
            # 최근 것부터. 오래된 카드는 투자 판단에 덜 쓰인다.
            for a in dated[:40]
        ],
        manufacturers=[
            ManufacturerCountOut(name=name, count=count)
            for name, count in sorted(by_maker.items(), key=lambda t: -t[1])
        ],
        total_accelerators=len(accelerators),
        downloads=[
            PackageDownloadsOut(
                package=d.package,
                label=d.label,
                last_week=d.last_week,
                prior_week=d.prior_week,
                week_over_week=(
                    d.week_over_week.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                    if d.week_over_week is not None
                    else None
                ),
                days=[day.isoformat() for day in d.days],
                counts=d.counts,
            )
            for d in sorted(downloads, key=lambda x: -x.last_week)
        ],
        sources=[
            "AI 가속기: Epoch AI `ml_hardware.csv` — 공개 데이터셋, 키 없음",
            "SDK 다운로드: npm registry `api.npmjs.org/downloads` — 공개 API, 키 없음",
            "⚠️Epoch 데이터는 가격·성능이 **미공개인 칸이 흔하다**. 비워 둔 채로 둔다 — 0 으로 채우면 '무료'나 '성능 0'이 된다.",
            "⚠️SDK 다운로드는 CI·미러가 섞인 수치다. 절대값보다 **추세와 상대 비교**로 읽는 편이 낫다.",
        ],
    )


@router.get("/ai-data", response_model=AiDataOut)
def get_ai_data(refresh: bool = Query(default=False)) -> AiDataOut:
    """AI 생태계 지표 — 가속기 · SDK 채택. **키 없이** 공개 데이터."""
    global _ai_cache
    now = time.monotonic()
    with _ai_lock:
        if not refresh and _ai_cache is not None and now - _ai_cache[0] < AI_DATA_TTL_SECONDS:
            return _ai_cache[1]

    built = _build_ai_data()
    with _ai_lock:
        _ai_cache = (time.monotonic(), built)
    return built


# ── 시장 뉴스 (주제별) ───────────────────────────────────────────────────────

_TOPICS_SEED = (
    Path(__file__).resolve().parents[4] / "database" / "seeds" / "news_topics.py"
)

# 주제 뉴스는 분 단위로 바뀌지 않고, 주제 수만큼 구글을 두드려야 한다. 30분 캐시.
MARKET_NEWS_TTL_SECONDS = 1800.0
MARKET_NEWS_WINDOW_DAYS = 3

_market_news_lock = threading.Lock()
_market_news_cache: dict[str, tuple[float, "MarketNewsOut"]] = {}


def _load_topics():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_news_topics_seed", _TOPICS_SEED)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_news_topics_seed"] = module
    spec.loader.exec_module(module)
    return module


def _build_market_news(lang: str, holdings: list[tuple[str, str | None]]) -> "MarketNewsOut":
    from prices import news as news_source

    seed = _load_topics()
    results = news_source.fetch_topic_news(
        seed.NEWS_TOPICS, lang=lang, days=MARKET_NEWS_WINDOW_DAYS
    )

    articles: list[TopicArticleOut] = []
    topics: list[TopicOut] = []
    seen: set[str] = set()

    for r in results:
        for a in r.articles:
            # ⚠️같은 기사가 **여러 주제에** 걸린다(반도체 ↔ AI 인프라). 전체
            #   목록에서 한 번 더 걸러 내지 않으면 같은 제목이 두 번 보인다.
            key = news_source.title_key(a.title)
            if key in seen:
                continue
            seen.add(key)
            # 제목에 걸린 내 보유 종목 — 보유종목 뉴스에서 이미 봤을 수 있다.
            hit = [
                ticker
                for ticker, name in holdings
                if news_source._relevant(a.title, ticker, name)
            ]
            articles.append(
                TopicArticleOut(
                    topic=r.key, topic_label=r.label, title=a.title,
                    publisher=a.publisher, published_at=a.published_at,
                    url=a.url, holdings=hit,
                )
            )
        topics.append(
            TopicOut(
                key=r.key, label=r.label, query=r.query, ok=r.ok, reason=r.reason,
                article_count=len(r.articles), filtered_out=r.filtered_out,
            )
        )

    # 시각을 모르는 기사는 뒤로. 지금 시각으로 채우면 최신인 척한다.
    articles.sort(key=lambda a: (a.published_at is not None, a.published_at), reverse=True)

    return MarketNewsOut(
        articles=articles,
        topics=topics,
        lang=lang,
        window_days=MARKET_NEWS_WINDOW_DAYS,
        filtered_total=sum(t.filtered_out for t in topics),
        holdings_hit_count=sum(1 for a in articles if a.holdings),
        source_ok=any(t.ok for t in topics),
        notes=list(seed.NOTES),
    )


@router.get("/news", response_model=MarketNewsOut)
def get_market_news(
    lang: str = Query(default="ko", pattern="^(ko|en)$"),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> MarketNewsOut:
    """시장 뉴스 — 내가 **아직 안 산 쪽에서** 무슨 일이 있나.

    ★보유종목 뉴스와 같은 소스지만 답하는 질문이 다르다. 거기는 "내 종목에 무슨
      일이 있었나", 여기는 "판이 어떻게 돌아가는가"다.

    ★**한국어를 쓴다.** 종목 검색에서는 한국어가 무너졌지만(최저 32%), 주제
      검색은 97~100% 다(실측) — 주제어가 모호하지 않기 때문이다. 한국 매체가
      국내 공급망(한미반도체·하이닉스)을 먼저 다루므로 오히려 유용하다.

    ⚠️제목에 걸린 보유 종목을 표시한다 — 보유종목 뉴스에서 이미 본 기사를
      여기서 또 읽지 않도록.
    """
    now = time.monotonic()
    with _market_news_lock:
        hit = _market_news_cache.get(lang)
        if not refresh and hit is not None and now - hit[0] < MARKET_NEWS_TTL_SECONDS:
            return hit[1]

    rows = db.execute(
        select(Asset.ticker, Asset.name)
        .join(CurrentPosition, CurrentPosition.asset_id == Asset.id)
        .distinct()
    ).all()
    built = _build_market_news(lang, [(t, n) for t, n in rows if t])
    with _market_news_lock:
        _market_news_cache[lang] = (time.monotonic(), built)
    return built
