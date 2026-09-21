"""AI/Tech 3단계 산업 분류 (L1 대분류 / L2 중분류 / L3 소분류)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-21

출처: 사용자 제공 `AI_Tech_classification_v2.xlsx` 의 J·K·L 열(4,646종목).
정본 사본은 `database/seeds/ai_tech_classification.json`.

★왜 기존 `sector` 를 덮지 않고 컬럼을 더하는가:
  `sector`(반도체·인터넷 …)는 **전통적 섹터 축**이고, 이 분류는 **AI/Tech 밸류체인
  축**이다(컴퓨팅 인프라 > 클라우드 > 하이퍼스케일러). 같은 종목이 두 축에서 다른
  자리에 놓이며, 둘 다 볼 이유가 있다. 한 컬럼에 섞으면 어느 축인지 알 수 없게 된다.

⚠️ETF 는 이 분류표에 없다(개별 종목 분류다). 실측상 보유 17종목 중 7개가 ETF 라
  L1 이 비는데, 그걸 '미분류'로 두면 비중의 절반이 미분류가 된다. ETF 는 L1='ETF'
  로 따로 세운다 — 투과(look-through) 배분은 사용자가 원하지 않는다고 밝혔다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("tech_l1", sa.String(), nullable=True))
    op.add_column("assets", sa.Column("tech_l2", sa.String(), nullable=True))
    op.add_column("assets", sa.Column("tech_l3", sa.String(), nullable=True))
    # SEED(분류표) / ETF(상품으로 분류) / MANUAL(화면에서 지정). 자동 갱신이 사람이
    # 고친 값을 덮지 않게 하는 표식이다.
    op.add_column("assets", sa.Column("tech_source", sa.String(), nullable=True))
    op.create_index("ix_assets_tech_l1", "assets", ["tech_l1"])


def downgrade() -> None:
    op.drop_index("ix_assets_tech_l1", table_name="assets")
    op.drop_column("assets", "tech_source")
    op.drop_column("assets", "tech_l3")
    op.drop_column("assets", "tech_l2")
    op.drop_column("assets", "tech_l1")
