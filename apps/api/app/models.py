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
    # ★(0019) 큐별로 worker 를 따로 띄운다 — LLM 한 건(수 분)이 공시 수집을 막지 않게.
    queue: Mapped[str] = mapped_column(
        String, nullable=False, default="default", server_default=text("'default'")
    )
    # 작업 중 주기적으로 갱신. 끊기면 죽은 작업으로 보고 되살린다(attempts 상한까지).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_queue_status_created_at", "queue", "status", "created_at"),
    )


class SourceStatus(Base):
    """원천·worker 의 마지막 성공/실패(0019). 실패는 종류(403/429/timeout/other)로."""

    __tablename__ = "source_status"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


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
    # 증권사가 쓰는 거래소 코드(키움 ND/NY/NA). 우리 분류(country/market)와 다른 축이라
    # 별도로 둔다 — 배당 조회(usa21730)가 이 값을 **필수**로 요구한다.
    broker_exchange_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # AI/Tech 밸류체인 3단계 분류(alembic 0010). `sector`(전통 섹터)와 **다른 축**이다 —
    # 같은 종목이 두 축에서 다른 자리에 놓이고, 둘 다 볼 이유가 있다.
    tech_l1: Mapped[str | None] = mapped_column(String, nullable=True)
    tech_l2: Mapped[str | None] = mapped_column(String, nullable=True)
    tech_l3: Mapped[str | None] = mapped_column(String, nullable=True)
    tech_source: Mapped[str | None] = mapped_column(String, nullable=True)
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
        Index("ix_assets_tech_l1", "tech_l1"),
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

    ⚠️`trade_no` 는 증권사 안에서 **일자별로 리셋**된다. 게다가 국내와 해외가
      번호를 따로 매겨 같은 날 `000000001` 이 둘 생긴다 — 유일키는
      계좌+**시장**+일자+번호다(alembic 0018).
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
    market: Mapped[str] = mapped_column(String, nullable=False)  # KR / US
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


class AccountDailyPerformance(Base):
    """계좌 일별 성과 (alembic 0008, 키움 usa21670).

    증권사가 이미 들고 있는 과거 시계열이다 — 우리가 매일 스냅샷을 찍어 쌓지 않는다.
    ⚠️거래가 없는 날도 행이 온다(값이 전날과 같다). 차트에서 '변동 없음'과 '데이터
      없음'을 구분해야 하면 pnl_krw==0 으로 판단하지 말고 날짜 연속성을 본다.
    """

    __tablename__ = "account_daily_performance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    base_date: Mapped[date] = mapped_column(Date, nullable=False)
    deposit_assets_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    stock_value_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    cumulative_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    dividend_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    commission_tax_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    buy_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    sell_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    deposit_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    withdrawal_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    return_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "base_date", name="uq_daily_perf_account_date"),
        Index("ix_daily_perf_account_date", "account_id", "base_date"),
    )


class RealizedPnl(Base):
    """실현손익 한 건 (alembic 0008, 키움 ust21530).

    증권사가 **매도일 × 종목**으로 집계해 준다(매도평균가) — 그래서 그게 자연키다.
    ⚠️환차손익(fx_pnl_krw)은 주가 손익과 **별개**다. 합치면 종목이 올라서 번 건지
      환율로 번 건지 구분이 사라진다(실측: SGOV 외화 -$7.58 / 환차 +₩195,692).
    """

    __tablename__ = "realized_pnl"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sell_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    avg_buy_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    avg_sell_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    buy_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    sell_amount_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    commission_tax_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    pnl_local: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    buy_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    sell_amount_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    commission_tax_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    pnl_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    buy_exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    sell_exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    fx_pnl_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "sell_date", "ticker", name="uq_realized_account_date_ticker"),
        Index("ix_realized_account_date", "account_id", "sell_date"),
    )


class Dividend(Base):
    """배당 수령 한 건 (alembic 0009, 키움 usa21730 의 dvid_amt).

    ⚠️배당 전용 TR 이 없다 — 일별 종목수익률 응답에 섞여 온다. 배당이 0 인 날이
      대부분이라 0 인 행은 저장하지 않는다.
    ⚠️금액은 증권사가 **원화**로 준다. 외화 원금액은 이 TR 이 주지 않는다.
    """

    __tablename__ = "dividends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_krw: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'KRW'"))
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "pay_date", "ticker", name="uq_dividends_account_date_ticker"),
        Index("ix_dividends_account_date", "account_id", "pay_date"),
    )


class RebalanceTarget(Base):
    """리밸런싱 목표 비중 (alembic 0015).

    ⚠️`assets` FK 를 걸지 않는다 — 아직 사지 않은 종목에도 목표를 둘 수 있어야 한다.
    ⚠️`target_weight` 는 소수다(0.20 = 20%). 합이 1을 넘어도 **막지 않는다** —
      막으면 목표를 옮기는 중간 상태를 저장할 수 없다. 대신 화면이 말한다.
    """

    __tablename__ = "rebalance_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OpsAlertState(Base):
    """운영 트립와이어 상태 (alembic 0027, core/ops_alerts.py). 열림 = `resolved_at IS NULL`."""

    __tablename__ = "ops_alert_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertRule(Base):
    """알림 규칙 (alembic 0014).

    ★전달(텔레그램 등)은 아직 없다. 그래도 조건을 세우고 **지금 충족하는지**
      판정하는 부분은 지금 데이터로 전부 된다.

    ⚠️`assets` 를 FK 로 걸지 않는다 — 아직 사지 않은 종목에도 걸 수 있어야 한다.

    ⚠️`last_state` 를 **판정 근거로 쓰지 않는다.** 판정은 언제나 지금 시세로
      다시 한다. 캐시로 쓰면 시세가 바뀌어도 화면이 옛 상태를 말한다.
    """

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: NULL 이면 포트폴리오 전체에 거는 규칙이다.
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_state: Mapped[str | None] = mapped_column(String, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triggered_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_alert_rules_ticker", "ticker"),
        Index("ix_alert_rules_enabled", "enabled"),
    )


class WatchlistItem(Base):
    """관심종목 — 아직 안 산 종목도 담는 보드.

    ⚠️보유 종목을 여기 복제하지 않는다. `current_positions` 가 정본이고, 복제하면
      판 뒤에도 남거나 둘이 어긋난다. 화면에서 합쳐 보여줄 뿐이다.
    ⚠️`assets` 를 FK 로 걸지 않는다 — assets 행은 매수해야 생기는데, 안 산 종목을
      담는 게 이 화면의 요점이다.
    """

    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class JournalEntry(Base):
    """매매일지 한 편 — 진입 근거 · 청산 근거 · 복기.

    ⚠️`trades` 에 FK 를 걸지 않는다. 체결 이력은 동기화마다 다시 적재돼 행 id 가
      안정적이지 않고(SKHY 매도가 며칠 뒤에 들어온 사례), 살지 말지 고민만 한
      종목에도 메모를 남겨야 하는데 그런 종목엔 체결 자체가 없다.
      ticker + entry_date 로 느슨하게 묶고 화면에서 체결을 찾아 붙인다.
    """

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 종목 무관 메모도 일지다 — 시장 전체에 대한 기록.
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # 기록한 날이 아니라 **그 판단을 한 날**. 소급 기록을 허용한다.
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'ENTRY'"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 확신도 1~5. nullable 이다 — 강제하면 아무 숫자나 찍힌다.
    conviction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ── 계획 (alembic 0016) ─────────────────────────────────────────────
    # ⚠️전부 nullable 이다. 계획 없이 적는 메모가 대부분이고, 0 을 채우면
    #   "0주 계획"이라는 없는 사실이 생긴다.
    planned_side: Mapped[str | None] = mapped_column(String, nullable=True)
    planned_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    planned_price_krw: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Order(Base):
    """주문 내역 — 체결 이력이 감추는 것들(키움 ust21180).

    체결은 "성사된 것"만, 주문은 "하려고 한 것"을 전부 알려준다. 미체결·취소·
    슬리피지·주문 채널이 여기에만 있다.

    ⚠️assets 를 FK 로 걸지 않는다. 한 번도 체결된 적 없는 종목은 assets 행이 없다
      (실측: SKHYV 는 주문 3건 전부 미체결이라 보유·체결 어디에도 없다).
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("account_id", "order_date", "order_no", name="uq_orders_account_date_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_no: Mapped[str] = mapped_column(String, nullable=False)
    order_time: Mapped[str | None] = mapped_column(String, nullable=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    order_type: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'USD'"))
    order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    cancelled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    modified_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    remaining_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # ⚠️미체결이면 None 이다. 증권사는 0 으로 주는데 그대로 두면 "0달러 체결"이 된다.
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    filled_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    reserve_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )



class SeasonalitySeries(Base):
    """계절성 대상 시계열(0020). 시드: `database/seeds/seasonality_series.py`."""

    __tablename__ = "seasonality_series"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    grp: Mapped[str] = mapped_column(String, nullable=False)
    bbg_ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    yahoo_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    continuation: Mapped[str] = mapped_column(
        String, nullable=False, default="direct", server_default=text("'direct'")
    )
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class MonthlyClose(Base):
    """월말 종가(0020). 수익률은 **같은 source 안에서만** 낸다 — 원천끼리 수준을 잇지 않는다."""

    __tablename__ = "monthly_closes"

    series: Mapped[str] = mapped_column(
        String, ForeignKey("seasonality_series.key"), primary_key=True
    )
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # 'YYYY-MM'
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # (0021) 키에 포함 — 같은 달의 블룸버그·Yahoo 값을 둘 다 둔다(원천 전환 달의 기준값).
    source: Mapped[str] = mapped_column(String, primary_key=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


# ── SEC 공시(0022, 계획 A) — 원본 `13F기관내부자/db/filings.db` 의 표를 옮겼다 ──────────


class GuruRoster(Base):
    """13F 추적 대상. kind='guru' 는 활성·백필, kind='index'(퀀트·인덱스)는 비활성으로만."""

    __tablename__ = "guru_roster"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    guru_name: Mapped[str | None] = mapped_column(String, nullable=True)
    firm: Mapped[str] = mapped_column(String, nullable=False)
    filer_name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    backfill_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default=text("'pending'")
    )
    backfill_from: Mapped[date] = mapped_column(
        Date, nullable=False, default=date(2013, 4, 1), server_default=text("'2013-04-01'")
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecFiling(Base):
    __tablename__ = "sec_filings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    form_type: Mapped[str] = mapped_column(String, nullable=False)
    accession_number: Mapped[str] = mapped_column(String, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_of_report: Mapped[date | None] = mapped_column(Date, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    filer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    filer_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    watch_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    watch_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # 13F-HR/A: 'RESTATEMENT'(대체) | 'NEW HOLDINGS'(추가분, 합산)
    amendment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("accession_number", "form_type", name="uq_sec_filings_acc_form"),
        Index("ix_sec_filings_watch_form_period", "watch_cik", "form_type", "period_of_report"),
        Index("ix_sec_filings_issuer_form_date", "issuer_cik", "form_type", "filing_date"),
    )


class Holding13F(Base):
    __tablename__ = "holdings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    name_of_issuer: Mapped[str | None] = mapped_column(String, nullable=True)
    title_of_class: Mapped[str | None] = mapped_column(String, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String(9), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    shr_type: Mapped[str | None] = mapped_column(String, nullable=True)
    put_call: Mapped[str | None] = mapped_column(String, nullable=True)
    investment_discretion: Mapped[str | None] = mapped_column(String, nullable=True)
    vote_sole: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    vote_shared: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    vote_none: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)

    __table_args__ = (
        Index("ix_holdings_13f_acc", "accession_number"),
        Index("ix_holdings_13f_cusip", "cusip"),
    )


class Form4Transaction(Base):
    __tablename__ = "form4_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    insider_name: Mapped[str | None] = mapped_column(String, nullable=True)
    insider_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    insider_role: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    transaction_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    transaction_description: Mapped[str | None] = mapped_column(String, nullable=True)
    buy_sell: Mapped[str | None] = mapped_column(String, nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    transaction_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    shares_owned_after: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    ownership_type: Mapped[str | None] = mapped_column(String, nullable=True)
    acquired_disposed: Mapped[str | None] = mapped_column(String(1), nullable=True)
    is_derivative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_open_market: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_option_exercise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # 10b5-1 계획매매 — 순매수에서 뺀다(장내 매도의 73%, 실측)
    is_planned_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_form4_acc", "accession_number"),
        Index("ix_form4_issuer_date", "issuer_cik", "transaction_date"),
    )


class OwnershipEvent(Base):
    __tablename__ = "ownership_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    subject_name: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cusip: Mapped[str | None] = mapped_column(String(9), nullable=True)
    filer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_amendment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_activist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    __table_args__ = (Index("ix_ownership_events_acc", "accession_number"),)


class CusipMap(Base):
    __tablename__ = "cusip_map"

    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[str] = mapped_column(String, nullable=False, default="none", server_default=text("'none'"))
    figi: Mapped[str | None] = mapped_column(String, nullable=True)
    # 0023 — SEC 업종코드와 그로 정한 섹터('' = 찾아봤지만 없음)
    sic: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


# ── 실적 모니터 (0024, 계획 B1) ────────────────────────────────────────────────
# ⚠️`quarter` 는 발표일로 정한 달력 분기 라벨(원본 `derive_fiscal_quarter`) — 회사 회계분기가 아니다.


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (UniqueConstraint("ticker", "quarter", name="uq_earnings_events_ticker_quarter"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    quarter: Mapped[str] = mapped_column(String(8), nullable=False)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    timing: Mapped[str | None] = mapped_column(String(8), nullable=True)
    eps_forecast: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    n_estimates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue_forecast: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    revenue_forecast_status: Mapped[str | None] = mapped_column(String, nullable=True)
    revenue_forecast_source: Mapped[str | None] = mapped_column(String, nullable=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


class EarningsResult(Base):
    __tablename__ = "earnings_results"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("earnings_events.id", ondelete="CASCADE"), primary_key=True
    )
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    revenue_actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    eps_surprise_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    revenue_surprise_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    filing_accession: Mapped[str | None] = mapped_column(String, nullable=True)
    filing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reaction_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    reaction_window: Mapped[str | None] = mapped_column(String, nullable=True)
    reaction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EarningsGuidance(Base):
    __tablename__ = "earnings_guidance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("earnings_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    prior_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    prior_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class EarningsWatchpoint(Base):
    __tablename__ = "earnings_watchpoints"
    __table_args__ = (UniqueConstraint("ticker", "quarter", "rank", name="uq_earnings_watchpoints"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    quarter: Mapped[str] = mapped_column(String(8), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    point: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )


class AiMetricSnapshot(Base):
    """AI Key Data 스냅샷(0025) — 과거를 다시 받을 수 없는 VS Code·PyPI 전용.

    ⚠️npm·Ramp·OpenRouter·Epoch 은 여기 적지 않는다(라이브 조회 + 메모리 캐시, 계획 §12-3).
    같은 날 재실행은 덮어쓴다. 음수 델타도 원값 그대로(차분은 API 몫).
    """

    __tablename__ = "ai_metric_snapshot"

    source: Mapped[str] = mapped_column(String, primary_key=True)   # 'vscode' | 'pypi'
    series: Mapped[str] = mapped_column(String, primary_key=True)   # ext id | 패키지명
    date: Mapped[date] = mapped_column(Date, primary_key=True)      # 스냅샷 날짜(KST)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VideoDigest(Base):
    """영상 요약(0026) — Plaud 녹음 `[youtube_YYMMDD_채널]` 한 건의 한 문단 이슈 요약.

    status: done(요약 있음) · pending(Plaud 전사 없음 — 다음 실행에서 다시) · failed(error 에 이유).
    ⚠️요약이 없으면 summary_ko 는 비어 있다 — 실패 문구를 요약 칸에 쓰지 않는다. 전사문은 저장하지 않는다.
    """

    __tablename__ = "video_digests"
    __table_args__ = (
        UniqueConstraint("plaud_file_id", name="uq_video_digests_plaud_file_id"),
        Index("ix_video_digests_video_date", "video_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plaud_file_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_tag: Mapped[str] = mapped_column(String, nullable=False)
    video_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_ko: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'pending'"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()")
    )
