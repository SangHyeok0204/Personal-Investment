import logging
import time

from sqlalchemy import create_engine, text

logger = logging.getLogger("worker")


def get_engine(database_url):
    return create_engine(database_url, pool_pre_ping=True)


def wait_for_db(engine, timeout_seconds=60, interval_seconds=2):
    """Block until the database is reachable, or raise after timeout_seconds."""
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection established")
            return
        except Exception as exc:
            last_error = exc
            logger.info("Database not ready yet, retrying in %ss", interval_seconds)
            time.sleep(interval_seconds)
    raise RuntimeError(
        f"Could not connect to database within {timeout_seconds}s: {last_error}"
    )
