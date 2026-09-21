"""assets 에 섹터 분류를 더한다 (sector / industry / 출처 / 분류시각)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-21

왜 필요한가: 0003 이 넣은 `asset_type` 은 **자산군**(STOCK/BOND/DERIVATIVE/OTHER)
이지 섹터가 아니다. 사용자가 모니터링 1순위로 꼽은 "섹터별 투자 비중"을 그리려면
종목→섹터 매핑이 따로 있어야 하는데, 증권사(키움)는 섹터를 주지 않는다.

설계 결정 세 가지:

1. **섹터는 assets 에 직접 단다.** 별도 분류 테이블을 두면 조인이 하나 늘고,
   종목당 섹터는 하나뿐이라 테이블을 나눌 이득이 없다. 나중에 다중 분류 체계
   (GICS/WICS 동시 운용)가 필요해지면 그때 분리한다 — 지금 만들면 YAGNI 다.

2. **출처(sector_source)를 같이 기록한다.** 손으로 넣은 것과 외부에서 받아온
   것을 구분하지 못하면, 나중에 자동 분류를 붙일 때 사람이 고친 값을 덮어쓴다.
   'MANUAL' 은 자동 갱신에서 제외하는 표식이 된다.

3. **미분류를 NULL 로 둔다.** '기타'로 채우지 않는다 — '분류를 안 했다'와
   '분류했더니 기타다'는 다른 상태이고, 섞이면 분류 작업이 끝났는지 알 수 없다.
   화면은 NULL 을 '미분류'로 **드러내서** 그린다(합계에서 숨기지 않는다).
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


# 분류 목록의 정본은 database/seeds/sectors.py 다. 여기 복제하지 않고 읽어 온다 —
# 마이그레이션·워커·스크립트가 각자 목록을 들면 반드시 어긋난다.
import importlib.util as _ilu
import pathlib as _pathlib
import sys as _sys

_SEED_PATH = _pathlib.Path(__file__).resolve().parents[3] / "database" / "seeds" / "sectors.py"
_spec = _ilu.spec_from_file_location("_sector_seed_0006", _SEED_PATH)
_mod = _ilu.module_from_spec(_spec)
_sys.modules["_sector_seed_0006"] = _mod
_spec.loader.exec_module(_mod)
SECTOR_SEED = _mod.SECTOR_SEED


def upgrade() -> None:
    op.add_column("assets", sa.Column("sector", sa.String(), nullable=True))
    op.add_column("assets", sa.Column("industry", sa.String(), nullable=True))
    # MANUAL / SEED / 외부 출처 코드. 자동 분류가 사람이 고친 값을 덮지 않게 하는 표식.
    op.add_column("assets", sa.Column("sector_source", sa.String(), nullable=True))
    op.add_column(
        "assets", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_assets_sector", "assets", ["sector"])

    # 이미 분류된 종목은 건드리지 않는다(재실행해도 안전, 사람이 고친 값 보존).
    conn = op.get_bind()
    for ticker, (sector, industry) in SECTOR_SEED.items():
        conn.execute(
            sa.text(
                "UPDATE assets SET sector = :sector, industry = :industry, "
                "sector_source = 'SEED', classified_at = now(), updated_at = now() "
                "WHERE ticker = :ticker AND sector IS NULL"
            ),
            {"sector": sector, "industry": industry, "ticker": ticker},
        )


def downgrade() -> None:
    op.drop_index("ix_assets_sector", table_name="assets")
    op.drop_column("assets", "classified_at")
    op.drop_column("assets", "sector_source")
    op.drop_column("assets", "industry")
    op.drop_column("assets", "sector")
