import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_LOCAL = _REPO_ROOT / ".env.local"


def _database_url() -> str | None:
    """환경변수 → `.env.local` 순으로 찾는다.

    ⚠️예전에는 `os.environ` 만 봤다. 그래서 API 쪽이 `.env.local` 을 읽게 된 뒤로도
      워커 테스트 **17건이 조용히 건너뛰어졌다** — 합계는 '474 passed' 에서
      '457 passed, 24 skipped' 로 줄었는데, 요약 한 줄만 보면 통과로 읽힌다.
      건너뛴 시험은 통과한 시험이 아니다. 두 쪽이 같은 곳을 보게 맞춘다.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if not _ENV_LOCAL.exists():
        return None
    for line in _ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.partition("=")[2].strip() or None
    return None

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
-- 0019: 큐·심장박동·재시도 횟수. 테스트 DB 는 세션마다 새로 만들지 않고 재사용하므로
-- CREATE TABLE IF NOT EXISTS 만으로는 기존 표에 열이 붙지 않는다 — 따로 더한다.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS queue VARCHAR NOT NULL DEFAULT 'default';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS ix_jobs_queue_status_created_at ON jobs (queue, status, created_at);

CREATE TABLE IF NOT EXISTS source_status (
    source VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    last_ok_at TIMESTAMPTZ,
    last_error_at TIMESTAMPTZ,
    last_error_kind VARCHAR,
    last_error_message TEXT,
    detail JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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


#: ⚠️**이력 표가 시험 DB 에 없었다.** 그래서 전체 동기화 시험이 이력 단계에서
#:  조용히 실패하고 있었다 — `except Exception` 이 삼켜 경고 한 줄만 남기고
#:  SUCCESS 로 끝나니 시험은 통과했다. 실측으로 확인한 로그:
#:    WARNING|sync_history|History sync failed ... relation "..." does not exist
#:  즉 체결·일별성과·실현손익·주문·배당 경로는 **한 번도 시험된 적이 없다.**
#:  잔고만 보는 시험이라면 없어도 되지만, 그러면 "이력이 동작한다"는 근거가
#:  어디에도 없다. 표를 만들어 진짜로 태운다.
HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY, account_id UUID NOT NULL, asset_id UUID,
    ticker VARCHAR NOT NULL, asset_name VARCHAR, trade_date DATE NOT NULL,
    settlement_date DATE NOT NULL, trade_date_source VARCHAR,
    trade_no VARCHAR NOT NULL, market VARCHAR NOT NULL, side VARCHAR NOT NULL,
    quantity NUMERIC(20,6) NOT NULL, price NUMERIC(20,6),
    currency VARCHAR NOT NULL, amount_local NUMERIC(20,4),
    settlement_amount_local NUMERIC(20,4), commission_local NUMERIC(20,4),
    tax_local NUMERIC(20,4), amount_krw NUMERIC(20,2), exchange VARCHAR,
    channel VARCHAR, processed_at VARCHAR, source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_trades_account_market_settle_no
        UNIQUE (account_id, market, settlement_date, trade_no)
);
-- 0028 — 재사용되는 시험 DB 에 옛 표가 남아 있으면 멱등하게 맞춘다.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS settlement_date DATE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trade_date_source VARCHAR;
ALTER TABLE trades DROP CONSTRAINT IF EXISTS uq_trades_account_market_date_no;
ALTER TABLE trades DROP CONSTRAINT IF EXISTS uq_trades_account_date_no;
CREATE UNIQUE INDEX IF NOT EXISTS uq_trades_account_market_settle_no
    ON trades (account_id, market, settlement_date, trade_no);

CREATE TABLE IF NOT EXISTS account_daily_performance (
    id UUID PRIMARY KEY, account_id UUID NOT NULL, base_date DATE NOT NULL,
    deposit_assets_krw NUMERIC(20,2), stock_value_krw NUMERIC(20,2),
    pnl_krw NUMERIC(20,2), cumulative_pnl_krw NUMERIC(20,2),
    dividend_krw NUMERIC(20,2), commission_tax_krw NUMERIC(20,2),
    buy_amount_krw NUMERIC(20,2), sell_amount_krw NUMERIC(20,2),
    deposit_krw NUMERIC(20,2), withdrawal_krw NUMERIC(20,2),
    return_rate NUMERIC(12,6), exchange_rate NUMERIC(12,4), source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_daily_perf_account_date UNIQUE (account_id, base_date)
);

CREATE TABLE IF NOT EXISTS realized_pnl (
    id UUID PRIMARY KEY, account_id UUID NOT NULL, asset_id UUID,
    ticker VARCHAR NOT NULL, asset_name VARCHAR, sell_date DATE NOT NULL,
    quantity NUMERIC(20,6) NOT NULL, currency VARCHAR NOT NULL,
    avg_buy_price NUMERIC(20,6), avg_sell_price NUMERIC(20,6),
    buy_amount_local NUMERIC(20,4), sell_amount_local NUMERIC(20,4),
    commission_tax_local NUMERIC(20,4), pnl_local NUMERIC(20,4),
    buy_amount_krw NUMERIC(20,2), sell_amount_krw NUMERIC(20,2),
    commission_tax_krw NUMERIC(20,2), pnl_krw NUMERIC(20,2),
    pnl_rate NUMERIC(12,6), buy_exchange_rate NUMERIC(12,4),
    sell_exchange_rate NUMERIC(12,4), fx_pnl_krw NUMERIC(20,2), exchange VARCHAR,
    source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_realized_account_date_ticker UNIQUE (account_id, sell_date, ticker)
);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY, account_id UUID NOT NULL, asset_id UUID,
    ticker VARCHAR NOT NULL, asset_name VARCHAR, order_date DATE NOT NULL,
    order_no VARCHAR NOT NULL, order_time VARCHAR, side VARCHAR NOT NULL,
    order_type VARCHAR, currency VARCHAR NOT NULL, order_quantity NUMERIC(20,6),
    filled_quantity NUMERIC(20,6), cancelled_quantity NUMERIC(20,6),
    modified_quantity NUMERIC(20,6), remaining_quantity NUMERIC(20,6),
    order_price NUMERIC(20,6), filled_price NUMERIC(20,6),
    stop_price NUMERIC(20,6), filled_amount NUMERIC(20,4), exchange VARCHAR,
    channel VARCHAR, reserve_type VARCHAR, source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_orders_account_date_no UNIQUE (account_id, order_date, order_no)
);

CREATE TABLE IF NOT EXISTS dividends (
    id UUID PRIMARY KEY, account_id UUID NOT NULL, asset_id UUID,
    ticker VARCHAR NOT NULL, asset_name VARCHAR, pay_date DATE NOT NULL,
    amount_krw NUMERIC(20,2) NOT NULL, currency VARCHAR NOT NULL,
    source_job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_dividends_account_date_ticker UNIQUE (account_id, pay_date, ticker)
);

CREATE TABLE IF NOT EXISTS broker_exchange_codes (
    ticker VARCHAR PRIMARY KEY, code VARCHAR NOT NULL,
    source VARCHAR NOT NULL DEFAULT 'probe',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@pytest.fixture(scope="session")
def test_engine():
    base_url = _database_url()
    if not base_url:
        pytest.skip(f"DATABASE_URL 없음 (환경변수에도, {_ENV_LOCAL} 에도)")
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
        conn.execute(text(HISTORY_DDL))

    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE jobs, job_logs, imports, source_status, brokers, brokerage_connections, "
                "accounts, assets, current_positions, account_balances, "
                "portfolio_snapshots, position_snapshots, broker_api_raw_responses, "
                # ⚠️이력 표도 비운다. 안 비우면 앞 시험이 남긴 행이 다음 시험의
                #   '몇 건 들어왔나'를 바꾼다.
                "trades, account_daily_performance, realized_pnl, orders, "
                "dividends, broker_exchange_codes "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield test_engine
