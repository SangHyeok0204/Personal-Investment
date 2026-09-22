"""거래소 코드를 티커별로 기억한다 — 판 종목까지

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-23

★왜 필요한가: 배당 조회(usa21730)는 종목마다 **거래소 코드(ND/NY/NA)** 가 있어야
  하는데 잔고 응답이 알려주지 않는다. 그래서 ND→NY→NA 로 더듬어 찾고, 찾은 코드를
  `assets.broker_exchange_code` 에 적어 둔다.

  문제는 **`assets` 에 보유 종목만 있다**는 것이다(실측 17행). 이미 판 종목은
  포지션이 없어 자산 표에 안 남으므로 코드도 못 남긴다. 실측: SGOV 는 배당이
  14건이나 들어왔는데 코드가 안 남아 동기화할 때마다 세 거래소를 다시 더듬는다.

⚠️그보다 나쁜 것: 탐색이 "에러가 안 나면 맞는 거래소"로 친다 — **빈 응답도
  통과한다.** 최근 5일에 아무 행이 없는 종목(판 종목이 특히)은 첫 코드인 ND 가
  그대로 붙고, 그 종목이 사실 NYSE 면 배당 조회가 **조용히 빈 값**을 돌려준다.
  건너뛴 것으로도 안 잡히니 화면에서는 '배당 0원'으로 보인다.

  탐색을 "행이 온 코드만 인정"으로 조이려면 먼저 **한 번 찾은 코드를 잃지 않아야**
  한다. 안 그러면 판 종목이 매번 '확인 못 함'으로 보고된다. 그래서 이 표를 만든다.

  ⚠️티커가 자연키다. 계좌를 나눠도 같은 종목의 거래소는 같다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_exchange_codes",
        sa.Column("ticker", sa.String(), primary_key=True),
        # ND / NY / NA. 증권사가 쓰는 코드를 그대로 둔다.
        sa.Column("code", sa.String(), nullable=False),
        # 어떻게 알아냈나 — "probe"(더듬어 찾음) / "dividend"(배당 응답에 실려 옴).
        # 근거를 남겨야 나중에 "이 코드 믿어도 되나"를 물을 수 있다.
        sa.Column("source", sa.String(), nullable=False, server_default="probe"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 이미 알아낸 코드를 옮겨 둔다 — 처음부터 다시 더듬게 하지 않는다.
    op.execute(
        """
        INSERT INTO broker_exchange_codes (ticker, code, source)
        SELECT ticker, broker_exchange_code, 'assets'
        FROM assets
        WHERE broker_exchange_code IS NOT NULL
        ON CONFLICT (ticker) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("broker_exchange_codes")
