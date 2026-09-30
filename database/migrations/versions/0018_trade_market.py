"""체결의 자연키에 시장을 넣는다 — 국내와 해외의 거래번호가 겹친다

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-23

★왜 필요한가: `trade_no` 는 증권사 안에서 **일자별로 1 부터 리셋**된다.
  실측(2026-09-23, trades 86행): 전부 9자리이고 값은 `000000001`~`000000005`,
  즉 그날의 몇 번째 거래인가일 뿐이다.

  지금까지는 해외(ust21100)만 받아서 문제가 없었다. 국내(kt00015)를 같이 받기
  시작하면 **같은 계좌·같은 날짜에 `000000001` 이 두 개** 생긴다 — 국내 1번과
  해외 1번. 기존 유일키가 (account_id, trade_date, trade_no) 라
  `ON CONFLICT ... DO UPDATE` 가 한쪽을 다른 쪽으로 **덮어쓴다.**

⚠️예외가 안 난다. 업서트가 성공하고 건수도 맞게 세어져서, 화면에는 "체결 N건"이
  그대로 뜬다. 사라진 것은 국내 매매 한 건이고 아무도 모른다. 그래서 국내 체결을
  받기 **전에** 키를 먼저 고친다.

시장은 통화로 갈음하지 않는다 — 통화는 결제 통화라 뜻이 다르고, 나중에 원화로
결제되는 해외 상품이 생기면 그때 조용히 틀린다. 무엇을 뜻하는지 이름으로 적는다.

기존 86행은 전부 해외(exchange="미국", currency=USD)이므로 'US' 로 채운다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 행을 먼저 채워야 NOT NULL 을 걸 수 있다. 지금 들어 있는 체결은
    # 전부 해외다(국내 조회는 구현된 적이 없다).
    op.add_column(
        "trades",
        sa.Column("market", sa.String(), nullable=False, server_default="US"),
    )
    op.drop_constraint("uq_trades_account_date_no", "trades", type_="unique")
    op.create_unique_constraint(
        "uq_trades_account_market_date_no",
        "trades",
        ["account_id", "market", "trade_date", "trade_no"],
    )


def downgrade() -> None:
    # ⚠️되돌리면 국내·해외가 같은 번호를 쓰는 행이 남아 있을 수 있어 유일키가
    #   안 걸린다. 그때는 국내 행을 먼저 지워야 한다 — 자동으로 지우지 않는다.
    op.drop_constraint("uq_trades_account_market_date_no", "trades", type_="unique")
    op.create_unique_constraint(
        "uq_trades_account_date_no", "trades", ["account_id", "trade_date", "trade_no"]
    )
    op.drop_column("trades", "market")
