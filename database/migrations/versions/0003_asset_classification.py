"""asset classification seed: set asset_type for the current holdings

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12

No schema change — assets.asset_type already exists (0002). This only seeds the
classifications the user decided on, since Kiwoom does not supply an asset class.

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# portfolio-detail-spec §2. Anything not listed keeps the worker's default (STOCK).
ASSET_TYPE_BY_TICKER = {
    "SGOV": "BOND",  # 미국 초단기 국채 ETF
    "TSL": "DERIVATIVE",  # 테슬라 1.25배 레버리지 ETF
    "GLD": "OTHER",  # 금 SPDR ETF (원자재)
    "XLB": "STOCK",  # 원자재 섹터 '기업 주식' ETF
    "SCHD": "STOCK",  # 미국 배당주 ETF
    "NVDA": "STOCK",
    "MSFT": "STOCK",
    "GOOGL": "STOCK",
    "GLW": "STOCK",
    "SKHYV": "STOCK",
    "000660": "STOCK",  # 국내 개별주
    "388720": "STOCK",  # 국내 개별주
}

DEFAULT_ASSET_TYPE = "STOCK"


def upgrade() -> None:
    # Idempotent: matching by ticker is a no-op when the holding is absent, and the
    # IS DISTINCT FROM guard means re-running touches nothing already classified.
    for ticker, asset_type in ASSET_TYPE_BY_TICKER.items():
        op.execute(
            f"UPDATE assets SET asset_type = '{asset_type}', updated_at = now() "
            f"WHERE ticker = '{ticker}' AND asset_type IS DISTINCT FROM '{asset_type}'"
        )


def downgrade() -> None:
    # Hand the reclassified holdings back to the worker's default. Tickers seeded as
    # STOCK were already at the default, so they need no revert.
    for ticker, asset_type in ASSET_TYPE_BY_TICKER.items():
        if asset_type == DEFAULT_ASSET_TYPE:
            continue
        op.execute(
            f"UPDATE assets SET asset_type = '{DEFAULT_ASSET_TYPE}', updated_at = now() "
            f"WHERE ticker = '{ticker}'"
        )
