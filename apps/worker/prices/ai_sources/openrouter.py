"""OpenRouter 일간 토큰 — `GET openrouter.ai/api/v1/datasets/rankings-daily`. **키 필요**.

★드라이브 `openrouter.py` 규칙:
  · 날짜는 UTC. **완결일 = UTC 어제까지** — 오늘은 부분일이라 받지 않는다.
  · 90일 청크로 나눠 받는다. FLOOR = 2025-01-01(데이터셋 시작일, 앞은 클램프/400).
  · `meta.as_of` 를 보존한다 — 재게시 시 "as of {as_of}" 인용이 약관이다(CC BY 4.0).
  · 하루 = 상위 50 모델 + `other`(top-50 밖 합) 1행. 모델 결측은 "51위 밖"이지 0 이 아니다
    → 여기서 0 을 채우지 않는다.
  · 레이트리밋 30/분·500/일 — 호출 쪽이 6h 캐시한다(FLOOR 부터 ≈8 요청/회).

⚠️키가 없으면 **부르지 않고** status="key_missing" 을 돌려준다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from . import config

FLOOR = date.fromisoformat(config.OPENROUTER_FLOOR)


def last_complete_day(now: datetime | None = None) -> date:
    """UTC 완결일(어제)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).date() - timedelta(days=1)


def chunks(start: date, end: date, size: int = config.OPENROUTER_CHUNK_DAYS) -> list[tuple[date, date]]:
    """[start, end] 를 size 일 이하 구간으로. 양끝 포함."""
    start = max(start, FLOOR)
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        hi = min(cur + timedelta(days=size - 1), end)
        out.append((cur, hi))
        cur = hi + timedelta(days=1)
    return out


def parse(payload: dict) -> tuple[list[tuple[date, str, int]], dict]:
    """→ ([(날짜, model_permaslug, total_tokens)], meta). total_tokens 는 문자열로 온다."""
    rows: list[tuple[date, str, int]] = []
    for row in (payload or {}).get("data") or []:
        try:
            day = date.fromisoformat(str(row.get("date"))[:10])
            tokens = int(float(row.get("total_tokens")))
        except (TypeError, ValueError):
            continue
        slug = str(row.get("model_permaslug") or "").strip()
        if slug:
            rows.append((day, slug, tokens))
    return rows, dict((payload or {}).get("meta") or {})


def fetch_window(
    client: httpx.Client, start: date, end: date, *, modality: str | None = None
) -> tuple[list[tuple[date, str, int]], dict]:
    params = {"start_date": start.isoformat(), "end_date": end.isoformat(), "period": "day"}
    if modality:
        params["modality"] = modality
    response = client.get(config.OPENROUTER_RANKINGS, params=params)
    response.raise_for_status()
    return parse(response.json())


def fetch(
    api_key: str | None,
    *,
    start: date = FLOOR,
    end: date | None = None,
    modality: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """→ {"status", "rows", "as_of", "start", "end"}. 키 없으면 호출 없이 key_missing."""
    if not api_key:
        return {"status": "key_missing", "rows": [], "as_of": None, "start": None, "end": None}
    end = end or last_complete_day()
    rows: list[tuple[date, str, int]] = []
    as_of: str | None = None
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": config.UA}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for lo, hi in chunks(start, end):
            got, meta = fetch_window(client, lo, hi, modality=modality)
            rows.extend(got)
            if meta.get("as_of") and (as_of is None or str(meta["as_of"]) > as_of):
                as_of = str(meta["as_of"])
    if not rows:
        raise RuntimeError("openrouter: 빈 응답")
    return {"status": "ok", "rows": rows, "as_of": as_of, "start": max(start, FLOOR), "end": end}
