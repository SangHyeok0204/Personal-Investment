"""B1 — 비상 정지(STOP 파일 · LLM_DAILY_CAP=0)는 호출도 셈도 하지 않고, 작업은 PENDING 으로 남긴다. 비용은 기록만."""
import json
import subprocess
import uuid

import pytest
from sqlalchemy import text

import main
from llm import cli


@pytest.fixture(autouse=True)
def fake_bin(tmp_path, monkeypatch):
    b = tmp_path / "claude"
    b.write_text("#!/bin/sh\n")
    b.chmod(0o755)
    monkeypatch.setenv("CLAUDE_BIN", str(b))
    monkeypatch.setenv("LLM_DAILY_CAP", "40")


OK = json.dumps({"is_error": False, "result": "ok", "total_cost_usd": 0.25, "modelUsage": {"m": {}}})


class Runner:
    def __init__(self):
        self.calls = 0

    def __call__(self, cmd, **kw):
        self.calls += 1
        return subprocess.CompletedProcess(cmd, 0, stdout=OK, stderr="")


def _stop(storage):
    p = storage / "llm"
    p.mkdir(parents=True, exist_ok=True)
    (p / "STOP").touch()
    return p / "STOP"


def _counter(storage):
    return json.loads(next((storage / "llm").glob("calls-*.json")).read_text())


# ── run_claude ──────────────────────────────────────────────────────────────


def test_stop_file_blocks_call_without_counting(tmp_path):
    _stop(tmp_path)
    runner = Runner()
    with pytest.raises(cli.LlmError) as e:
        cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    assert e.value.kind == "stopped"
    assert runner.calls == 0
    assert cli.calls_today(str(tmp_path)) == 0


def test_cap_zero_is_the_same_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_DAILY_CAP", "0")
    runner = Runner()
    with pytest.raises(cli.LlmError) as e:
        cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    assert e.value.kind == "stopped"          # 'cap' 이 아니라 같은 정지 경로
    assert runner.calls == 0 and cli.calls_today(str(tmp_path)) == 0


def test_after_rm_the_call_runs(tmp_path):
    stop = _stop(tmp_path)
    runner = Runner()
    with pytest.raises(cli.LlmError):
        cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    stop.unlink()
    r = cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    assert r.text == "ok" and runner.calls == 1 and cli.calls_today(str(tmp_path)) == 1


def test_usd_notional_accumulates_and_keeps_n(tmp_path):
    runner = Runner()
    cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    cli.run_claude("x", storage_dir=str(tmp_path), runner=runner)
    data = _counter(tmp_path)
    assert data == {"n": 2, "usd_notional": 0.5}
    cli._bump(str(tmp_path))                  # 셈을 올려도 비용 기록은 남는다
    assert _counter(tmp_path)["usd_notional"] == 0.5


# ── worker ─────────────────────────────────────────────────────────────────


def _insert(db, queue="llm", job_type="LLM_FAKE", attempts=0):
    job_id = uuid.uuid4()
    with db.begin() as conn:
        conn.execute(text("INSERT INTO jobs (id, job_type, status, payload, queue, attempts) "
                          "VALUES (:id, :t, 'PENDING', '{}'::jsonb, :q, :a)"),
                     {"id": job_id, "t": job_type, "q": queue, "a": attempts})
    return job_id


def _job(db, job_id):
    with db.begin() as conn:
        return conn.execute(text("SELECT status, attempts, started_at FROM jobs WHERE id=:id"),
                            {"id": job_id}).mappings().first()


@pytest.fixture
def fake_llm_handler(monkeypatch):
    runner = Runner()

    def handler(engine, job_id, payload, storage_dir, log_job):
        return {"text": cli.run_claude("x", storage_dir=storage_dir, runner=runner).text}

    monkeypatch.setitem(main.HANDLERS, "LLM_FAKE", handler)
    return runner


def test_stopped_job_is_requeued_without_counting_an_attempt(db, tmp_path, fake_llm_handler):
    # 집은 뒤에 STOP 이 생긴 경우(경합) — run_claude 가 'stopped' 를 올리면 worker 가 되돌린다.
    job_id = _insert(db, attempts=1)
    assert main.claim_job(db, ("llm",)) == job_id
    assert _job(db, job_id)["attempts"] == 2
    _stop(tmp_path)
    main.process_job(db, main.fetch_job(db, job_id), str(tmp_path))
    row = _job(db, job_id)
    assert (row["status"], row["attempts"], row["started_at"]) == ("PENDING", 1, None)
    assert fake_llm_handler.calls == 0 and cli.calls_today(str(tmp_path)) == 0
    with db.begin() as conn:
        st = conn.execute(text("SELECT last_error_kind FROM source_status WHERE source='claude'")).scalar()
    assert st == "stopped"


def test_claim_skipped_while_stopped_then_runs_after_rm(db, tmp_path, fake_llm_handler):
    job_id = _insert(db)
    stop = _stop(tmp_path)
    for _ in range(3):                        # 정지 중에는 집지 않는다 — 헛돌지 않는다
        assert main.run_one_cycle(db, str(tmp_path), ("llm",)) is False
    row = _job(db, job_id)
    assert (row["status"], row["attempts"]) == ("PENDING", 0)
    assert fake_llm_handler.calls == 0 and cli.calls_today(str(tmp_path)) == 0

    stop.unlink()
    assert main.run_one_cycle(db, str(tmp_path), ("llm",)) is True
    row = _job(db, job_id)
    assert (row["status"], row["attempts"]) == ("SUCCESS", 1)
    assert fake_llm_handler.calls == 1 and cli.calls_today(str(tmp_path)) == 1


def test_cap_zero_skips_claim_too(db, tmp_path, monkeypatch, fake_llm_handler):
    monkeypatch.setenv("LLM_DAILY_CAP", "0")
    job_id = _insert(db)
    assert main.run_one_cycle(db, str(tmp_path), ("llm",)) is False
    assert (_job(db, job_id)["status"], _job(db, job_id)["attempts"]) == ("PENDING", 0)


def test_stop_does_not_block_other_queues(db, tmp_path):
    _stop(tmp_path)
    llm = _insert(db, job_type="TEST_JOB")
    other = _insert(db, queue="default", job_type="TEST_JOB")
    assert main.run_one_cycle(db, str(tmp_path), ("llm", "default")) is True
    assert _job(db, other)["status"] == "SUCCESS"
    assert _job(db, llm)["status"] == "PENDING"
