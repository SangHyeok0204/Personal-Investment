"""관심종목 보드

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-22

사용자가 처음부터 말한 것: "toss api 활용해서 관심 있는 종목 모니터하는 것".
시세 소스(토스/야후)가 붙은 지금에야 의미가 생겨 이제 만든다.

★보유 종목은 **여기에 넣지 않는다.** 보유는 `current_positions` 가 이미 정본이고,
  복제해 두면 판 뒤에도 관심종목에 남거나 둘이 어긋난다. 화면에서 두 목록을
  합쳐 보여주되 저장은 한 곳에만 한다.

★계좌에 묶지 않는다(account_id 없음). 관심종목은 "무엇을 지켜보는가"라서
  어느 계좌로 사든 같다. 계좌를 바꿔도 목록이 따라다녀야 한다.

⚠️`assets` 를 FK 로 걸지 않는다. 아직 한 번도 안 산 종목을 담는 게 이 화면의
  요점인데, assets 행은 **매수해야** 생긴다. FK 를 걸면 관심종목에 새 종목을
  추가하는 것 자체가 막힌다. ticker 문자열로 느슨하게 둔다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        # 시세 소스가 이름을 주기 전에도 화면에 뭔가는 띄워야 한다.
        sa.Column("asset_name", sa.String(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        # 목표가·손절가는 **선택**이다. 안 걸어 둔 종목이 대부분이다.
        # ⚠️통화를 따로 두지 않는다 — 시세 소스가 주는 통화를 그대로 쓴다.
        #   여기 통화를 또 저장하면 소스와 어긋났을 때 어느 쪽이 맞는지 알 수 없다.
        sa.Column("target_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("stop_price", sa.Numeric(20, 6), nullable=True),
        # 사용자가 정한 순서. 같은 값이면 추가한 순서대로.
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
    # 같은 종목을 두 번 담을 이유가 없다. 중복은 DB 에서 막는다 —
    # 화면에서만 막으면 탭 두 개로 동시에 누르면 뚫린다.
    op.create_unique_constraint(
        "uq_watchlist_items_ticker", "watchlist_items", ["ticker"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_watchlist_items_ticker", "watchlist_items", type_="unique")
    op.drop_table("watchlist_items")
