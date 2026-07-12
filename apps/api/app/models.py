import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (Index("ix_jobs_status_created_at", "status", "created_at"),)


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[str] = mapped_column(String, nullable=False)
    step: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # SQLAlchemy reserves the ``metadata`` attribute on declarative classes, so the
    # ORM attribute is ``meta`` while the physical column stays ``metadata``.
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (Index("ix_job_logs_job_id_created_at", "job_id", "created_at"),)


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (Index("ix_imports_job_id", "job_id"),)


# ---------------------------------------------------------------------------
# Kiwoom portfolio (round 2)
#
# Money/qty precisions per contract-kiwoom.md §3: quantity & prices
# NUMERIC(20, 6), amounts NUMERIC(20, 2), exchange_rate NUMERIC(12, 4),
# unrealized_return NUMERIC(10, 4). KRW-converted and FX-dependent columns are
# nullable (US rows may lack an FX rate; domestic uses rate 1.0).
# ---------------------------------------------------------------------------


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (UniqueConstraint("code", name="uq_brokers_code"),)


class BrokerageConnection(Base):
    __tablename__ = "brokerage_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokers.id"), nullable=False
    )
    connection_name: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="CONFIGURED", server_default=text("'CONFIGURED'")
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokers.id"), nullable=False
    )
    brokerage_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokerage_connections.id"), nullable=False
    )
    external_account_id: Mapped[str] = mapped_column(String, nullable=False)
    account_number_masked: Mapped[str | None] = mapped_column(String, nullable=True)
    account_name: Mapped[str | None] = mapped_column(String, nullable=True)
    account_type: Mapped[str | None] = mapped_column(String, nullable=True)
    base_currency: Mapped[str] = mapped_column(
        String, nullable=False, default="KRW", server_default=text("'KRW'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "brokerage_connection_id",
            "external_account_id",
            name="uq_accounts_connection_external",
        ),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint("country", "market", "ticker", name="uq_assets_country_market_ticker"),
    )


class CurrentPosition(Base):
    __tablename__ = "current_positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    available_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    average_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    purchase_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    market_value_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_pnl_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_return: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    market_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint("account_id", "asset_id", name="uq_current_positions_account_asset"),
    )


class AccountBalance(Base):
    __tablename__ = "account_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    available_cash: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_purchase_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_market_value_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_evaluation_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_unrealized_pnl_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    total_evaluation_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_account_balances_account_currency"),
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_currency: Mapped[str] = mapped_column(
        String, nullable=False, default="KRW", server_default=text("'KRW'")
    )
    cash_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    securities_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_assets_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_purchase_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_unrealized_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_portfolio_snapshots_account_snapshot_at", "account_id", "snapshot_at"),
    )


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    average_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    market_value_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    market_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_pnl_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (Index("ix_position_snapshots_snapshot", "portfolio_snapshot_id"),)


class BrokerApiRawResponse(Base):
    __tablename__ = "broker_api_raw_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokers.id"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    api_category: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_name: Mapped[str] = mapped_column(String, nullable=False)
    response_file_path: Mapped[str] = mapped_column(String, nullable=False)
    response_hash: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (Index("ix_broker_api_raw_responses_job_id", "job_id"),)
