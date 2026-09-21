import uuid
from datetime import datetime
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
