import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TestJobRequest(BaseModel):
    payload: dict[str, Any] | None = None


class InternalJobRequest(BaseModel):
    job_type: str = Field(min_length=1)
    payload: dict[str, Any] | None = None


class CheckHogaEnvelope(BaseModel):
    """CHECK-agent 호가(orderbook) envelope v1. ``payload`` stays a loosely typed
    pass-through dict — the collector owns its shape, the api only validates the
    transport wrapper before forwarding."""

    schema_version: int
    source: str
    source_timestamp: str
    sent_at: str
    seq: int | None = None
    payload: dict[str, Any]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    status: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class JobLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    level: str
    step: str | None
    message: str
    # Field is emitted as "metadata" but read from the ORM ``meta`` attribute
    # (the physical column is "metadata"; SQLAlchemy reserves that attribute name).
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="meta")
    created_at: datetime


class JobDetailOut(JobOut):
    logs: list[JobLogOut] = []


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class JobStatsOut(BaseModel):
    total: int
    pending: int
    running: int
    success: int
    failed: int


class ImportCreateOut(BaseModel):
    job_id: uuid.UUID
    import_id: uuid.UUID
    original_filename: str


class AiUsageMeterOut(BaseModel):
    label: str
    subtitle: str | None = None
    # None = 소진율 판정 불가. 업스트림이 %를 산출하지 못하면 지어내지 않고 null 로
    # 보낸다 — 0% 로 그리면 조용히 틀린 값이 된다.
    pct: float | None = None
    remaining_pct: float | None = None


class AiUsageAccountOut(BaseModel):
    account_num: int
    email: str | None = None
    plan: str | None = None
    captured_at: str | None = None
    age_seconds: float | None = None
    stale: bool
    # '사용 크레딧'(초과분 과금) 토글. False 면 플랜 한도에서 그대로 멈춘다.
    # None = 판정 불가(스크래퍼가 스위치를 못 찾음 / codex 는 이 개념이 없음).
    extra_usage_enabled: bool | None = None
    items: list[AiUsageMeterOut] = []


class AiUsageOut(BaseModel):
    monitor_base_url: str
    reachable: bool
    error: str | None = None
    fetched_at: str
    claude: list[AiUsageAccountOut] = []
    codex: list[AiUsageAccountOut] = []


# ── LAN 대시보드 (lan-dashboard 이식) ────────────────────────────────────
# 필드명은 원본 프런트 계약(camelCase)을 그대로 유지한다.


class LanStatusOut(BaseModel):
    status: str  # online | offline | error | unknown
    responseTime: int | None = None
    error: str | None = None
    httpStatus: int | None = None
    lastChecked: str | None = None


class LanServerOut(BaseModel):
    id: str
    name: str
    host: str
    port: int
    protocol: str  # tcp | http | https | heartbeat
    description: str = ""
    group: str = ""
    key: str = ""  # heartbeat: 프로세스가 POST 하는 키
    maxAgeSec: int | None = None  # heartbeat: 이 초 넘게 수신 없으면 offline
    status: LanStatusOut


class LanServerIn(BaseModel):
    # host/port 는 heartbeat 타입엔 불필요해 기본값 허용 — 타입별 필수검증은 라우터가.
    name: str = Field(min_length=1)
    host: str = ""
    port: int = 0
    protocol: str = "tcp"
    description: str = ""
    group: str = ""
    key: str = ""
    maxAgeSec: int | None = None


class LanServerUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    protocol: str | None = None
    description: str | None = None
    group: str | None = None
    key: str | None = None
    maxAgeSec: int | None = None


class LanGroupIn(BaseModel):
    name: str


class LanSummaryOut(BaseModel):
    total: int
    online: int
    offline: int
    unknown: int


# ── 개인 계좌 포트폴리오 ──────────────────────────────────────────────────────
# 금액은 전부 문자열로 내보낸다. float 로 보내면 브라우저의 IEEE754 반올림이
# 원 단위에서 드러나고(예: 12345678.9 → 12345678.899999999), 합계와 종목별 수치가
# 어긋나 보인다. 프런트는 받은 문자열을 표시용으로만 포맷한다.


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    broker_code: str
    broker_name: str
    connection_name: str
    environment: str
    status: str
    last_connected_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    broker_code: str
    broker_name: str
    account_name: str | None
    account_number_masked: str | None
    account_type: str | None
    base_currency: str
    is_active: bool
    last_synced_at: datetime | None


class AccountListOut(BaseModel):
    items: list[AccountOut]
    # 계좌가 하나도 없으면 프런트는 "미연동" 안내를 띄운다 — 0원으로 그리지 않는다.
    connected: bool


class CashByCurrencyOut(BaseModel):
    """통화별 예수금. krw_value 가 null 이면 환율이 없어 KRW 합계에서 빠진 것이다."""

    currency: str
    cash_balance: Decimal
    available_cash: Decimal | None
    krw_value: Decimal | None


class PortfolioSummaryOut(BaseModel):
    """자산 현황 상단 4칸. 값이 없으면 null 이고, 프런트는 "—" 로 그린다."""

    as_of: datetime | None
    account_count: int
    position_count: int
    total_assets_krw: Decimal | None
    securities_value_krw: Decimal | None
    cash_krw: Decimal | None
    available_cash_krw: Decimal | None
    purchase_amount_krw: Decimal | None
    unrealized_pnl_krw: Decimal | None
    # 매입원가 대비 평가손익률. 매입원가가 0이면 null (0% 로 그리면 거짓말이 된다).
    unrealized_return: Decimal | None
    # 통화별 예수금. cash_krw 는 환산 가능한 것만 더하므로, 환율 없는 외화가 있으면
    # 합계에서 빠진다 — 그 돈이 화면에서 사라지지 않게 내역을 같이 내보낸다.
    cash_by_currency: list[CashByCurrencyOut] = []


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: uuid.UUID
    account_name: str | None
    broker_code: str
    asset_id: uuid.UUID
    ticker: str
    name: str | None
    market: str
    country: str
    currency: str
    asset_type: str | None
    sector: str | None
    industry: str | None
    sector_source: str | None
    # AI/Tech 밸류체인 3단계(전통 섹터와 다른 축)
    tech_l1: str | None
    tech_l2: str | None
    tech_l3: str | None
    quantity: Decimal
    average_purchase_price: Decimal | None
    current_price: Decimal | None
    purchase_amount_local: Decimal | None
    market_value_local: Decimal | None
    market_value_krw: Decimal | None
    unrealized_pnl_local: Decimal | None
    unrealized_pnl_krw: Decimal | None
    unrealized_return: Decimal | None
    exchange_rate: Decimal | None
    as_of: datetime


class HoldingListOut(BaseModel):
    items: list[HoldingOut]
    total_market_value_krw: Decimal | None
    as_of: datetime | None


class SnapshotPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_at: datetime
    total_assets_krw: Decimal | None
    securities_value_krw: Decimal | None
    cash_value_krw: Decimal | None
    total_unrealized_pnl_krw: Decimal | None


class PortfolioHistoryOut(BaseModel):
    items: list[SnapshotPointOut]
    days: int


class AllocationSliceOut(BaseModel):
    """비중 한 조각. 미분류는 key=null 로 내려가고 화면이 '미분류'로 그린다."""

    key: str | None
    label: str
    market_value_krw: Decimal
    weight: Decimal
    position_count: int


class AllocationOut(BaseModel):
    dimension: str
    items: list[AllocationSliceOut]
    total_market_value_krw: Decimal | None
    # 분류가 안 된 평가금액. 0 이면 분류가 끝난 것이다.
    unclassified_market_value_krw: Decimal | None
    as_of: datetime | None


class HoldingSectorPatch(BaseModel):
    """섹터 수기 지정. 화면에서 고친 값은 sector_source='MANUAL' 로 남는다."""

    sector: str | None = Field(default=None, max_length=64)
    industry: str | None = Field(default=None, max_length=64)


# ── 매매(체결) 내역 ──────────────────────────────────────────────────────────

class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str | None
    trade_date: date
    trade_no: str
    side: str
    ticker: str
    asset_name: str | None
    sector: str | None
    currency: str
    quantity: Decimal
    price: Decimal | None
    amount_local: Decimal | None
    settlement_amount_local: Decimal | None
    commission_local: Decimal | None
    tax_local: Decimal | None
    exchange: str | None
    channel: str | None
    processed_at: str | None


class TradeStatsOut(BaseModel):
    """기간 합계. 통화가 섞이면 합산하지 않는다 — 통화별로 나눠 내보낸다."""

    currency: str
    buy_count: int
    sell_count: int
    buy_amount: Decimal
    sell_amount: Decimal
    commission: Decimal
    tax: Decimal


class TradeListOut(BaseModel):
    items: list[TradeOut]
    total: int
    stats: list[TradeStatsOut]
    first_trade_date: date | None
    last_trade_date: date | None


# ── 일별 성과 / 실현손익 ─────────────────────────────────────────────────────

class DailyPerformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_date: date
    deposit_assets_krw: Decimal | None
    stock_value_krw: Decimal | None
    cumulative_pnl_krw: Decimal | None
    pnl_krw: Decimal | None
    deposit_krw: Decimal | None
    withdrawal_krw: Decimal | None


class PerformanceSeriesOut(BaseModel):
    items: list[DailyPerformanceOut]
    first_date: date | None
    last_date: date | None
    # 기간 시작·끝의 예탁자산. 기간 손익은 여기에 순입금을 빼야 의미가 생긴다.
    start_assets_krw: Decimal | None
    end_assets_krw: Decimal | None
    net_deposit_krw: Decimal | None
    # (끝 - 시작 - 순입금). 입출금 영향을 뺀 순수 증감이다.
    gain_krw: Decimal | None


# ── 성과분석 (ETF성과분석_양식_v2.html 대응) ────────────────────────────────

class PeriodReturnOut(BaseModel):
    """기간별 수익률 한 칸. 데이터가 모자란 기간은 ratio 가 None 이다."""

    label: str
    days: int
    return_ratio: Decimal | None
    start_date: date | None
    end_date: date | None
    observations: int


class RiskMetricsOut(BaseModel):
    """한 구간의 위험지표 묶음. 계산 불가한 항목은 None (0 이 아니다)."""

    label: str
    observations: int
    annualized_return: Decimal | None
    volatility: Decimal | None
    downside_volatility: Decimal | None
    max_drawdown: Decimal | None
    max_drawdown_peak_date: date | None
    max_drawdown_trough_date: date | None
    sharpe: Decimal | None
    sortino: Decimal | None
    hit_ratio: Decimal | None


class MonthlyReturnOut(BaseModel):
    month: str
    return_ratio: Decimal


class DrawdownPointOut(BaseModel):
    base_date: date
    drawdown: Decimal


class ContributionOut(BaseModel):
    """종목별 절대 기여도.

    contribution = 종목 평가손익 / **전체 매입원가**. 그래서 전 종목을 더하면
    포트폴리오 평가수익률과 정확히 같아진다 — 화면에서 검산이 된다.
    """

    asset_id: uuid.UUID
    ticker: str
    name: str | None
    sector: str | None
    tech_l1: str | None
    weight: Decimal | None
    purchase_krw: Decimal | None
    market_value_krw: Decimal | None
    unrealized_pnl_krw: Decimal | None
    unrealized_return: Decimal | None
    dividend_krw: Decimal | None
    contribution: Decimal | None


class FlowShiftOut(BaseModel):
    """다음 날로 밀려 기록돼 있던 입출금을 하루 앞으로 당긴 기록.

    조용히 고치지 않는다 — 몇 건을 어떻게 건드렸는지 화면에 그대로 띄운다.
    """

    moved_from: date
    moved_to: date
    amount: Decimal


class PerformanceAnalyticsOut(BaseModel):
    first_date: date | None
    last_date: date | None
    periods: list[PeriodReturnOut]
    risk: list[RiskMetricsOut]
    monthly: list[MonthlyReturnOut]
    drawdown: list[DrawdownPointOut]
    contributions: list[ContributionOut]
    # 검산용 — contributions 의 합과 같아야 한다.
    total_purchase_krw: Decimal | None
    total_unrealized_pnl_krw: Decimal | None
    total_return: Decimal | None
    realized_pnl_krw: Decimal | None
    dividend_krw: Decimal | None
    flow_shifts: list[FlowShiftOut]


# ── 편입비 (매매 이력에서 복원) ──────────────────────────────────────────────

class InclusionEventOut(BaseModel):
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


class InclusionHoldingOut(BaseModel):
    """종목별 편입 현황. 청산된 종목도 포함한다(빠진 이력도 이력이다)."""

    ticker: str
    asset_name: str | None
    first_entry: date
    exited_at: date | None
    status: str
    """OPEN(보유 중) · CLOSED(청산) · STALE(매매 이력에 매도가 빠짐)

    STALE 은 실제로 관측된 상태다 — SKHY 는 2026-09-18 에 팔려 realized_pnl 에
    있는데 그 매도 체결만 trades 에 없었다. 조용히 보유 중으로 두면 편입비가
    틀리고, 조용히 지우면 이력이 사라진다. 그래서 표시해서 남긴다.
    """
    holding_days: int
    cost: Decimal | None
    weight: Decimal | None
    buy_count: int
    sell_count: int


class InclusionWeightPointOut(BaseModel):
    base_date: date
    ticker: str
    weight: Decimal
    cost: Decimal


class InclusionOut(BaseModel):
    """편입비 — **원가(USD) 기준**이다.

    평가금액 기준 과거 비중은 종목별 과거 주가가 있어야 하는데 저장하지 않는다.
    trades 의 amount_krw 는 전부 비어 있고 거래일 환율도 없어서 USD 로 둔다.
    """

    currency: str
    first_trade_date: date | None
    last_trade_date: date | None
    holdings: list[InclusionHoldingOut]
    events: list[InclusionEventOut]
    monthly_weights: list[InclusionWeightPointOut]
    total_cost: Decimal | None
    open_count: int
    exited_count: int


# ── 실시간 시세 (보유 종목) ──────────────────────────────────────────────────

class LiveQuoteOut(BaseModel):
    """한 종목의 실시간 시세 + 그 가격으로 다시 계산한 평가금액."""

    ticker: str
    name: str | None
    price: Decimal
    currency: str
    previous_close: Decimal | None
    change: Decimal | None
    change_rate: Decimal | None
    as_of: datetime | None
    source: str
    quantity: Decimal | None
    market_value_local: Decimal | None
    market_value_krw: Decimal | None
    unrealized_pnl_krw: Decimal | None


class LiveQuotesOut(BaseModel):
    """보유 종목 실시간 시세.

    ⚠️KRW 환산에는 **수집 시점에 증권사가 준 환율을 그대로** 쓴다. 여기서 환율을
      새로 받아오지 않는다 — 가격과 환율이 서로 다른 시점의 값이면 합계가
      종목별 수치와 어긋나고, 그 차이는 화면에서 "합이 안 맞는다"로 보인다.
      움직이는 건 가격뿐이고 환율은 마지막 동기화 값에 고정돼 있다.
    """

    items: list[LiveQuoteOut]
    total_market_value_krw: Decimal | None
    total_unrealized_pnl_krw: Decimal | None
    # 시세를 못 받은 종목 — 숨기지 않고 개수로 알린다.
    missing: list[str]
    fetched: int
    as_of: datetime | None


# ── 관심종목 ─────────────────────────────────────────────────────────────────

class WatchlistCreateIn(BaseModel):
    ticker: str
    asset_name: str | None = None
    memo: str | None = None
    target_price: Decimal | None = None
    stop_price: Decimal | None = None


class WatchlistUpdateIn(BaseModel):
    """부분 수정. 라우터가 `exclude_unset` 으로 **보낸 필드만** 반영한다 —
    안 그러면 메모만 고쳐도 목표가가 null 로 덮인다."""

    asset_name: str | None = None
    memo: str | None = None
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    sort_order: int | None = None


class WatchlistItemOut(BaseModel):
    id: uuid.UUID
    ticker: str
    asset_name: str | None
    memo: str | None
    target_price: Decimal | None
    stop_price: Decimal | None
    sort_order: int
    # 지금 보유 중인지. 저장하지 않고 current_positions 를 보고 매번 판단한다.
    held: bool

    # 아래는 시세 소스에서 온 값. 못 받으면 전부 None 이고 화면이 "—" 로 둔다.
    price: Decimal | None
    currency: str | None
    previous_close: Decimal | None
    change: Decimal | None
    change_rate: Decimal | None
    fifty_two_week_low: Decimal | None
    fifty_two_week_high: Decimal | None
    # 52주 저점 0 ~ 고점 1 사이의 위치.
    fifty_two_week_position: Decimal | None
    # 현재가 대비 목표가/손절가까지의 비율. 가격이 없으면 None(0 이 아니다).
    to_target: Decimal | None
    to_stop: Decimal | None
    source: str | None
    as_of: datetime | None


class WatchlistListOut(BaseModel):
    items: list[WatchlistItemOut]
    # 시세를 못 받은 종목. 숨기지 않고 드러낸다.
    missing: list[str]
    fetched: int


# ── 시장 모니터 ──────────────────────────────────────────────────────────────

class MarketRowOut(BaseModel):
    """시장 지표 한 줄.

    ⚠️`changes` 의 단위는 `kind` 에 따라 다르다.
      · price → **비율**(0.0123 = +1.23%)
      · rate  → **bp**(10.0 = +10bp). 금리 4.96 → 5.06 은 "+2%" 가 아니다.
      화면은 kind 를 보고 단위를 붙여야 한다.
    """

    symbol: str
    name: str
    category: str
    kind: str
    note: str | None
    price: Decimal | None
    currency: str | None
    as_of: date | None
    changes: dict[str, Decimal | None]


class MarketMonitorOut(BaseModel):
    rows: list[MarketRowOut]
    categories: list[str]
    periods: list[str]
    # 이번 조회에서 못 받은 지표. 숨기지 않는다.
    missing: list[str]
    # 아예 출처가 없어 비워 둔 항목(블룸버그 전용 등). 화면 각주로 띄운다.
    missing_sources: list[str]


# ── 매매일지 ─────────────────────────────────────────────────────────────────

class JournalTradeOut(BaseModel):
    """일지 날짜 근처(±3일)의 실제 체결. 판단과 실행이 며칠 어긋나는 건 흔하다."""

    trade_date: date
    side: str
    quantity: Decimal
    price: Decimal | None
    amount_local: Decimal | None
    currency: str


class JournalCreateIn(BaseModel):
    ticker: str | None = None
    asset_name: str | None = None
    entry_date: date
    kind: str = "ENTRY"
    title: str
    body: str | None = None
    conviction: int | None = None


class JournalUpdateIn(BaseModel):
    ticker: str | None = None
    entry_date: date | None = None
    kind: str | None = None
    title: str | None = None
    body: str | None = None
    conviction: int | None = None


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    ticker: str | None
    asset_name: str | None
    entry_date: date
    kind: str
    title: str
    body: str | None
    conviction: int | None
    created_at: datetime
    updated_at: datetime

    # ── 결과 ── 메모 옆에 "그래서 어떻게 됐는지"를 붙인다.
    #    ⚠️없으면 None 이다. 0 으로 채우면 "본전"으로 읽힌다.
    nearby_trades: list[JournalTradeOut]
    held: bool
    unrealized_pnl_krw: Decimal | None
    unrealized_return: Decimal | None
    realized_pnl_krw: Decimal | None


class JournalListOut(BaseModel):
    items: list[JournalEntryOut]
    total: int
    kinds: list[str]


class RealizedPnlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sell_date: date
    ticker: str
    asset_name: str | None
    sector: str | None
    currency: str
    quantity: Decimal
    avg_buy_price: Decimal | None
    avg_sell_price: Decimal | None
    buy_amount_local: Decimal | None
    sell_amount_local: Decimal | None
    commission_tax_local: Decimal | None
    pnl_local: Decimal | None
    pnl_krw: Decimal | None
    pnl_rate: Decimal | None
    buy_exchange_rate: Decimal | None
    sell_exchange_rate: Decimal | None
    fx_pnl_krw: Decimal | None


class RealizedPnlListOut(BaseModel):
    items: list[RealizedPnlOut]
    total: int
    # 주가 손익과 환 손익을 **분리해서** 내보낸다 — 합치면 무엇으로 벌었는지 모른다.
    pnl_krw: Decimal | None
    fx_pnl_krw: Decimal | None
    win_count: int
    loss_count: int
    first_sell_date: date | None
    last_sell_date: date | None


# ── 배당 ────────────────────────────────────────────────────────────────────

class DividendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pay_date: date
    ticker: str
    asset_name: str | None
    sector: str | None
    amount_krw: Decimal
    currency: str


class DividendMonthOut(BaseModel):
    month: str
    amount_krw: Decimal
    count: int


class DividendByTickerOut(BaseModel):
    ticker: str
    asset_name: str | None
    amount_krw: Decimal
    count: int


class DividendListOut(BaseModel):
    items: list[DividendOut]
    total: int
    total_amount_krw: Decimal | None
    monthly: list[DividendMonthOut]
    by_ticker: list[DividendByTickerOut]
    first_pay_date: date | None
    last_pay_date: date | None
