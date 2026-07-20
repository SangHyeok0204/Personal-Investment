from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def default_db_path() -> Path:
    # 중앙 데이터 레이어(raw\data)로 이전 — parents[4]=raw 루트(구 raw).
    return Path(__file__).resolve().parents[4] / "data" / "_데이터베이스" / "ETF_INAV_MONITOR.db"


def sqlite_file_uri(path, **query_params):
    path_text = Path(path).as_posix()
    if path_text.startswith("//"):
        path_text = "//" + path_text
    query = "&".join(
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in query_params.items()
    )
    suffix = f"?{query}" if query else ""
    return f"file:{quote(path_text, safe='/:')}{suffix}"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class KisStore:
    def __init__(self, db_path: Path | None = None, timeout: int = 5):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.timeout = timeout

    def _connect(self, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            uri = sqlite_file_uri(self.db_path, mode="ro")
            conn = sqlite3.connect(uri, uri=True, timeout=self.timeout)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        if not read_only:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def connection(self, read_only: bool = False):
        conn = self._connect(read_only=read_only)
        try:
            yield conn
            if not read_only:
                conn.commit()
        except Exception:
            if not read_only:
                conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS isin_mappings (
                    isin TEXT PRIMARY KEY,
                    ticker TEXT,
                    exchange TEXT,
                    figi TEXT,
                    name TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_ticks (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    trade_time TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    last REAL,
                    open REAL,
                    high REAL,
                    low REAL,
                    volume INTEGER,
                    raw_json TEXT,
                    PRIMARY KEY (exchange, symbol, trade_time)
                );

                CREATE INDEX IF NOT EXISTS idx_isin_mappings_ticker
                    ON isin_mappings(ticker COLLATE NOCASE);

                CREATE INDEX IF NOT EXISTS idx_price_ticks_observed_at
                    ON price_ticks(observed_at);
                """
            )

    def get_isin_mappings(self, isins: list[str]) -> dict[str, dict]:
        normalized = [str(value).strip().upper() for value in isins if str(value).strip()]
        if not normalized:
            return {}
        self.init_db()
        placeholders = ",".join("?" for _ in normalized)
        with self.connection(read_only=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM isin_mappings WHERE UPPER(isin) IN ({placeholders})",
                normalized,
            ).fetchall()
        mappings: dict[str, dict] = {}
        for row in rows:
            key = (row["isin"] or "").strip().upper()
            if key and key not in mappings:
                mappings[key] = dict(row)
        return mappings

    def upsert_isin_mappings(self, rows: list[dict]) -> int:
        valid = [
            {
                "isin": (row.get("isin") or "").strip().upper(),
                "ticker": (row.get("ticker") or row.get("symbol") or "").strip().upper() or None,
                "exchange": (row.get("exchange") or row.get("exchCode") or "").strip().upper() or None,
                "figi": (row.get("figi") or "").strip() or None,
                "name": row.get("name") or row.get("companyName") or row.get("englishName"),
                "source": row.get("source") or "openfigi",
            }
            for row in rows
            if row.get("isin")
        ]
        valid = [row for row in valid if row["isin"]]
        if not valid:
            return 0
        self.init_db()
        timestamp = now_utc()
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO isin_mappings (
                    isin, ticker, exchange, figi, name, source, created_at, updated_at
                ) VALUES (
                    :isin, :ticker, :exchange, :figi, :name, :source, :created_at, :updated_at
                )
                ON CONFLICT(isin) DO UPDATE SET
                    ticker = COALESCE(excluded.ticker, isin_mappings.ticker),
                    exchange = COALESCE(excluded.exchange, isin_mappings.exchange),
                    figi = COALESCE(excluded.figi, isin_mappings.figi),
                    name = COALESCE(excluded.name, isin_mappings.name),
                    source = COALESCE(excluded.source, isin_mappings.source),
                    updated_at = excluded.updated_at
                """,
                [{**row, "created_at": timestamp, "updated_at": timestamp} for row in valid],
            )
        return len(valid)

    def upsert_ticks(self, rows: list[dict]) -> int:
        valid = []
        for row in rows:
            exchange = (row.get("exchange") or "").strip().upper()
            symbol = (row.get("symbol") or row.get("ticker") or "").strip().upper()
            trade_time = row.get("trade_time") or row.get("observed_at") or now_utc()
            if not exchange or not symbol:
                continue
            valid.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "trade_time": trade_time,
                    "observed_at": row.get("observed_at") or now_utc(),
                    "last": row.get("last") or row.get("price"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "volume": row.get("volume"),
                    "raw_json": json.dumps(row, ensure_ascii=False, default=str),
                }
            )
        if not valid:
            return 0
        self.init_db()
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO price_ticks (
                    exchange, symbol, trade_time, observed_at,
                    last, open, high, low, volume, raw_json
                ) VALUES (
                    :exchange, :symbol, :trade_time, :observed_at,
                    :last, :open, :high, :low, :volume, :raw_json
                )
                ON CONFLICT(exchange, symbol, trade_time) DO UPDATE SET
                    observed_at = excluded.observed_at,
                    last = excluded.last,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    volume = excluded.volume,
                    raw_json = excluded.raw_json
                """,
                valid,
            )
        return len(valid)
