import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Base


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
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture()
def db(engine):
    # Reset all tables before each test.
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE job_logs, imports, jobs RESTART IDENTITY CASCADE"))

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
