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
            text("TRUNCATE jobs, job_logs, imports RESTART IDENTITY CASCADE")
        )
    yield test_engine
