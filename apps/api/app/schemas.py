import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TestJobRequest(BaseModel):
    payload: dict[str, Any] | None = None


class InternalJobRequest(BaseModel):
    job_type: str = Field(min_length=1)
    payload: dict[str, Any] | None = None


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


# ---------------------------------------------------------------------------
# Kiwoom portfolio (round 2)
#
# NUMERIC columns are serialized as JSON numbers (float) for UI simplicity;
# see contract-kiwoom.md §6 (precision caveat).
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    account_id: uuid.UUID
    asset_id: uuid.UUID
    broker: str | None
    country: str | None
    market: str | None
    ticker: str | None
    asset_name: str | None
    asset_type: str | None
    currency: str | None
    quantity: float | None
    available_quantity: float | None
    average_purchase_price: float | None
    purchase_amount_local: float | None
    current_price: float | None
    market_value_local: float | None
    unrealized_pnl_local: float | None
    unrealized_return: float | None
    exchange_rate: float | None
    market_value_krw: float | None
    unrealized_pnl_krw: float | None
    as_of: datetime | None
    source_job_id: uuid.UUID | None


class PositionListOut(BaseModel):
    items: list[PositionOut]
    total: int


class BrokerageConnectionOut(BaseModel):
    id: uuid.UUID
    broker_code: str
    connection_name: str
    environment: str
    status: str
    last_connected_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None
    credentials_configured: bool


class BrokerageConnectionListOut(BaseModel):
    items: list[BrokerageConnectionOut]


class SyncTriggerOut(BaseModel):
    job_id: uuid.UUID
    status: str
    reused: bool


class PortfolioSummaryOut(BaseModel):
    total_assets_krw: float
    securities_value_krw: float
    cash_value_krw: float
    total_purchase_amount_krw: float
    total_unrealized_pnl_krw: float
    unrealized_return_pct: float | None
    position_count: int
    account_count: int


class AccountSummaryOut(BaseModel):
    id: uuid.UUID
    account_name: str | None
    account_number_masked: str | None
    account_type: str | None
    base_currency: str | None
    total_assets_krw: float | None
    last_synced_at: datetime | None


class CashBalanceOut(BaseModel):
    account_id: uuid.UUID
    currency: str
    cash_balance: float | None
    available_cash: float | None
    exchange_rate: float | None
    cash_krw: float | None
    # Kiwoom's 추정예탁자산 (account-level: cash + securities). NOT this row's cash
    # in KRW — never sum it as cash (that double-counts securities). Reconciliation
    # figure only; the UI must use cash_krw.
    estimated_total_assets_krw: float | None
    as_of: datetime | None


class MarketBreakdownOut(BaseModel):
    country: str | None
    securities_value_krw: float
    position_count: int


class ConnectionBriefOut(BaseModel):
    id: uuid.UUID
    status: str
    credentials_configured: bool
    last_error: str | None


class PortfolioOverviewOut(BaseModel):
    summary: PortfolioSummaryOut
    accounts: list[AccountSummaryOut]
    positions: list[PositionOut]
    cash_balances: list[CashBalanceOut]
    market_breakdown: list[MarketBreakdownOut]
    last_synced_at: datetime | None
    sync_status: str
    connection: ConnectionBriefOut | None


class AccountPortfolioOut(BaseModel):
    account: AccountSummaryOut
    positions: list[PositionOut]
    cash_balances: list[CashBalanceOut]
    last_synced_at: datetime | None
