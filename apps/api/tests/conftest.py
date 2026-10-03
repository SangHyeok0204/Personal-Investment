import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Base

# All tables truncated between tests (FK-safe via CASCADE).
# 포트폴리오 테이블도 포함한다 — 계좌/종목은 테스트마다 새로 만든다(2026-09-21).
_ALL_TABLES = (
    "job_logs, imports, jobs, source_status, trades, realized_pnl, account_daily_performance, dividends, "
    "alert_rules, ops_alert_state, rebalance_targets, journal_entries, orders, "
    "portfolio_snapshots, current_positions, account_balances, "
    "accounts, assets, brokerage_connections, brokers, monthly_closes, seasonality_series, "
    "guru_roster, sec_filings, holdings_13f, form4_transactions, ownership_events, cusip_map, watchlist_items, "
    "earnings_watchpoints, earnings_guidance, earnings_results, earnings_events"
)


def _test_db_url():
    return make_url(settings.DATABASE_URL).set(database="investment_test")


@pytest.fixture(scope="session")
def engine():
    test_url = _test_db_url()

    # Create the test database if it does not exist (autocommit; ignore duplicate).
    admin_url = make_url(settings.DATABASE_URL).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": test_url.database},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    admin_engine.dispose()

    test_engine = create_engine(test_url, future=True)
    # 계절성 표는 키가 바뀐 적이 있다(0021) — 재사용 DB 에 옛 키가 남지 않게 새로 만든다.
    with test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS monthly_closes, seasonality_series CASCADE"))
    Base.metadata.create_all(test_engine)
    # ⚠️테스트 DB 는 재사용된다. create_all 은 **이미 있는 표에 열을 붙이지 않는다**
    #   — 0019 에서 jobs 에 더한 열을 여기서 멱등하게 맞춘다(워커 테스트와 같은 DB).
    with test_engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS queue VARCHAR NOT NULL DEFAULT 'default'"))
        conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0"))
    yield test_engine
    test_engine.dispose()


@pytest.fixture()
def db(engine):
    # Reset all tables before each test.
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {_ALL_TABLES} RESTART IDENTITY CASCADE"))

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine, db, tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    (storage_dir / "raw").mkdir(parents=True)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage_dir))

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
