"""영상 요약 — Plaud 로 녹음한 유튜브 영상의 한 문단 이슈 요약

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-01

★사용자가 유튜브 영상을 Plaud 에 녹음해 `[youtube_YYMMDD_채널]` 제목으로 올린다. 매일 아침(07:40 KST 이후 한 번)
  worker(llm 큐, `PLAUD_VIDEO`)가 최근 14일 녹음 중 규칙에 맞는 새 것을 받아 `claude -p` 로 한 문단 요약한다.
  화면: /news/video.

status:
  · done    — summary_ko 가 있다. 다시 처리하지 않는다.
  · pending — Plaud 전사가 아직 없다(전사 전이거나 앱에서 전사를 안 만들었다). 다음 실행에서 다시 본다. LLM 을 부르지 않는다.
  · failed  — LLM 실패·형식 오류 등. error 에 이유. attempts 3번까지 다음 실행에서 다시.
⚠️전사문 원문은 저장하지 않는다 — 요약에만 쓰고 Plaud 에 원본이 있다.
⚠️recorded_at 은 UTC aware 로 저장한다(Plaud 는 시간대 없는 UTC 문자열을 준다 — client.to_utc).
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_digests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plaud_file_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source_tag", sa.String(), nullable=False),
        sa.Column("video_date", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_ko", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("plaud_file_id", name="uq_video_digests_plaud_file_id"),
    )
    op.create_index("ix_video_digests_video_date", "video_digests", ["video_date"])


def downgrade() -> None:
    op.drop_index("ix_video_digests_video_date", table_name="video_digests")
    op.drop_table("video_digests")
