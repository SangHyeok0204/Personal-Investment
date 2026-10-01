"""영상 요약 API(/api/v1/news/videos) 모양 · 07:40 KST 따라잡기 · "지금 확인"."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.sec_sync import DAILY_SLOTS, VIDEO_AT, due, maybe_enqueue
from app.models import Job

UTC = timezone.utc


@pytest.fixture
def vdb(db):
    db.execute(text("TRUNCATE video_digests RESTART IDENTITY"))
    db.commit()
    return db


def _add(db, fid, d, status, summary=None, error=None, recorded=None):
    db.execute(text(
        "INSERT INTO video_digests (plaud_file_id, title, source_tag, video_date, channel, recorded_at, summary_ko, "
        "status, error, model) VALUES (:f, :t, 'youtube', :d, '월가아재', :r, :s, :st, :e, :m)"),
        {"f": fid, "t": f"[youtube_{d:%y%m%d}_월가아재]", "d": d, "r": recorded, "s": summary, "st": status,
         "e": error, "m": "claude-test" if summary else None})
    db.commit()


def test_list_shape_newest_first(client, vdb):
    today = datetime.now(UTC).date()
    _add(vdb, "old", today - timedelta(days=40), "done", summary="옛 요약")
    _add(vdb, "a", today - timedelta(days=1), "done", summary="한 문단 요약.",
         recorded=datetime(2026, 9, 30, 6, 0, tzinfo=UTC))
    _add(vdb, "b", today, "failed", error="LLM timeout: CLI 응답 500초 초과")
    _add(vdb, "c", today, "pending", error="Plaud 전사 없음")
    r = client.get("/api/v1/news/videos?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30 and body["source"] is None and body["last_job"] is None
    assert "07:40" in body["schedule"]
    ids = [i["plaud_file_id"] for i in body["items"]]
    assert ids[2] == "a" and set(ids[:2]) == {"b", "c"} and "old" not in ids
    a = body["items"][2]
    assert set(a) == {"id", "plaud_file_id", "title", "source_tag", "video_date", "channel", "recorded_at",
                      "summary_ko", "status", "error", "model", "updated_at"}
    # 시간대가 붙은 시각(세션 시간대는 KST) — 같은 순간인지 본다
    assert datetime.fromisoformat(a["recorded_at"]) == datetime(2026, 9, 30, 6, 0, tzinfo=UTC)
    assert a["summary_ko"] == "한 문단 요약."
    failed = next(i for i in body["items"] if i["plaud_file_id"] == "b")
    assert failed["summary_ko"] is None and failed["status"] == "failed"      # 실패에 요약을 채우지 않는다
    assert client.get("/api/v1/news/videos?days=0").status_code == 422


def test_list_reports_source_and_last_job(client, vdb):
    vdb.execute(text("INSERT INTO source_status (source, kind, last_error_at, last_error_kind, last_error_message) "
                     "VALUES ('plaud_video', 'source', now(), 'logged_out', 'Plaud 로그아웃')"))
    vdb.add(Job(job_type="PLAUD_VIDEO", queue="llm", status="FAILED", error_message="x"))
    vdb.commit()
    body = client.get("/api/v1/news/videos").json()
    assert body["items"] == [] and body["source"]["last_error_kind"] == "logged_out"
    assert body["last_job"]["status"] == "FAILED"


def test_refresh_enqueues_once(client, vdb):
    first = client.post("/api/v1/news/videos/refresh")
    assert first.status_code == 202 and first.json()["queued"] is True
    assert client.post("/api/v1/news/videos/refresh").json() == {"queued": False, "job_id": None}
    jobs = vdb.execute(text("SELECT queue, status FROM jobs WHERE job_type = 'PLAUD_VIDEO'")).all()
    assert jobs == [("llm", "PENDING")]


def test_video_daily_slot_catch_up():
    assert DAILY_SLOTS["PLAUD_VIDEO"] == VIDEO_AT == (7, 40)
    kst = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=timezone(timedelta(hours=9)))  # noqa: E731
    job = lambda status, t: SimpleNamespace(status=status, created_at=t)  # noqa: E731
    assert not due("PLAUD_VIDEO", job("SUCCESS", kst(1, 7, 45)), kst(2, 7, 30))   # 07:40 전 — 어제 돈 것으로 충분
    assert due("PLAUD_VIDEO", job("SUCCESS", kst(1, 7, 45)), kst(2, 7, 41))       # 07:40 지남
    # 맥이 자고 있었다 — 깨어난 오후에 따라잡는다
    assert due("PLAUD_VIDEO", job("SUCCESS", kst(1, 7, 45)), kst(2, 15, 0))
    assert not due("PLAUD_VIDEO", job("SUCCESS", kst(2, 7, 45)), kst(2, 15, 0))   # 오늘 이미
    assert not due("PLAUD_VIDEO", job("RUNNING", kst(1, 7, 45)), kst(2, 9, 0))    # 진행 중
    assert not due("PLAUD_VIDEO", job("FAILED", kst(2, 8, 0)), kst(2, 9, 0))      # 실패도 하루 한 번
    assert due("PLAUD_VIDEO", None, kst(2, 9, 0))


def test_maybe_enqueue_puts_video_on_llm_queue(vdb):
    now = datetime(2026, 10, 1, 23, 0, tzinfo=UTC)          # 10-02 08:00 KST
    added = maybe_enqueue(vdb, now)
    video = [j for j in added if j.job_type == "PLAUD_VIDEO"]
    assert len(video) == 1 and video[0].queue == "llm"
    assert not [j for j in maybe_enqueue(vdb, now) if j.job_type == "PLAUD_VIDEO"]   # 대기 중이면 또 넣지 않는다
