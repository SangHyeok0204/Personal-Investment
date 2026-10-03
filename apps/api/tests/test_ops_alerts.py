"""하네스 O1 — 서버측 트립와이어(core/ops_alerts) 전이와 /alerts 노출."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import ops_alerts
from app.core.ai_snapshot_sync import today_kst
from app.core.config import settings
from app.models import Job, OpsAlertState, SourceStatus

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_DAILY_CAP", 40)
    (tmp_path / "llm").mkdir()
    return tmp_path


def _rows(db, kind):
    db.expire_all()
    return db.execute(select(OpsAlertState).where(OpsAlertState.kind == kind)).scalars().all()


def _running_job(db, minutes, job_type="TEST_JOB"):
    job = Job(id=uuid.uuid4(), job_type=job_type, status="RUNNING", queue="llm",
              started_at=NOW - timedelta(minutes=minutes))
    db.add(job)
    db.commit()
    return job


def test_job_stuck_opens_once_then_resolves(db, storage):
    job = _running_job(db, 61)
    _running_job(db, 30)                       # 상한 아래 — 안 잡힌다

    assert ops_alerts.tick(db, NOW)["opened"] == [f"JOB_STUCK:{job.id}"]
    assert ops_alerts.tick(db, NOW + timedelta(minutes=5)) == {"opened": [], "resolved": []}
    rows = _rows(db, "JOB_STUCK")
    assert len(rows) == 1 and rows[0].resolved_at is None
    assert rows[0].last_seen > rows[0].first_seen

    job.status = "SUCCESS"
    db.commit()
    assert ops_alerts.tick(db, NOW + timedelta(minutes=10))["resolved"] == [f"JOB_STUCK:{job.id}"]
    assert _rows(db, "JOB_STUCK")[0].resolved_at is not None


def test_job_stuck_uses_wallclock_limit(db, storage):
    _running_job(db, 170, "EARNINGS_REVENUE")     # 상한 3시간 — 실측 최대 127분, 정상 범위
    assert ops_alerts.tick(db, NOW)["opened"] == []
    _running_job(db, 181, "EARNINGS_REVENUE")
    assert len(ops_alerts.tick(db, NOW)["opened"]) == 1


def test_stuck_limits_match_worker_wallclock():
    """API 경보 상한은 worker 벽시계 상한과 같아야 한다 — 어긋나면 잘린 뒤에야 알리거나, 정상 작업을 경보한다."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "worker" / "wallclock.py"
    spec = importlib.util.spec_from_file_location("worker_wallclock", path)
    wc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wc)
    assert ops_alerts.STUCK_LIMITS == wc.LIMITS
    assert ops_alerts.STUCK_DEFAULT_SECONDS == wc.DEFAULT_LIMIT_SECONDS


def test_source_error_after_6h(db, storage):
    db.add(SourceStatus(source="investing", kind="source", last_ok_at=NOW - timedelta(hours=8),
                        last_error_at=NOW - timedelta(hours=7), last_error_kind="timeout"))
    db.add(SourceStatus(source="fresh", kind="source", last_ok_at=NOW - timedelta(hours=2),
                        last_error_at=NOW - timedelta(hours=1), last_error_kind="timeout"))
    db.add(SourceStatus(source="ok", kind="source", last_ok_at=NOW, last_error_at=NOW - timedelta(days=2)))
    # 사람이 일부러 멈춘 것(STOP) — 마지막 성공이 오래돼도 원천 고장이 아니다.
    db.add(SourceStatus(source="claude", kind="source", last_ok_at=NOW - timedelta(days=1),
                        last_error_at=NOW - timedelta(minutes=7), last_error_kind="stopped"))
    db.commit()
    assert ops_alerts.tick(db, NOW)["opened"] == ["SOURCE_ERROR:investing"]
    assert len(_rows(db, "SOURCE_ERROR")) == 1


def test_llm_cap_80pct(db, storage):
    counter = storage / "llm" / f"calls-{today_kst():%Y-%m-%d}.json"
    counter.write_text(json.dumps({"n": 31}))
    assert ops_alerts.tick(db, NOW)["opened"] == []
    counter.write_text(json.dumps({"n": 33}))
    assert ops_alerts.tick(db, NOW)["opened"] == ["LLM_CAP_80PCT"]
    assert _rows(db, "LLM_CAP_80PCT")[0].detail == {"calls_today": 33, "cap": 40}
    counter.unlink()
    assert ops_alerts.tick(db, NOW)["resolved"] == ["LLM_CAP_80PCT"]


def test_llm_escalation_packet(db, storage):
    esc = storage / "llm" / "escalations"
    esc.mkdir()
    (esc / "2026-10-03-LLM_JUDGE-42.json").write_text("{}")
    (esc / "2026-10-03-LLM_JUDGE-43.json.tmp").write_text("{}")   # 쓰는 중 — 안 센다
    assert ops_alerts.tick(db, NOW)["opened"] == ["LLM_ESCALATION:2026-10-03-LLM_JUDGE-42.json"]
    assert ops_alerts.tick(db, NOW)["opened"] == []


def test_alerts_endpoint_lists_ops_and_ack_hides(client, db):
    _running_job(db, 61)
    ops_alerts.tick(db, NOW)

    ops = client.get("/api/v1/alerts").json()["ops"]
    assert [o["kind"] for o in ops] == ["JOB_STUCK"]
    assert "RUNNING" in ops[0]["message"]

    res = client.post(f"/api/v1/alerts/ops/{ops[0]['key']}/ack")
    assert res.status_code == 200
    assert client.get("/api/v1/alerts").json()["ops"] == []
    assert client.post("/api/v1/alerts/ops/nope/ack").status_code == 404

    # 확인해도 열린 채다 — 다음 판정이 다시 알리지 않는다.
    assert ops_alerts.tick(db, NOW)["opened"] == []
    assert _rows(db, "JOB_STUCK")[0].resolved_at is None
