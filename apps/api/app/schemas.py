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
    포트폴리오 평가수익률과 같아진다 — 화면에서 검산이 된다.

    ⚠️반올림 때문에 마지막 자리는 어긋날 수 있다(8자리 반올림 → 17종목 합에서
      1e-8 수준). "정확히 일치"라고 쓰면 검산하다 버그로 오해하게 된다.
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
    #: 이 가격이 **얇은 데이마켓 체결**로 만들어졌는지. 값을 버리지는 않는다 —
    #: 한국 투자자가 실제로 체결할 수 있는 가격이다. 다만 정규장 가격인 척하게
    #: 두지 않는다(2026-09-22 실측: NVDA 데이마켓 5,119주 vs 정규장 8,152만주).
    thin_session: bool = False
    #: 그 봉의 거래량. thin_session 일 때 얼마나 얇은지 화면이 말할 수 있어야 한다.
    volume: Decimal | None = None
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


# ── 주문 내역 ────────────────────────────────────────────────────────────────

class OrderOut(BaseModel):
    """주문 한 건.

    ⚠️`improvement` 는 지정가 대비 체결가가 얼마나 **유리했나**(양수 = 유리).
      매수는 싸게, 매도는 비싸게 체결될수록 양수다 — 방향을 맞춰 두지 않으면
      매수·매도 부호가 반대라 평균이 의미를 잃는다. 미체결이면 None.
    """

    id: uuid.UUID
    ticker: str
    asset_name: str | None
    order_date: date
    order_time: str | None
    order_no: str
    side: str
    order_type: str | None
    currency: str
    # FILLED · PARTIAL · UNFILLED · CANCELLED (수량으로 판정)
    status: str
    order_quantity: Decimal | None
    filled_quantity: Decimal | None
    cancelled_quantity: Decimal | None
    remaining_quantity: Decimal | None
    order_price: Decimal | None
    filled_price: Decimal | None
    filled_amount: Decimal | None
    improvement: Decimal | None
    channel: str | None


class OrderListOut(BaseModel):
    items: list[OrderOut]
    # 아래 집계는 **필터와 무관하게 전체 기준**이다 — "미체결만 보기"로
    # 체결률이 0% 가 되면 그 숫자는 거짓말이다.
    total: int
    filled: int
    partial: int
    unfilled: int
    cancelled: int
    # 취소는 분모에서 뺀다. 내가 거둬들인 주문은 '체결 실패'가 아니다.
    fill_rate: Decimal | None
    avg_improvement: Decimal | None
    first_order_date: date | None
    last_order_date: date | None


# ── 입출금 ───────────────────────────────────────────────────────────────────

class CashflowEventOut(BaseModel):
    base_date: date
    # 입금/출금 중 실제로 있었던 쪽만 채운다 — 0 을 늘어놓으면 읽기 나쁘다.
    deposit_krw: Decimal | None
    withdrawal_krw: Decimal | None
    net_krw: Decimal
    # 그날 마감 예탁자산. 입금이 자산에 반영됐는지 눈으로 대조할 수 있다.
    assets_after_krw: Decimal | None


class CashflowMonthOut(BaseModel):
    month: str
    deposit_krw: Decimal
    withdrawal_krw: Decimal
    net_krw: Decimal


class CashflowOut(BaseModel):
    """입출금 이력 + "넣은 돈 대비 지금".

    ⚠️`gain_krw` 는 **금액 증감**이지 수익률(TWR)이 아니다. 성과 분석의 기간
      수익률과 다른 질문에 답한다 — 여기는 "얼마가 늘었나", 거기는 "얼마나 잘
      굴렸나". 입금 시점이 다르면 두 숫자는 당연히 갈린다.
    ⚠️`opening_balance_krw` 는 조회 구간 시작 전부터 있던 돈이다. 이걸 수익에
      섞으면 넣지도 않은 돈이 불어난 것처럼 보인다.
    """

    events: list[CashflowEventOut]
    monthly: list[CashflowMonthOut]
    total_deposit_krw: Decimal | None
    total_withdrawal_krw: Decimal | None
    net_deposit_krw: Decimal | None
    opening_balance_krw: Decimal | None
    current_assets_krw: Decimal | None
    gain_krw: Decimal | None
    gain_ratio: Decimal | None
    first_date: date | None
    last_date: date | None


# ── 매크로 지표 ──────────────────────────────────────────────────────────────

class MacroRowOut(BaseModel):
    """매크로 지표 한 줄.

    ⚠️`value` 의 의미가 `transform` 마다 다르다.
      · level    — 값 자체(실업률 4.1 → "4.1%")
      · yoy      — **전년 대비 변화율**(CPI 332.8 이 아니라 0.029 → "+2.9%")
      · mom_diff — 전월 대비 증감(비농업고용 158,913 이 아니라 150 → "+15만명")
    ⚠️`changes` 는 그 값의 **차이**다. yoy 지표의 변화는 "물가상승률이 몇 %p
      움직였나"이지 "물가가 몇 % 올랐나"가 아니다.
    """

    series_id: str
    name: str
    category: str
    transform: str
    unit: str
    note: str | None
    value: Decimal | None
    # 발표가 한 달 이상 늦는 지표가 있다. 화면은 이 날짜를 반드시 띄운다.
    as_of: date | None
    changes: dict[str, Decimal | None]


class MacroMonitorOut(BaseModel):
    rows: list[MacroRowOut]
    categories: list[str]
    periods: list[str]
    missing: list[str]
    notes: list[str]


# ── 벤치마크 비교 ────────────────────────────────────────────────────────────

class BenchmarkPointOut(BaseModel):
    """차트 한 점. 구간 시작을 100 으로 맞춘 지수다."""

    base_date: date
    portfolio: Decimal | None
    benchmarks: dict[str, Decimal | None]


class BenchmarkPeriodOut(BaseModel):
    """기간별 비교.

    ⚠️`benchmarks_krw` 가 비교의 정본이다. 내 계좌 수익률이 원화 기준이라
      달러 지수(`benchmarks_usd`)와 그대로 견주면 환율 변동이 실력처럼 보인다.
      USD 값은 "환율을 빼면 얼마였나"를 보려고 같이 낸다.
    """

    label: str
    start_date: date
    end_date: date
    observations: int
    portfolio: Decimal | None
    benchmarks_krw: dict[str, Decimal | None]
    benchmarks_usd: dict[str, Decimal | None]
    # 내 수익률 − 원화 환산 지수 수익률.
    excess: dict[str, Decimal | None]


class BenchmarkOut(BaseModel):
    series: list[BenchmarkPointOut]
    periods: list[BenchmarkPeriodOut]
    benchmarks: list[str]
    currency_note: str
    first_date: date | None
    last_date: date | None


# ── 실적 발표 일정 ───────────────────────────────────────────────────────────

class EarningsEventOut(BaseModel):
    report_date: date
    ticker: str
    company: str
    # 장전 / 장후 / 미정. 먼 날짜는 대개 "미정"이다.
    timing: str
    # ⚠️못 읽으면 None 이다. 0 으로 만들면 "EPS 0달러 전망"이라는 틀린 사실이 남는다.
    eps_forecast: Decimal | None
    estimate_count: int | None
    last_year_eps: Decimal | None
    market_cap: Decimal | None
    held: bool


class EpsHistoryOut(BaseModel):
    period: str
    kind: str
    consensus: Decimal | None
    actual: Decimal | None
    # 실제 − 컨센서스. 둘 중 하나라도 없으면 None.
    surprise: Decimal | None


class EarningsOut(BaseModel):
    """실적 일정. 내 종목과 시장 맥락을 나눠서 낸다.

    ⚠️전체는 60일에 4,201건이라 그대로 내보내지 않는다 — 내 종목은 전부,
      시장 맥락은 근시일 대형주만.
    """

    mine: list[EarningsEventOut]
    major: list[EarningsEventOut]
    window_days: int
    major_window_days: int
    total_scanned: int
    first_date: date
    last_date: date


# ── AI 생태계 지표 ───────────────────────────────────────────────────────────

class AcceleratorOut(BaseModel):
    """AI 가속기 한 종.

    ⚠️가격·성능이 **미공개인 칸이 흔하다**. None 으로 둔다 — 0 으로 채우면
      "무료"나 "성능 0"이라는 틀린 사실이 남는다.
    """

    name: str
    manufacturer: str
    kind: str | None
    release_date: date | None
    price_usd: Decimal | None
    fp16_flops: Decimal | None
    fp8_flops: Decimal | None
    memory_bytes: Decimal | None
    bandwidth_bytes: Decimal | None
    tdp_watts: Decimal | None
    # FP16 ÷ TDP. 데이터센터가 실제로 따지는 값이다.
    flops_per_watt: Decimal | None


class ManufacturerCountOut(BaseModel):
    name: str
    count: int


class PackageDownloadsOut(BaseModel):
    """AI SDK 다운로드 — "모델을 실제로 쓰고 있나"의 대리 지표."""

    package: str
    label: str
    last_week: int
    prior_week: int
    # 직전 주가 0 이면 나눌 수 없어 None.
    week_over_week: Decimal | None
    days: list[str]
    counts: list[int]


class AiDataOut(BaseModel):
    accelerators: list[AcceleratorOut]
    manufacturers: list[ManufacturerCountOut]
    total_accelerators: int
    downloads: list[PackageDownloadsOut]
    sources: list[str]


# ── 환노출 ───────────────────────────────────────────────────────────────────

class FxPositionOut(BaseModel):
    """종목별 환노출.

    ⚠️`estimated_entry_rate` 는 **추정**이다. 증권사가 매입 환율을 주지 않아
      매수 체결일의 일별 종가 환율로 가중평균했다. 모르면 None 이고,
      그때 `estimated_fx_pnl_krw` 도 None 이다 — 0 으로 두면 "환차 없음"이 된다.
    """

    ticker: str
    name: str | None
    currency: str
    market_value_krw: Decimal | None
    estimated_entry_rate: Decimal | None
    estimated_fx_pnl_krw: Decimal | None


class FxShockOut(BaseModel):
    """환율이 이만큼 움직이면 평가액이 얼마가 되나."""

    move: Decimal
    value_krw: Decimal | None
    delta_krw: Decimal | None


class FxExposureOut(BaseModel):
    """환노출 — 원화로 살아가며 달러 자산을 들고 있을 때의 위험.

    ⚠️`unrealized_fx_krw` 는 추정(매입 환율이 추정이므로), `realized_fx_krw` 는
      실측(증권사가 매수·매도 환율을 함께 준다)이다. 성격이 다르므로 합치지 않는다.
    """

    base_currency: str
    exposed_currency: str
    current_rate: Decimal | None
    exposed_value_krw: Decimal | None
    # 전체 평가금액 중 외화 비중. 1.0 이면 전부 환율에 노출돼 있다.
    exposure_ratio: Decimal | None
    positions: list[FxPositionOut]
    estimated_entry_rate: Decimal | None
    rate_change_ratio: Decimal | None
    unrealized_fx_krw: Decimal | None
    realized_fx_krw: Decimal | None
    shocks: list[FxShockOut]
    rate_as_of: date | None
    note: str


# ── 거래비용 ─────────────────────────────────────────────────────────────────

class CostBySideOut(BaseModel):
    side: str
    trade_count: int
    turnover: Decimal
    commission: Decimal
    tax: Decimal
    cost_ratio: Decimal | None


class CostByMonthOut(BaseModel):
    month: str
    trade_count: int
    turnover: Decimal
    cost: Decimal


class CostByTickerOut(BaseModel):
    ticker: str
    name: str | None
    trade_count: int
    turnover: Decimal
    cost: Decimal
    cost_ratio: Decimal | None


class TradingCostOut(BaseModel):
    """수수료·세금.

    ⚠️비용률의 분모는 **거래대금**이다. 평가액이 아니다 — 비용은 얼마를 들고
      있느냐가 아니라 얼마를 굴렸느냐에 붙는다.
    ⚠️`realized_pnl_krw` 는 참고용으로 나란히 둘 뿐, 비용과 **더하거나 빼지
      않는다**. 증권사 실현손익이 비용을 이미 반영했는지 확실하지 않다 —
      확실하지 않은 계산으로 한 숫자를 만들면 그게 더 나쁘다.
    ⚠️금액은 USD 다(거래일 환율이 없어 원화 환산을 만들지 않는다).
    """

    currency: str
    trade_count: int
    turnover: Decimal | None
    commission: Decimal | None
    tax: Decimal | None
    total_cost: Decimal | None
    cost_ratio: Decimal | None
    by_side: list[CostBySideOut]
    by_month: list[CostByMonthOut]
    by_ticker: list[CostByTickerOut]
    realized_pnl_krw: Decimal | None
    first_trade_date: date | None
    last_trade_date: date | None


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


# ── 월별 현금흐름 ────────────────────────────────────────────────────────────

class MonthlyCashflowRowOut(BaseModel):
    """한 달의 현금흐름 한 줄. **전부 원화다.**

    ★원천을 `account_daily_performance` 하나로 고정했다. trades 는 USD 이고
      거래일 환율이 없어서, 두 원천을 섞으면 통화가 섞인다. 반면 이 표는
      입금·출금·배당·수수료·매수·매도를 증권사가 **전부 원화로** 준다.

    ⚠️세 층을 더하지 않는다. 성격이 다르기 때문이다:
      · 외부 흐름(deposit/withdrawal) — 내 지갑 ↔ 계좌. 수익이 아니다.
      · 계좌가 만든 현금(dividend − cost) — 시장과 무관하게 실제로 생긴 현금.
      · 매매 회전(buy/sell) — 계좌 안에서 현금 ↔ 주식. 손익이 아니다.
    """

    month: str
    deposit_krw: Decimal
    withdrawal_krw: Decimal
    net_flow_krw: Decimal
    dividend_krw: Decimal
    cost_krw: Decimal
    net_cash_generated_krw: Decimal
    buy_krw: Decimal
    sell_krw: Decimal
    pnl_krw: Decimal
    opening_assets_krw: Decimal | None
    closing_assets_krw: Decimal | None
    #: 월초 + 순납입 + 손익 으로 설명되지 않는 나머지. 대부분 환율이다(아래 note).
    unexplained_krw: Decimal | None


class MonthlyCashflowOut(BaseModel):
    """월별 현금흐름.

    ⚠️`unexplained_krw` 를 **환차손익이라고 부르지 않는다.** 키움 일별성과의
      `exchange_rate` 가 530행 전부 비어 있어 환율을 실측할 수 없다. 다만
      "전월말 주식평가액 × 월간 USD/KRW 변화"와 맞춰 보면 상관계수 0.937
      (R²=0.878), 부호 15/17 일치, 절대합의 63%가 설명된다 — 그래서 '대부분
      환율'이라고는 말하되 환차 금액으로 적지는 않는다.
    """

    rows: list[MonthlyCashflowRowOut]
    total_deposit_krw: Decimal
    total_withdrawal_krw: Decimal
    total_dividend_krw: Decimal
    total_cost_krw: Decimal
    net_cash_generated_krw: Decimal
    total_buy_krw: Decimal
    total_sell_krw: Decimal
    months_dividend_covered_cost: int
    months_total: int
    first_month: str | None
    last_month: str | None
    note: str


# ── 세금 (해외주식 양도소득 · 배당소득) ──────────────────────────────────────

class TaxSaleOut(BaseModel):
    """매도 한 건의 양도차익. **체결일 환율로 환산한 원화 기준이다.**

    ⚠️`realized_pnl.buy_amount_krw` 를 취득가액으로 쓰면 안 된다. 그 칸은
      매수·매도를 **같은 환율**(실측 ≈1,372)로 환산한 값이라, 세법이 말하는
      "매수일 환율로 환산한 취득가액"이 아니다. 체결일 환율이 따로 들어와 있다.
    """

    ticker: str
    name: str | None
    sell_date: date
    quantity: Decimal
    proceeds_krw: Decimal
    cost_basis_krw: Decimal
    expense_krw: Decimal
    gain_krw: Decimal


class TaxYearOut(BaseModel):
    """한 해의 해외주식 양도소득 + 배당소득.

    ⚠️여기서는 **환차손익을 양도차익에 포함한다.** 다른 화면에서는 주가 손익과
      환차 손익을 섞지 말라고 해 놓고 여기서만 합치는 게 아니라, 질문이 다르다 —
      세법의 양도차익은 원화 기준 양도가액 − 취득가액이므로 환율 변동이
      **과세 대상 그 자체**다. 종목 선택이 좋았는지를 묻는 화면과는 다른 질문이다.
    """

    year: int
    sale_count: int
    proceeds_krw: Decimal
    cost_basis_krw: Decimal
    expense_krw: Decimal
    #: 체결일 환율로 계산한 양도차익(법정 정의).
    gain_krw: Decimal
    #: 증권사가 준 값(pnl_krw + fx_pnl_krw). 같은 것을 다르게 센 결과다.
    gain_krw_broker: Decimal
    #: 두 방식의 차이. **숨기지 않는다** — 0 이 아니면 둘 중 하나는 근사다.
    method_diff_krw: Decimal
    deduction_krw: Decimal
    taxable_base_krw: Decimal
    tax_rate: Decimal
    tax_krw: Decimal
    #: 기본공제까지 남은 여유. 음수면 이미 과세 구간이다.
    headroom_krw: Decimal
    dividend_krw: Decimal
    dividend_count: int
    #: 금융소득종합과세 기준(2,000만원). 넘으면 분리과세로 끝나지 않는다.
    comprehensive_threshold_krw: Decimal
    sales: list[TaxSaleOut]


class TaxOut(BaseModel):
    """세금 추정.

    ⚠️**신고 자료가 아니다.** 증권사 원장·기준환율·해외납부세액공제를 반영하지
      않았고, 배당이 세전인지 세후인지도 확인할 수 없다(notes 참고).
    """

    years: list[int]
    current: TaxYearOut | None
    notes: list[str]


# ── 공시 (SEC EDGAR) ─────────────────────────────────────────────────────────

class FilingOut(BaseModel):
    """공시 한 건.

    ⚠️`items` 는 8-K 에만 있다. "8-K 2.02" 는 아무 뜻도 전달하지 못하므로
      `item_labels` 로 사람 말을 같이 보낸다("실적 발표").
    """

    ticker: str
    company: str | None
    form: str
    form_label: str
    category: str
    filed_date: date
    report_date: date | None
    items: list[str]
    item_labels: list[str]
    url: str


class FilingTickerOut(BaseModel):
    """종목별 조회 결과.

    ⚠️`ok=False`(못 받았다)와 `filings=[]`(받았는데 없다)는 **다른 상태**다.
      ETF 는 실패가 아니라 개별 공시 대상이 아니다 — `reason` 으로 구분한다.
    """

    ticker: str
    name: str | None
    cik: str | None
    ok: bool
    reason: str | None
    filing_count: int
    insider_count: int
    #: 상한에 걸려 잘렸는지. 잘렸으면 화면이 그 사실을 말해야 한다.
    truncated: bool


class FilingsOut(BaseModel):
    """보유 종목 공시.

    ⚠️`source_ok=False` 면 화면이 "공시가 없습니다"라고 말하면 안 된다.
    """

    filings: list[FilingOut]
    tickers: list[FilingTickerOut]
    categories: list[str]
    window_days: int
    insider_window_days: int
    #: 내부자 서식(3/4/5/144)은 개별로 싣지 않고 센다. 실측 NVDA 최근 1001건 중
    #: 803건이 임원 서류라, 나열하면 나머지가 안 보인다.
    insider_total: int
    covered_count: int
    not_covered_count: int
    source_ok: bool
    user_agent_is_default: bool


# ── 기간 리포트 ──────────────────────────────────────────────────────────────

class ReportPeriodOut(BaseModel):
    """고를 수 있는 기간 하나."""

    key: str
    label: str
    start_date: date
    end_date: date


class ReportRealizedOut(BaseModel):
    ticker: str
    name: str | None
    pnl_krw: Decimal
    fx_pnl_krw: Decimal | None
    sell_count: int


class ReportPositionChangeOut(BaseModel):
    """그 기간에 새로 산 종목 / 전량 판 종목."""

    ticker: str
    name: str | None
    kind: str  # "NEW" | "CLOSED"
    first_date: date
    last_date: date
    trade_count: int


class ReportBenchmarkOut(BaseModel):
    name: str
    return_krw: Decimal | None
    excess: Decimal | None


class ReportOut(BaseModel):
    """한 기간에 무슨 일이 있었나.

    ⚠️**기간별 평가 기여도는 내지 않는다.** 종목별로 "이번 달 얼마 기여했나"를
      계산하려면 보유 종목의 일별 시계열이 있어야 하는데, 스냅샷이 어제부터
      6건뿐이다. 만들면 그럴듯해 보이지만 근거가 없다 — 대신 **실현손익**
      (증권사 실측)만 종목별로 낸다.

    ⚠️`unexplained_krw` 를 환차손익이라고 부르지 않는다(월별 현금흐름과 같은 이유).
    """

    periods: list[ReportPeriodOut]
    period: ReportPeriodOut | None
    #: 자산 분해 — 시작 + 순납입 + 손익 + 그 외 = 끝
    opening_assets_krw: Decimal | None
    closing_assets_krw: Decimal | None
    net_flow_krw: Decimal
    pnl_krw: Decimal
    unexplained_krw: Decimal | None
    #: 기간 TWR. 구간이 짧아 계산할 수 없으면 None(0 이 아니다).
    twr: Decimal | None
    benchmarks: list[ReportBenchmarkOut]
    #: 그 기간의 매매
    buy_count: int
    sell_count: int
    turnover_krw: Decimal
    cost_krw: Decimal
    dividend_krw: Decimal
    realized: list[ReportRealizedOut]
    realized_total_krw: Decimal
    changes: list[ReportPositionChangeOut]
    #: 가장 많이 오른 날 / 내린 날 (일별 손익 기준)
    best_day: date | None
    best_day_krw: Decimal | None
    worst_day: date | None
    worst_day_krw: Decimal | None
    trading_days: int
    notes: list[str]


# ── 보유 종목 뉴스 (구글 뉴스 RSS) ───────────────────────────────────────────

class NewsArticleOut(BaseModel):
    """기사 한 건.

    ⚠️한 기사가 **여러 보유 종목에 동시에 걸릴 수 있다**("Nvidia and AMD …").
      그때 같은 제목을 두 줄로 늘어놓으면 화면이 고장 난 것처럼 보이고, 하나를
      지우면 다른 종목의 뉴스가 사라진다. 그래서 한 줄로 합치고 종목을 다 싣는다.
    """

    tickers: list[str]
    companies: list[str]
    title: str
    publisher: str | None
    published_at: datetime | None
    url: str


class NewsTickerOut(BaseModel):
    """종목별 조회 결과.

    ⚠️`ok=False`(못 받았다)와 `article_count=0`(받았는데 없다)은 다른 상태다.
      `covered=False` 는 또 다른 상태 — 아예 대상이 아니라는 뜻이다(ETF).
    """

    ticker: str
    name: str | None
    company: str | None
    covered: bool
    ok: bool
    reason: str | None
    article_count: int
    filtered_out: int


class NewsOut(BaseModel):
    """보유 종목 뉴스.

    ⚠️`source_ok=False` 면 화면이 "뉴스가 없습니다"라고 말하면 안 된다.
    """

    articles: list[NewsArticleOut]
    tickers: list[NewsTickerOut]
    window_days: int
    covered_count: int
    not_covered_count: int
    filtered_total: int
    source_ok: bool
    notes: list[str]


# ── 알림 ─────────────────────────────────────────────────────────────────────

class AlertKindOut(BaseModel):
    key: str
    label: str
    hint: str
    needs_ticker: bool
    #: "price" | "percent" | "days" | None
    unit: str | None


class AlertRuleIn(BaseModel):
    kind: str
    ticker: str | None = None
    threshold: Decimal | None = None
    memo: str | None = None
    enabled: bool = True


class AlertRulePatch(BaseModel):
    threshold: Decimal | None = None
    memo: str | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    """규칙 하나와 **지금** 판정 결과.

    ⚠️`state` 는 셋이다 — TRIGGERED / OK / **UNKNOWN**. 잴 수 없었는데
      "미충족"이라고 적으면 화면이 괜찮다고 거짓말을 한다.
    """

    id: uuid.UUID
    kind: str
    kind_label: str
    ticker: str | None
    name: str | None
    threshold: Decimal | None
    unit: str | None
    enabled: bool
    memo: str | None
    state: str
    actual: Decimal | None
    message: str
    #: 이 상태가 된 시각(기록). 판정의 근거가 아니다.
    triggered_since: datetime | None


class AlertsOut(BaseModel):
    """알림 규칙 목록 + 지금 판정.

    ⚠️`delivery_configured` 가 False 면 **화면이 "알림을 보냈다"고 말하면 안 된다.**
      규칙을 세우고 판정하는 데까지만 동작한다.
    """

    rules: list[AlertRuleOut]
    kinds: list[AlertKindOut]
    triggered_count: int
    unknown_count: int
    disabled_count: int
    delivery_configured: bool
    notes: list[str]


# ── 시장 뉴스 (주제별) ───────────────────────────────────────────────────────

class TopicArticleOut(BaseModel):
    topic: str
    topic_label: str
    title: str
    publisher: str | None
    published_at: datetime | None
    url: str
    #: 제목에 걸린 내 보유 종목. 있으면 보유종목 뉴스에서 이미 봤을 수 있다.
    holdings: list[str]


class TopicOut(BaseModel):
    key: str
    label: str
    query: str
    ok: bool
    reason: str | None
    article_count: int
    filtered_out: int


class MarketNewsOut(BaseModel):
    """시장 뉴스 — 내 포지션이 아니라 판이 어떻게 돌아가는가.

    ⚠️`source_ok=False` 면 화면이 "뉴스가 없습니다"라고 말하면 안 된다.
    """

    articles: list[TopicArticleOut]
    topics: list[TopicOut]
    lang: str
    window_days: int
    filtered_total: int
    holdings_hit_count: int
    source_ok: bool
    notes: list[str]
