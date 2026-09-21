import uuid
from datetime import date, datetime, timezone

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
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


# ── 종토방(stock discussion) 읽기 서빙 사본 (push-ingest, alembic 0004·0005) ──
# 정본 = 개발 PC SQLite. 아래 테이블들은 push 로 받은 read-replica 다.


class SdEtfMeta(Base):
    __tablename__ = "sd_etf_meta"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SdPost(Base):
    __tablename__ = "sd_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # src_id = 원본 SQLite id (비키 컬럼, D7): 정렬/신규감지 타이브레이크.
    src_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    etf_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    etf_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    post_date_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dislikes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint(
            "source", "post_id", "etf_code", name="uq_sd_posts_source_postid_etfcode"
        ),
        # 피드 정렬 전용 expression index (DDL 은 마이그레이션에서 raw SQL 로 생성).
        Index(
            "ix_sd_posts_feed",
            text("COALESCE(post_date, crawled_at) DESC NULLS LAST"),
            text("src_id DESC"),
        ),
        Index("ix_sd_posts_etf_code", "etf_code"),
        Index("ix_sd_posts_author", "author"),
    )


class SdAuthorLabel(Base):
    __tablename__ = "sd_author_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 원본 SQLite 는 (author,source,label) 유니크 — 한 작성자 복수 라벨 허용.
        UniqueConstraint(
            "source", "author", "label", name="uq_sd_author_labels_source_author_label"
        ),
    )


class SdSyncState(Base):
    __tablename__ = "sd_sync_state"

    # 싱글턴 (id=1). last_ingest_at 이 staleness 판정 기준 (D5·D11).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_batch_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    naver_last_ok: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    naver_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    naver_consec_errors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    toss_last_ok: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    toss_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    toss_consec_errors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment_labeled_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sentiment_cost_usd_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_labels_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── 개인 계좌 포트폴리오 (alembic 0002) ────────────────────────────────────────
# 테이블은 0002_kiwoom_portfolio 에서 이미 만들어져 있었지만 ORM 매핑이 없어
# 어느 코드도 읽지 못하고 있었다. 2026-09-21 에 개인 대시보드를 붙이면서 매핑한다.
#
# 읽기 전용 매핑이다 — 쓰기는 collector/worker 가 한다. 그래서 default/onupdate 를
# 달지 않고 server_default 만 반영한다(대시보드가 실수로 값을 만들어내지 않게).
#
# ⚠️금액은 전부 Numeric 이다. float 로 바꾸지 말 것 — 평가금액·손익을 더하는
#   화면에서 원 단위 오차가 눈에 보인다. API 경계에서 Decimal→str 로 내보낸다.


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
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
    # CONFIGURED / CONNECTED / ERROR — 연동 화면의 상태 칩이 이 값을 읽는다.
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'CONFIGURED'")
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
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
    # 계좌번호는 마스킹된 형태만 들고 있는다 — 화면에 원본을 띄울 이유가 없다.
    account_number_masked: Mapped[str | None] = mapped_column(String, nullable=True)
    account_name: Mapped[str | None] = mapped_column(String, nullable=True)
    account_type: Mapped[str | None] = mapped_column(String, nullable=True)
    base_currency: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'KRW'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint(
            "brokerage_connection_id",
            "external_account_id",
            name="uq_accounts_connection_external_id",
        ),
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # asset_type 은 **자산군**(STOCK/BOND/DERIVATIVE/OTHER, alembic 0003).
    asset_type: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    # 섹터(alembic 0006). 증권사는 섹터를 주지 않아 따로 채운다.
    # ⚠️미분류는 NULL 로 둔다 — '기타'로 채우면 분류가 끝났는지 알 수 없다.
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    # SEED / MANUAL / 외부출처. 자동 분류가 사람이 고친 값을 덮지 않게 하는 표식.
    sector_source: Mapped[str | None] = mapped_column(String, nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("country", "market", "ticker", name="uq_assets_country_market_ticker"),
        Index("ix_assets_sector", "sector"),
    )


class CurrentPosition(Base):
    """계좌×종목 현재 보유 — 수집기가 매 동기화마다 덮어쓰는 최신 상태 한 줄."""

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
    # 환율은 수집 시점에 증권사가 준 값을 그대로 박아 둔다 — 화면이 다시 계산하면
    # 같은 화면의 합계와 종목별 수치가 어긋난다.
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    market_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    unrealized_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "asset_id", name="uq_current_positions_account_asset"),
    )


class AccountBalance(Base):
    """계좌×통화 예수금과 합계. 외화 계좌는 통화별로 행이 갈린다."""

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
    total_evaluation_amount_local: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True
    )
    total_unrealized_pnl_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    total_evaluation_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_account_balances_account_currency"),
    )


class PortfolioSnapshot(Base):
    """계좌별 일별(또는 동기화별) 총자산 스냅샷 — 자산 추이·수익률(TWR)의 원천."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_currency: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'KRW'")
    )
    cash_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    securities_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_assets_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_purchase_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_unrealized_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_portfolio_snapshots_account_snapshot_at", "account_id", "snapshot_at"),
    )


class Trade(Base):
    """체결 한 건 (alembic 0007).

    ⚠️`trade_no` 는 증권사 안에서 **일자별로 리셋**된다. 유일키는 계좌+일자+번호다.
    ⚠️해외 거래는 원화 금액이 0 으로 오므로 amount_krw 는 NULL 일 수 있다 —
      0 으로 채우면 "거래금액 0원"이라는 틀린 사실이 화면에 뜬다.
    """

    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    # 이미 판 종목도 남는다 — 종목 마스터가 없을 수 있어 nullable.
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_no: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # BUY / SELL
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    settlement_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    commission_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    tax_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    processed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "trade_date", "trade_no", name="uq_trades_account_date_no"),
        Index("ix_trades_account_date", "account_id", "trade_date"),
        Index("ix_trades_ticker", "ticker"),
    )
