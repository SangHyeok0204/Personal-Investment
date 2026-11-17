"""채용 공고 API — 화면 `/careers` 가 쓴다.

★2026-11-02 사용자 요청: finance-jobs 스킬(~/.claude/skills/finance-jobs)이 크롤링한 신입/인턴 공고 중
  **지금 지원 가능한 것**만 표로. 원천은 스킬 출력 JSON 을 저장한 `storage/jobs/postings.json`
  (`scripts/crawl-jobs.sh` 가 만든다). DB 를 거치지 않는다 — 크롤 한 번이 통째로 한 스냅샷이다.
⚠️마감일을 모르는 공고는 지원 가능으로 둔다(모름 ≠ 마감).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.core.config import settings
from app.core.errors import AppError

router = APIRouter(prefix="/api/v1/careers", tags=["careers"])

KST = ZoneInfo("Asia/Seoul")
FIELDS = ("company", "apply_period", "work_period", "kind", "role", "category", "location",
          "hire_type", "deadline", "posted", "title", "url")


def postings_path() -> Path:
    return Path(settings.STORAGE_DIR) / "jobs" / "postings.json"


def open_postings(raw: dict, today: date) -> dict:
    """스킬 출력 → 화면 행. 마감이 오늘 이전인 공고는 뺀다. 출처는 한국어 이름(대학 게시판은 게시판 이름)."""
    names = {s["key"]: s["name"] for s in raw.get("sources", [])}
    rows, closed = [], 0
    for j in raw.get("jobs", []):
        if j.get("deadline") and j["deadline"] < today.isoformat():
            closed += 1
            continue
        row = {k: j.get(k) or "" for k in FIELDS}
        # source_names: 같은 공고가 여러 출처에 있어 한 행으로 합친 경우(스킬 2단계) "금투협, KKB"
        row["source"] = j.get("source_names") or (
            j.get("board") if j.get("source") == "univ" else names.get(j.get("source"), j.get("source", ""))
        )
        rows.append(row)
    return {
        "generated_at": raw.get("generated_at"),
        "since": raw.get("since"),
        "today": today.isoformat(),
        "closed_dropped": closed,
        "hidden_by_category": raw.get("hidden_by_category", {}),
        "sources": raw.get("sources", []),
        "jobs": rows,
    }


@router.get("/postings")
def postings() -> dict:
    p = postings_path()
    if not p.exists():
        raise AppError(404, "NO_POSTINGS", "아직 수집한 채용 공고가 없습니다 — scripts/crawl-jobs.sh 를 실행하세요.")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AppError(500, "BAD_POSTINGS", f"postings.json 을 읽지 못했습니다: {e}") from e
    return open_postings(raw, datetime.now(KST).date())
