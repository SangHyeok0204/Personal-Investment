"""cusip_map 에 SEC 업종코드(SIC)와 섹터 — 거장 13F 섹터 흐름의 '미분류' 줄이기 (계획 A5)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-27

★원본 섹터 맵은 한 분기(2026-03-31) 상위 종목으로 손으로 만든 CSV 다(286 CUSIP). 분기가 지날수록 새 종목이
  빠져 26Q2 커버리지가 86% 로 떨어졌고, 미분류가 섹터 막대에서 가장 큰 조각(+489bp)이 됐다.
  → CSV 가 없는 종목은 SEC `submissions` 의 SIC 로 채운다(CSV 먼저 — SIC 는 GICS 보다 거칠다).
  `sic = ''` 은 "찾아봤지만 없음"(다시 묻지 않는다), NULL 은 아직 안 찾아봄.
번호: P1 규칙(머지 순서) — 실적(B1)은 0024 로 밀린다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cusip_map", sa.Column("sic", sa.String(), nullable=True))
    op.add_column("cusip_map", sa.Column("sector", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("cusip_map", "sector")
    op.drop_column("cusip_map", "sic")
