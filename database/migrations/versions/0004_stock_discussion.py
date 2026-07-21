"""stock discussion (종토방) read-replica: sd_etf_meta, sd_posts, sd_author_labels, sd_sync_state

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sd_etf_meta",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "sd_posts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # src_id = 원본 SQLite id (비키 컬럼, D7): 정렬/신규감지 타이브레이크.
        sa.Column("src_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("post_id", sa.Text(), nullable=True),
        sa.Column("etf_code", sa.Text(), nullable=True),
        sa.Column("etf_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("post_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_date_raw", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("dislikes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sentiment", sa.Text(), nullable=True),
        sa.Column("sentiment_confidence", sa.Float(), nullable=True),
        sa.Column("sentiment_model", sa.Text(), nullable=True),
        sa.Column("sentiment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "source", "post_id", "etf_code", name="uq_sd_posts_source_postid_etfcode"
        ),
    )
    # 피드 정렬 전용 expression index (D7): ORDER BY COALESCE(post_date, crawled_at)
    # DESC NULLS LAST, src_id DESC 와 정확히 일치시켜 플래너가 사용하게 한다.
    op.execute(
        "CREATE INDEX ix_sd_posts_feed ON sd_posts "
        "(COALESCE(post_date, crawled_at) DESC NULLS LAST, src_id DESC)"
    )
    op.create_index("ix_sd_posts_etf_code", "sd_posts", ["etf_code"])
    op.create_index("ix_sd_posts_author", "sd_posts", ["author"])

    op.create_table(
        "sd_author_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source", "author", name="uq_sd_author_labels_source_author"
        ),
    )

    # 싱글턴 (id=1). last_ingest_at 이 staleness 판정 기준 (D5·D11).
    op.create_table(
        "sd_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("last_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_batch_id", sa.Text(), nullable=True),
        sa.Column("naver_last_ok", sa.DateTime(timezone=True), nullable=True),
        sa.Column("naver_last_error", sa.Text(), nullable=True),
        sa.Column("naver_consec_errors", sa.Integer(), nullable=True),
        sa.Column("toss_last_ok", sa.DateTime(timezone=True), nullable=True),
        sa.Column("toss_last_error", sa.Text(), nullable=True),
        sa.Column("toss_consec_errors", sa.Integer(), nullable=True),
        sa.Column("sentiment_labeled_total", sa.BigInteger(), nullable=True),
        sa.Column("sentiment_cost_usd_total", sa.Float(), nullable=True),
        sa.Column("spy_labels_total", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sd_sync_state")
    op.drop_table("sd_author_labels")
    op.drop_index("ix_sd_posts_author", table_name="sd_posts")
    op.drop_index("ix_sd_posts_etf_code", table_name="sd_posts")
    op.drop_index("ix_sd_posts_feed", table_name="sd_posts")
    op.drop_table("sd_posts")
    op.drop_table("sd_etf_meta")
