"""뉴스/영상 API — 영상 요약(/news/video).

Plaud 에 `[youtube_YYMMDD_채널]` 제목으로 올린 녹음을 worker(PLAUD_VIDEO, llm 큐)가 한 문단으로 요약해
`video_digests` 에 쌓는다. 여기는 읽기와 "지금 확인"(작업 넣기)만 한다.
⚠️요약이 없는 행(pending·failed)도 내려준다 — 화면이 "대기/실패"를 보여야 빠진 것과 구분된다.
⚠️전사문은 저장하지 않으므로 내려줄 것도 없다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.sec_sync import VIDEO_AT, enqueue_video_now
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/news", tags=["news"])
KST = ZoneInfo("Asia/Seoul")
SOURCE = "plaud_video"


def _iso(v):
    return v.isoformat() if v is not None else None


@router.get("/videos")
def list_videos(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    """영상 날짜(제목의 YYMMDD)가 최근 `days` 일 안인 것, 최근이 위."""
    since = datetime.now(timezone.utc).astimezone(KST).date() - timedelta(days=days)
    rows = db.execute(text(
        "SELECT id, plaud_file_id, title, source_tag, video_date, channel, recorded_at, summary_ko, status, error, "
        "model, updated_at FROM video_digests WHERE video_date >= :since "
        "ORDER BY video_date DESC, recorded_at DESC NULLS LAST, id DESC"), {"since": since}).mappings().all()
    src = db.execute(text(
        "SELECT last_ok_at, last_error_at, last_error_kind, last_error_message FROM source_status "
        "WHERE source = :s"), {"s": SOURCE}).mappings().first()
    job = db.execute(text(
        "SELECT status, created_at, finished_at, error_message FROM jobs WHERE job_type = 'PLAUD_VIDEO' "
        "ORDER BY created_at DESC LIMIT 1")).mappings().first()
    return {
        "days": days,
        "schedule": f"매일 {VIDEO_AT[0]:02d}:{VIDEO_AT[1]:02d} KST 이후 한 번",
        "items": [{
            "id": r["id"], "plaud_file_id": r["plaud_file_id"], "title": r["title"],
            "source_tag": r["source_tag"], "video_date": _iso(r["video_date"]), "channel": r["channel"],
            "recorded_at": _iso(r["recorded_at"]), "summary_ko": r["summary_ko"], "status": r["status"],
            "error": r["error"], "model": r["model"], "updated_at": _iso(r["updated_at"]),
        } for r in rows],
        "source": {
            "last_ok_at": _iso(src["last_ok_at"]), "last_error_at": _iso(src["last_error_at"]),
            "last_error_kind": src["last_error_kind"], "last_error_message": src["last_error_message"],
        } if src else None,
        "last_job": {
            "status": job["status"], "created_at": _iso(job["created_at"]),
            "finished_at": _iso(job["finished_at"]), "error_message": job["error_message"],
        } if job else None,
    }


@router.post("/videos/refresh", status_code=202)
def refresh_videos(db: Session = Depends(get_db)) -> dict:
    """"지금 확인" — PLAUD_VIDEO 작업을 넣는다. 이미 대기·실행 중이면 그대로 둔다."""
    job = enqueue_video_now(db)
    db.commit()
    return {"queued": job is not None, "job_id": str(job.id) if job else None}
