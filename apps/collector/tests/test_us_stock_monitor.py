"""us_stock_monitor 회귀 테스트 — 미장_실시간체결가.db(틱로그) → 테이블 payload.

라이브 DB 에 의존하지 않는다 — us_realtime.py 의 SCHEMA 대로 합성 DB 를 만들어 넣고,
세션 경계(session_bounds)는 고정값으로 monkeypatch 한다.

  1) 세션 경계: ET 20:00 개시 / 16:00 앵커 / 거래일 = 개시 다음날 (서머·표준시)
  2) 집계: 세션 내 체결만 Σ(가격×수량), 앵커 = 앵커 경계 이전 마지막 체결
  3) 세션 체결 없는 종목 제외, 과거 이력 없는 종목은 등락률 None (fail-soft)
  4) rowid 커서 증분 — 두 번째 cycle 이 새 행만 더한다(이중 집계 금지)
  5) 세션 롤오버 — 경계가 바뀌면 집계·앵커 리셋
  6) 웜업 전 build() = 빈 rows + note (화면 대기 문구 경로)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import us_stock_monitor as usm  # noqa: E402

SCHEMA = """
CREATE TABLE trades (
    symbol TEXT NOT NULL, ts TEXT NOT NULL, price REAL NOT NULL,
    volume INTEGER, collected_at TEXT NOT NULL
);
CREATE INDEX idx_trades_symbol_ts ON trades(symbol, ts);
CREATE TABLE latest (
    symbol TEXT PRIMARY KEY, price REAL, volume INTEGER, ts TEXT, collected_at TEXT
);
CREATE TABLE status (key TEXT PRIMARY KEY, value TEXT);
"""

# 고정 세션 (KST 문자열) — 개시 09:00, 앵커 경계 05:00 (서머타임 무관, 테스트 전용 값)
WS = "2026-08-26 09:00:00"
ANCHOR_B = "2026-08-26 05:00:00"
DAY = "2026-08-26"


def _mk_db(path: str, trades: list[tuple], status: dict | None = None) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO trades VALUES (?,?,?,?,?)",
                    [(s, ts, p, v, ts) for s, ts, p, v in trades])
    last: dict[str, tuple] = {}
    for s, ts, p, v in trades:
        if s not in last or ts >= last[s][1]:
            last[s] = (s, ts, p, v)
    con.executemany("INSERT OR REPLACE INTO latest VALUES (?,?,?,?,?)",
                    [(s, p, v, ts, ts) for s, ts, p, v in last.values()])
    for k, v in (status or {}).items():
        con.execute("INSERT OR REPLACE INTO status VALUES (?,?)", (k, v))
    con.commit()
    con.close()


def _monitor(db_path: str, monkeypatch) -> usm.UsStockMonitor:
    monkeypatch.setattr(usm, "session_bounds", lambda now_et=None: (WS, ANCHOR_B, DAY))
    mon = usm.UsStockMonitor(db_path=db_path)
    # 테스트는 _cycle 을 직접 부른다 — build() 의 lazy 스레드 기동을 막아 둔다.
    mon._thread = threading.Thread(target=lambda: None)
    return mon


BASE_TRADES = [
    # AAA: 앵커(전일 정규장 04:59 마감가 100) + 세션 체결 2건
    ("AAA", "2026-08-26 04:59:00", 100.0, 5),
    ("AAA", "2026-08-26 09:10:00", 101.0, 10),
    ("AAA", "2026-08-26 09:20:00", 102.0, 20),
    # BBB: 앵커~세션 사이(애프터장 06:30) 체결만 — 세션 체결 없음 → 표 제외
    ("BBB", "2026-08-26 06:30:00", 50.0, 3),
    # CCC: 과거 이력 없이 세션에서 첫 체결 → 등락률 None
    ("CCC", "2026-08-26 10:00:00", 7.0, 100),
]


def test_session_bounds_dst_and_standard():
    et = usm.ET
    # 서머타임(EDT, KST=ET+13): 수 10:00 ET → 개시 화 20:00 ET = 수 09:00 KST
    ws, anchor, day = usm.session_bounds(datetime(2026, 8, 26, 10, 0, tzinfo=et))
    assert (ws, anchor, day) == ("2026-08-26 09:00:00", "2026-08-26 05:00:00", "2026-08-26")
    # 20시 이후는 다음 거래일 사이클
    ws, anchor, day = usm.session_bounds(datetime(2026, 8, 26, 21, 0, tzinfo=et))
    assert (ws, day) == ("2026-08-27 09:00:00", "2026-08-27")
    # 표준시(EST, KST=ET+14): 개시 = 수 10:00 KST, 앵커 = 수 06:00 KST
    ws, anchor, day = usm.session_bounds(datetime(2026, 1, 15, 10, 0, tzinfo=et))
    assert (ws, anchor, day) == ("2026-01-15 10:00:00", "2026-01-15 06:00:00", "2026-01-15")


def test_build_before_first_cycle_is_waiting_note(tmp_path, monkeypatch):
    db = str(tmp_path / "us.db")
    _mk_db(db, BASE_TRADES)
    mon = _monitor(db, monkeypatch)
    payload = mon.build()
    assert payload["rows"] == [] and "웜업" in payload["note"]


def test_cycle_aggregates_session_only_with_anchor(tmp_path, monkeypatch):
    db = str(tmp_path / "us.db")
    _mk_db(db, BASE_TRADES, status={"last_flush_at": "2026-08-26 10:01:00"})
    mon = _monitor(db, monkeypatch)
    mon._cycle()
    payload = mon.build(sort="value", limit=30)

    by_sym = {r["symbol"]: r for r in payload["rows"]}
    assert "BBB" not in by_sym                      # 세션 체결 없음 → 제외
    aaa = by_sym["AAA"]
    assert aaa["price"] == 102.0                    # latest
    assert abs(aaa["change_pct"] - 2.0) < 1e-9      # 102/100 − 1 (애프터장 06:30 은 앵커 아님)
    assert aaa["value"] == 101.0 * 10 + 102.0 * 20  # 세션 2건만 (04:59 제외)
    assert aaa["volume"] == 30
    assert by_sym["CCC"]["change_pct"] is None      # 과거 이력 없음
    assert payload["asof"] == "2026-08-26 10:00:00"
    assert payload["feed_at"] == "2026-08-26 10:01:00"
    assert payload["day"] == DAY and payload["market"] == "us"
    # 거래대금 내림차순 rank: AAA(3060) > CCC(700)
    assert [r["symbol"] for r in payload["rows"]] == ["AAA", "CCC"]
    assert [r["rank"] for r in payload["rows"]] == [1, 2]


def test_incremental_cursor_no_double_count(tmp_path, monkeypatch):
    db = str(tmp_path / "us.db")
    _mk_db(db, BASE_TRADES)
    mon = _monitor(db, monkeypatch)
    mon._cycle()
    con = sqlite3.connect(db)
    con.execute("INSERT INTO trades VALUES (?,?,?,?,?)",
                ("AAA", "2026-08-26 10:30:00", 103.0, 5, "2026-08-26 10:30:00"))
    con.execute("INSERT OR REPLACE INTO latest VALUES (?,?,?,?,?)",
                ("AAA", 103.0, 5, "2026-08-26 10:30:00", "2026-08-26 10:30:00"))
    con.commit()
    con.close()
    mon._cycle()
    aaa = {r["symbol"]: r for r in mon.build()["rows"]}["AAA"]
    assert aaa["value"] == 101.0 * 10 + 102.0 * 20 + 103.0 * 5   # 기존분 재합산 금지
    assert aaa["price"] == 103.0


def test_session_rollover_resets_aggregates(tmp_path, monkeypatch):
    db = str(tmp_path / "us.db")
    _mk_db(db, BASE_TRADES)
    mon = _monitor(db, monkeypatch)
    mon._cycle()
    assert mon._agg["AAA"][0] == 30
    # 다음 거래일 경계로 넘어가면 세션 집계가 비고, 새 세션 체결만 남는다
    monkeypatch.setattr(usm, "session_bounds",
                        lambda now_et=None: ("2026-08-27 09:00:00",
                                             "2026-08-27 05:00:00", "2026-08-27"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO trades VALUES (?,?,?,?,?)",
                ("AAA", "2026-08-27 09:05:00", 110.0, 2, "2026-08-27 09:05:00"))
    con.execute("INSERT OR REPLACE INTO latest VALUES (?,?,?,?,?)",
                ("AAA", 110.0, 2, "2026-08-27 09:05:00", "2026-08-27 09:05:00"))
    con.commit()
    con.close()
    mon._cycle()
    aaa = {r["symbol"]: r for r in mon.build()["rows"]}["AAA"]
    assert aaa["volume"] == 2 and aaa["value"] == 220.0
    # 새 앵커 = 새 경계(27일 05:00) 이전 마지막 체결 = 26일 10:00 CCC 아님, AAA 는 102.0
    assert abs(aaa["change_pct"] - (110.0 / 102.0 - 1) * 100) < 1e-9
