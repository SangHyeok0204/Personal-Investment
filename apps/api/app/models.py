import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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
