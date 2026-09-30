"""OpenRouter tool-calling 토큰 — 같은 rankings-daily 를 두 번(전체 / `modality=tool_calling`).

★드라이브 `tool_calling.py` 규칙: **전체 쪽 날짜가 기준**이다. 그날 tool_calling 행이
  없으면 tool=0 으로 채운다(전체는 있는데 tool 이 비면 "그날 툴콜 0"). tool 에만 있는
  날짜는 버린다(분모가 없다). 원값 두 개만 돌려주고 비율은 화면 몫이다.
"""
from __future__ import annotations

from datetime import date

from . import openrouter


def daily_totals(rows: list[tuple[date, str, int]]) -> dict[date, int]:
    """모델 행(+`other`)을 날짜별로 합친다."""
    out: dict[date, int] = {}
    for day, _slug, tokens in rows:
        out[day] = out.get(day, 0) + tokens
    return out


def merge(total_rows, tool_rows) -> list[tuple[date, int, int]]:
    """→ [(날짜, total, tool)] 오름차순. 날짜 = 전체 쪽, tool 결측 = 0."""
    total = daily_totals(total_rows)
    tool = daily_totals(tool_rows)
    return [(day, total[day], tool.get(day, 0)) for day in sorted(total)]


def fetch(api_key: str | None, **kwargs) -> dict:
    """→ {"status", "rows": [(date, total, tool)], "as_of"}."""
    if not api_key:
        return {"status": "key_missing", "rows": [], "as_of": None}
    total = openrouter.fetch(api_key, **kwargs)
    tool = openrouter.fetch(api_key, modality="tool_calling", **kwargs)
    as_of = max(filter(None, [total.get("as_of"), tool.get("as_of")]), default=None)
    return {"status": "ok", "rows": merge(total["rows"], tool["rows"]), "as_of": as_of}
