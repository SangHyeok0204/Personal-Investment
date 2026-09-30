"""AI Key Data 스냅샷 — VS Code 누적 설치수·PyPI 최근 다운로드(S5)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-27

★.omc/plans/research-menu-revamp.md §11·§12-3.
  AI Key Data 6개 소스 중 npm·Ramp·OpenRouter·tool_calling·Epoch 은 과거를 매번 다시
  받을 수 있어 **라이브 조회 + 메모리 캐시**로 둔다. 테이블이 필요한 건 현재값만 주는
  두 소스뿐이다:
    · vscode — 마켓은 누적 설치수만 준다. 놓친 날은 복구할 수 없다.
    · pypi   — pypistats 는 180일만 준다. 장기 이력은 스냅샷을 쌓아야 남는다.

long 포맷 한 표: (source, series, date) → value, 부가 필드는 `extra`(jsonb).
  vscode: value=install, extra={update_count, download_count, version, last_updated, avg_rating, rating_count, snapshot_utc}
  pypi:   value=last_day, extra={last_week, last_month}
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_metric_snapshot",
        sa.Column("source", sa.String(), primary_key=True),
        sa.Column("series", sa.String(), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(24, 4), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_metric_snapshot")
