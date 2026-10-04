"""하네스 L4 — 작업별 벽시계 상한. 굳은 핸들러는 상한 + 30초 안에 FAILED(timeout_wallclock), 다음 작업은 돈다,
자식 프로세스(Playwright 자리)는 손자(크롬 자리 — 별도 세션으로 떠서 그룹 kill 로는 안 죽는다)까지 남지 않는다."""
import json
import subprocess
import sys
import threading
import time
import uuid

import pytest
from sqlalchemy import text

import main
import wallclock
from handlers import earnings_revenue

LIMIT = 2


def _job(engine, job_type, payload=None):
    jid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO jobs (id, job_type, status, payload) VALUES (:i, :t, 'PENDING', CAST(:p AS JSONB))"),
                  {"i": jid, "t": job_type, "p": json.dumps(payload or {})})
    return jid


def _row(engine, jid):
    with engine.begin() as c:
        return c.execute(text("SELECT status, error_message FROM jobs WHERE id = :i"), {"i": jid}).one()


def _pgrep(marker):
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.split()
    return [p for p in out if p]


def hang_with_grandchild(marker):
    """자식 프로세스에서 — 브라우저처럼 **별도 세션**의 손자를 띄우고 영원히 막힌다."""
    subprocess.Popen([sys.executable, "-c", f"import time; time.sleep(600)  # {marker}"], start_new_session=True)
    while True:
        time.sleep(1)


@pytest.fixture
def tiny_limits(monkeypatch):
    monkeypatch.setitem(wallclock.LIMITS, "HANG_THREAD", LIMIT)
    monkeypatch.setitem(wallclock.LIMITS, "HANG_CHILD", LIMIT)
    monkeypatch.setattr(wallclock, "GRACE_SECONDS", 1)
    monkeypatch.setattr(wallclock, "KILL_GRACE_SECONDS", 2)


def test_limits_per_type():
    # 실측 최댓값 × 약 1.5 (2026-10-03) — 정상 크롤(EARNINGS_REVENUE 최대 127분)이 잘리면 안 된다
    assert wallclock.limit_for("EARNINGS_REVENUE") == 3 * 3600
    assert wallclock.limit_for("SEC_13F_BACKFILL") == 4 * 3600
    assert wallclock.limit_for("SEC_FORM4") == 3 * 3600
    assert wallclock.limit_for("UNKNOWN_TYPE") == 3600
    assert earnings_revenue.collect.__defaults__[1] is earnings_revenue.crawl_isolated


def test_blocking_thread_handler_fails_and_next_job_runs(db, tmp_path, monkeypatch, tiny_limits):
    release = threading.Event()
    monkeypatch.setitem(main.HANDLERS, "HANG_THREAD", lambda *a: release.wait(120))
    hung = _job(db, "HANG_THREAD")
    nxt = _job(db, "TEST_JOB", {"hello": "after"})
    t0 = time.monotonic()
    assert main.run_one_cycle(db, str(tmp_path)) is True
    took = time.monotonic() - t0
    release.set()
    status, err = _row(db, hung)
    assert status == "FAILED" and err.startswith("timeout_wallclock") and took < LIMIT + 30
    with db.begin() as c:
        kind = c.execute(text("SELECT last_error_kind FROM source_status WHERE source = 'job:HANG_THREAD'")).scalar()
    assert kind == "timeout_wallclock"
    assert main.run_one_cycle(db, str(tmp_path)) is True
    assert _row(db, nxt)[0] == "SUCCESS"


def test_blocking_child_is_killed_with_grandchild(db, tmp_path, monkeypatch, tiny_limits):
    marker = f"wallclock-orphan-{uuid.uuid4().hex[:8]}"
    monkeypatch.setitem(main.HANDLERS, "HANG_CHILD",
                        lambda *a: wallclock.run_in_child(hang_with_grandchild, marker))
    hung = _job(db, "HANG_CHILD")
    nxt = _job(db, "TEST_JOB", {"hello": "after"})
    t0 = time.monotonic()
    try:
        main.run_one_cycle(db, str(tmp_path))
        took = time.monotonic() - t0
        status, err = _row(db, hung)
        assert status == "FAILED" and err.startswith("timeout_wallclock") and took < LIMIT + 30
        assert _pgrep(marker) == []                       # 손자(브라우저 자리)까지 남지 않는다
        assert main.run_one_cycle(db, str(tmp_path)) is True
        assert _row(db, nxt)[0] == "SUCCESS"
    finally:
        subprocess.run(["pkill", "-9", "-f", marker])


def test_run_in_child_returns_value_and_reraises():
    assert wallclock.run_in_child(sorted, [3, 1, 2], timeout=60) == [1, 2, 3]
    with pytest.raises(ValueError):
        wallclock.run_in_child(int, "x", timeout=60)


def progress_then_die(n, on_progress):
    for i in range(n):
        on_progress(i)
    raise RuntimeError("driver died")


def test_run_in_child_streams_progress_before_failure():
    """★2026-10-04 — 자식이 죽어도 그 전에 흘려보낸 중간 결과는 부모가 이미 받았다."""
    seen = []
    with pytest.raises(RuntimeError, match="driver died"):
        wallclock.run_in_child(progress_then_die, 3, timeout=60, on_progress=seen.append)
    assert seen == [0, 1, 2]


def progress_forever(marker, on_progress):
    """자식 프로세스에서 — 별도 세션의 손자를 띄우고 진행 상황을 끝없이 흘려보낸다."""
    subprocess.Popen([sys.executable, "-c", f"import time; time.sleep(600)  # {marker}"], start_new_session=True)
    i = 0
    while True:
        on_progress(i)
        i += 1
        time.sleep(0.05)


def test_parent_on_progress_error_kills_child_and_propagates(monkeypatch):
    """★2026-10-05 부모 쪽 on_progress(DB 저장 등)가 터지면 자식·손자를 죽이고 그 예외를 그대로 낸다."""
    monkeypatch.setattr(wallclock, "KILL_GRACE_SECONDS", 2)
    marker = f"wallclock-progress-err-{uuid.uuid4().hex[:8]}"

    def on_progress(v):
        if v >= 2:
            raise ValueError("db write failed")

    try:
        t0 = time.monotonic()
        with pytest.raises(ValueError, match="db write failed"):
            wallclock.run_in_child(progress_forever, marker, timeout=60, on_progress=on_progress)
        assert time.monotonic() - t0 < 30
        assert _pgrep(marker) == []
    finally:
        subprocess.run(["pkill", "-9", "-f", marker])


def test_timeout_fires_even_while_progress_keeps_streaming(monkeypatch):
    """★2026-10-05 진행 상황이 계속 와도(큐가 비지 않아도) 상한이 지나면 WallClockTimeout — 자손까지 죽인다."""
    monkeypatch.setattr(wallclock, "KILL_GRACE_SECONDS", 2)
    marker = f"wallclock-progress-to-{uuid.uuid4().hex[:8]}"
    seen = []
    try:
        t0 = time.monotonic()
        with pytest.raises(wallclock.WallClockTimeout, match="^timeout_wallclock"):
            wallclock.run_in_child(progress_forever, marker, timeout=LIMIT, on_progress=seen.append)
        assert time.monotonic() - t0 < LIMIT + 15
        assert len(seen) > 0
        assert _pgrep(marker) == []
    finally:
        subprocess.run(["pkill", "-9", "-f", marker])
