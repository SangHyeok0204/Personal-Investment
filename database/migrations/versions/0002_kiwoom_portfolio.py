"""kiwoom portfolio: brokers, connections, accounts, assets, positions,
balances, snapshots, raw responses

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brokers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("code", name="uq_brokers_code"),
    )

    op.create_table(
        "brokerage_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokers.id"),
            nullable=False,
        ),
        sa.Column("connection_name", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default=sa.text("'CONFIGURED'")
        ),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokers.id"),
            nullable=False,
        ),
        sa.Column(
            "brokerage_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokerage_connections.id"),
            nullable=False,
        ),
        sa.Column("external_account_id", sa.String(), nullable=False),
        sa.Column("account_number_masked", sa.String(), nullable=True),
        sa.Column("account_name", sa.String(), nullable=True),
        sa.Column("account_type", sa.String(), nullable=True),
        sa.Column(
            "base_currency", sa.String(), nullable=False, server_default=sa.text("'KRW'")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "brokerage_connection_id",
            "external_account_id",
            name="uq_accounts_connection_external",
        ),
    )

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("country", "market", "ticker", name="uq_assets_country_market_ticker"),
    )

    op.create_table(
        "current_positions",
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
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("available_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("average_purchase_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("purchase_amount_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("current_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("market_value_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_pnl_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_return", sa.Numeric(10, 4), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("market_value_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("account_id", "asset_id", name="uq_current_positions_account_asset"),
    )

    op.create_table(
        "account_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("cash_balance", sa.Numeric(20, 2), nullable=False),
        sa.Column("available_cash", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_purchase_amount_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_market_value_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_evaluation_amount_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_unrealized_pnl_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("total_evaluation_amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("account_id", "currency", name="uq_account_balances_account_currency"),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "base_currency", sa.String(), nullable=False, server_default=sa.text("'KRW'")
        ),
        sa.Column("cash_value_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("securities_value_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_assets_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_purchase_amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_unrealized_pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_portfolio_snapshots_account_snapshot_at",
        "portfolio_snapshots",
        ["account_id", "snapshot_at"],
    )

    op.create_table(
        "position_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "portfolio_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("average_purchase_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("current_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("market_value_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("market_value_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_pnl_local", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_position_snapshots_snapshot", "position_snapshots", ["portfolio_snapshot_id"]
    )

    op.create_table(
        "broker_api_raw_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokers.id"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_category", sa.String(), nullable=False),
        sa.Column("endpoint_name", sa.String(), nullable=False),
        sa.Column("response_file_path", sa.String(), nullable=False),
        sa.Column("response_hash", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_broker_api_raw_responses_job_id", "broker_api_raw_responses", ["job_id"]
    )

    # Idempotent seed: one Kiwoom broker + one default connection. Re-running the
    # migration (or running it after a manual insert) must not create duplicates.
    op.execute(
        """
        INSERT INTO brokers (id, code, name, is_active, created_at, updated_at)
        VALUES (gen_random_uuid(), 'KIWOOM', '키움증권', true, now(), now())
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO brokerage_connections
            (id, broker_id, connection_name, environment, status, created_at, updated_at)
        SELECT gen_random_uuid(), b.id, '키움 기본 연결', 'REAL', 'CONFIGURED', now(), now()
        FROM brokers b
        WHERE b.code = 'KIWOOM'
          AND NOT EXISTS (
              SELECT 1 FROM brokerage_connections bc
              WHERE bc.broker_id = b.id AND bc.connection_name = '키움 기본 연결'
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_broker_api_raw_responses_job_id", table_name="broker_api_raw_responses")
    op.drop_table("broker_api_raw_responses")
    op.drop_index("ix_position_snapshots_snapshot", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_index(
        "ix_portfolio_snapshots_account_snapshot_at", table_name="portfolio_snapshots"
    )
    op.drop_table("portfolio_snapshots")
    op.drop_table("account_balances")
    op.drop_table("current_positions")
    op.drop_table("assets")
    op.drop_table("accounts")
    op.drop_table("brokerage_connections")
    op.drop_table("brokers")
