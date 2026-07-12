import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine, text

DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY,
    job_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'PENDING',
    payload JSONB,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_jobs_status_created_at ON jobs (status, created_at);

CREATE TABLE IF NOT EXISTS job_logs (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    level VARCHAR NOT NULL,
    step VARCHAR,
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_job_logs_job_id_created_at ON job_logs (job_id, created_at);

CREATE TABLE IF NOT EXISTS imports (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id),
    original_filename VARCHAR NOT NULL,
    stored_filename VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    file_size BIGINT NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'PENDING',
    row_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_imports_job_id ON imports (job_id);

CREATE TABLE IF NOT EXISTS brokers (
    id UUID PRIMARY KEY,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_brokers_code UNIQUE (code)
);

CREATE TABLE IF NOT EXISTS brokerage_connections (
    id UUID PRIMARY KEY,
    broker_id UUID NOT NULL REFERENCES brokers(id),
    connection_name VARCHAR NOT NULL,
    environment VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'CONFIGURED',
    last_connected_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY,
    broker_id UUID NOT NULL REFERENCES brokers(id),
    brokerage_connection_id UUID NOT NULL REFERENCES brokerage_connections(id),
    external_account_id VARCHAR NOT NULL,
    account_number_masked VARCHAR,
    account_name VARCHAR,
    account_type VARCHAR,
    base_currency VARCHAR NOT NULL DEFAULT 'KRW',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_accounts_connection_external UNIQUE (brokerage_connection_id, external_account_id)
);

CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY,
    country VARCHAR NOT NULL,
    market VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    name VARCHAR,
    asset_type VARCHAR,
    currency VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_assets_country_market_ticker UNIQUE (country, market, ticker)
);

CREATE TABLE IF NOT EXISTS current_positions (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id),
    asset_id UUID NOT NULL REFERENCES assets(id),
    quantity NUMERIC(20, 6) NOT NULL,
    available_quantity NUMERIC(20, 6),
    average_purchase_price NUMERIC(20, 6),
    purchase_amount_local NUMERIC(20, 2),
    current_price NUMERIC(20, 6),
    market_value_local NUMERIC(20, 2),
    unrealized_pnl_local NUMERIC(20, 2),
    unrealized_return NUMERIC(10, 4),
    exchange_rate NUMERIC(12, 4),
    market_value_krw NUMERIC(20, 2),
    unrealized_pnl_krw NUMERIC(20, 2),
    as_of TIMESTAMPTZ NOT NULL,
    source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_current_positions_account_asset UNIQUE (account_id, asset_id)
);

CREATE TABLE IF NOT EXISTS account_balances (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id),
    currency VARCHAR NOT NULL,
    cash_balance NUMERIC(20, 2) NOT NULL,
    available_cash NUMERIC(20, 2),
    total_purchase_amount_local NUMERIC(20, 2),
    total_market_value_local NUMERIC(20, 2),
    total_evaluation_amount_local NUMERIC(20, 2),
    total_unrealized_pnl_local NUMERIC(20, 2),
    exchange_rate NUMERIC(12, 4),
    total_evaluation_amount_krw NUMERIC(20, 2),
    as_of TIMESTAMPTZ NOT NULL,
    source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_account_balances_account_currency UNIQUE (account_id, currency)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id),
    snapshot_at TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR NOT NULL DEFAULT 'KRW',
    cash_value_krw NUMERIC(20, 2),
    securities_value_krw NUMERIC(20, 2),
    total_assets_krw NUMERIC(20, 2),
    total_purchase_amount_krw NUMERIC(20, 2),
    total_unrealized_pnl_krw NUMERIC(20, 2),
    source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_portfolio_snapshots_account_snapshot_at
    ON portfolio_snapshots (account_id, snapshot_at);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id UUID PRIMARY KEY,
    portfolio_snapshot_id UUID NOT NULL REFERENCES portfolio_snapshots(id) ON DELETE CASCADE,
    account_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    currency VARCHAR NOT NULL,
    quantity NUMERIC(20, 6) NOT NULL,
    average_purchase_price NUMERIC(20, 6),
    current_price NUMERIC(20, 6),
    market_value_local NUMERIC(20, 2),
    market_value_krw NUMERIC(20, 2),
    unrealized_pnl_local NUMERIC(20, 2),
    unrealized_pnl_krw NUMERIC(20, 2),
    exchange_rate NUMERIC(12, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_position_snapshots_snapshot
    ON position_snapshots (portfolio_snapshot_id);

CREATE TABLE IF NOT EXISTS broker_api_raw_responses (
    id UUID PRIMARY KEY,
    broker_id UUID NOT NULL REFERENCES brokers(id),
    job_id UUID,
    api_category VARCHAR NOT NULL,
    endpoint_name VARCHAR NOT NULL,
    response_file_path VARCHAR NOT NULL,
    response_hash VARCHAR NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_broker_api_raw_responses_job_id
    ON broker_api_raw_responses (job_id);
"""


@pytest.fixture(scope="session")
def test_engine():
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        pytest.skip("DATABASE_URL not set")
    prefix = base_url.rpartition("/")[0]
    test_url = f"{prefix}/investment_test"
    admin_url = f"{prefix}/postgres"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text("CREATE DATABASE investment_test"))
    except Exception:
        pass
    finally:
        admin_engine.dispose()

    engine = create_engine(test_url)
    with engine.begin() as conn:
        conn.execute(text(DDL))

    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE jobs, job_logs, imports, brokers, brokerage_connections, "
                "accounts, assets, current_positions, account_balances, "
                "portfolio_snapshots, position_snapshots, broker_api_raw_responses "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield test_engine
