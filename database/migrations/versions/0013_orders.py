"""주문 내역 — 체결 이력이 감추는 것들

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-22

원천: 키움 `ust21180`(미국주식 기간별 주문내역).

★**체결 내역(ust21100)에는 없는 정보**가 여기 있다. 체결은 "성사된 것"만
  알려주지만, 주문은 "하려고 한 것"을 전부 알려준다. 실측(2026-09-22):
    · 2026-07-29 BE 를 6번 주문해 1번만 체결됐다. 184.56·184.62·184.65·185.01 에
      건 지정가는 전부 미체결. 체결 이력만 보면 "BE 를 4주 샀다"로 끝난다.
    · 슬리피지가 보인다. SNDK 매도 주문 1754.00 → 체결 1755.76.
    · 주문 채널이 남는다(전부 "영웅문S#" — 앱에서 넣은 주문).

⚠️조회 기간이 **3개월 제한**이다(실측: 20260601~20260922 요청에
  "조회기간은 3개월 이내만 가능합니다" / return_code=20). 체결내역(ust21100)의
  360일과 다르다 — TR 마다 상한이 다르므로 창을 따로 잡아야 한다.

⚠️명세서 응답 예시의 키는 `result_lsit`(오타)인데 **실제 응답은 `result_list`**
  다. 둘 다 받도록 해 두었다.

자연키는 (account_id, order_date, order_no) 다. 같은 기간을 다시 조회해도 행이
늘지 않아야 한다 — 주문 상태(체결수량·취소수량)는 나중에 바뀌므로 덮어쓴다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ⚠️assets 를 FK 로 걸지 않는다. 한 번도 체결된 적 없는 종목(SKHYV 처럼
        #   주문만 넣고 전부 미체결)은 assets 행이 없다.
        sa.Column("asset_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("asset_name", sa.String(), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("order_no", sa.String(), nullable=False),
        # 주문 시각(HH:MM:SS). 날짜와 따로 오므로 문자열 그대로 둔다.
        sa.Column("order_time", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=False),
        # 지정가 / 시장가 등.
        sa.Column("order_type", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("order_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("filled_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("cancelled_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("modified_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("remaining_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("order_price", sa.Numeric(20, 6), nullable=True),
        # ⚠️미체결 주문은 체결가가 0 으로 온다. 적재할 때 None 으로 바꾼다 —
        #   0 달러에 체결된 것처럼 보이면 안 된다.
        sa.Column("filled_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("stop_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("filled_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        # 영웅문S# / REST API 등 — 어디서 넣은 주문인지.
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("reserve_type", sa.String(), nullable=True),
        sa.Column("source_job_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
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
    op.create_unique_constraint(
        "uq_orders_account_date_no", "orders", ["account_id", "order_date", "order_no"]
    )
    op.create_index("ix_orders_account_date", "orders", ["account_id", "order_date"])
    op.create_index("ix_orders_ticker", "orders", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_orders_ticker", table_name="orders")
    op.drop_index("ix_orders_account_date", table_name="orders")
    op.drop_constraint("uq_orders_account_date_no", "orders", type_="unique")
    op.drop_table("orders")
