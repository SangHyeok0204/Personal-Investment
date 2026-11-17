"""채용 공고 API — 스킬 출력 JSON 을 지원 가능한 행으로."""
import json
from datetime import date
from pathlib import Path

from app.api import careers
from app.core.config import settings

RAW = {
    "generated_at": "2026-11-02T23:40:00",
    "since": "2026-10-19",
    "hidden_by_category": {"은행": 3},
    "sources": [
        {"key": "kofia", "name": "금투협", "url": "https://www.kofia.or.kr", "count": 2},
        {"key": "univ", "name": "대학 취업게시판", "url": "", "count": 1},
    ],
    "jobs": [
        {"source": "kofia", "board": "", "company": "A운용", "title": "인턴 모집", "posted": "2026-10-30",
         "url": "https://x/1", "kind": "인턴", "deadline": "2026-11-01", "category": "운용사"},
        {"source": "kofia", "board": "", "company": "B증권", "title": "신입 공채", "posted": "2026-10-31",
         "url": "https://x/2", "kind": "신입", "deadline": "2026-11-02", "role": "IB", "category": "증권사"},
        {"source": "univ", "board": "서울대 컴공", "company": "C퀀트", "title": "Quant Researcher",
         "posted": "2026-10-20", "url": "https://x/3", "kind": "직급 미표기", "deadline": "", "category": "퀀트/프랍"},
    ],
}


def test_open_postings_drops_closed_and_names_source():
    out = careers.open_postings(RAW, date(2026, 11, 2))
    assert [j["company"] for j in out["jobs"]] == ["B증권", "C퀀트"]  # 어제 마감은 빠지고, 오늘 마감은 남는다
    assert out["closed_dropped"] == 1
    assert [j["source"] for j in out["jobs"]] == ["금투협", "서울대 컴공"]
    # 빈 값은 None 이 아니라 빈 문자열 — 마감을 모르는 공고도 남는다
    assert out["jobs"][1]["deadline"] == "" and out["jobs"][1]["role"] == ""


def test_postings_endpoint(client):
    assert client.get("/api/v1/careers/postings").status_code == 404
    p = Path(settings.STORAGE_DIR) / "jobs" / "postings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(RAW, ensure_ascii=False), encoding="utf-8")
    body = client.get("/api/v1/careers/postings").json()
    assert body["generated_at"] == RAW["generated_at"]
    assert {j["company"] for j in body["jobs"]} <= {"A운용", "B증권", "C퀀트"}
