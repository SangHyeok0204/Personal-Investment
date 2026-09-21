"""배당 수령 이력 + 종목별 거래소 코드 캐시

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

원천: 키움 `usa21730`(미국주식 일별종목수익률현황)의 `dvid_amt`.
실측(2026-09-21)으로 확인한 것들:

  · 배당 **전용 TR 이 없다.** 일별 종목수익률 응답에 dvid_amt 가 섞여 온다.
    그래서 배당이 있는 날만 골라내 저장한다(0원인 날은 버린다 — 대부분이다).
  · `stk_cd` 가 **필수**다. 전체 조회가 안 되고 종목별로 돌려야 한다.
  · `stex_tp`(거래소구분)도 **필수인데 종목마다 다르다** — SCHD=NY, NVDA=ND.
    틀리면 `1903:종목 정보가 없습니다`. 보유종목 응답의 stex_nm 은 "미국"이라
    거래소를 알려주지 않으므로 ND/NY/NA 를 순차 시도해 찾아야 한다.
    → 한 번 찾은 코드를 assets.broker_exchange_code 에 캐시해 다음 동기화에서
      헛호출을 줄인다(종목 20개면 최대 60번이 20번으로 준다).
  · 금액은 **원화(KRW)** 로 온다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 증권사가 쓰는 거래소 코드(ND/NY/NA). 우리 분류(country/market)와 다른 축이라
    # 별도 컬럼으로 둔다 — market 을 덮어쓰면 유니크 키가 흔들린다.
    op.add_column(
        "assets", sa.Column("broker_exchange_code", sa.String(), nullable=True)
    )

    op.create_table(
        "dividends",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id"),
            nullable=True,
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("asset_name", sa.String(), nullable=True),
        # usa21730 은 구간(frst_base_dt~last_base_dt)으로 주는데, 배당이 찍힌 구간의
        # **끝 날짜**를 지급일로 본다. 하루짜리 구간이라 사실상 그날이다.
        sa.Column("pay_date", sa.Date(), nullable=False),
        # 증권사가 원화로 준다. 외화 원금액은 이 TR 이 주지 않는다.
        sa.Column("amount_krw", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'KRW'")),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "account_id", "pay_date", "ticker", name="uq_dividends_account_date_ticker"
        ),
    )
    op.create_index("ix_dividends_account_date", "dividends", ["account_id", "pay_date"])


def downgrade() -> None:
    op.drop_index("ix_dividends_account_date", table_name="dividends")
    op.drop_table("dividends")
    op.drop_column("assets", "broker_exchange_code")
