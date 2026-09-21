"""매매일지 — 진입 근거 · 청산 근거 · 복기

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-22

★일반 메모장이 아니다. 종목과 날짜에 묶여서, 화면이 그 메모를 **실제 체결·손익
  옆에 붙여** 보여줄 수 있어야 쓸모가 생긴다. "왜 샀는지" 옆에 "그래서 어떻게
  됐는지"가 같이 보이지 않으면 복기가 안 된다.

⚠️`trades` 에 FK 를 걸지 않는다. 두 가지 이유다:
    · 체결 이력은 동기화 때마다 다시 적재되므로 행 id 가 안정적이지 않다.
      실제로 SKHY 매도 체결이 며칠 뒤에야 들어온 것을 관측했다.
    · 살지 말지 **고민만 한 종목**에도 메모를 남길 수 있어야 한다. 체결이
      없으면 FK 를 걸 대상 자체가 없다.
  ticker + entry_date 로 느슨하게 묶고, 화면에서 그 날 전후 체결을 찾아 붙인다.

⚠️ticker 는 nullable 이다. "오늘 시장이 왜 빠졌나" 같은 종목 무관 메모도 일지다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # 종목 무관 메모를 허용한다 — 시장 전체에 대한 기록도 일지다.
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("asset_name", sa.String(), nullable=True),
        # 기록한 날이 아니라 **그 판단을 한 날**이다. 나중에 소급해 적을 수 있다.
        sa.Column("entry_date", sa.Date(), nullable=False),
        # ENTRY(진입 근거) · EXIT(청산 근거) · REVIEW(복기) · IDEA(아이디어)
        sa.Column("kind", sa.String(), nullable=False, server_default="ENTRY"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        # 확신도 1~5. 나중에 "확신이 높을 때 실제로 잘했나"를 볼 수 있다.
        # ⚠️nullable 이다 — 억지로 점수를 매기게 하면 아무 숫자나 찍는다.
        sa.Column("conviction", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # 종목별 조회가 기본 동선이다(그 종목 화면에서 "내가 뭐라고 썼더라").
    op.create_index(
        "ix_journal_entries_ticker_date",
        "journal_entries",
        ["ticker", "entry_date"],
    )
    op.create_index("ix_journal_entries_date", "journal_entries", ["entry_date"])


def downgrade() -> None:
    op.drop_index("ix_journal_entries_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_ticker_date", table_name="journal_entries")
    op.drop_table("journal_entries")
