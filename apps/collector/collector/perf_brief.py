"""[성과보고] 데일리·위클리 성과 브리프 리더 (2026-07-28).

`S:\\GE\\Wonjae\\07_회의자료\\정기미팅` 을 read-only 로 마운트한 컨테이너 경로
(`/srv/legacy/perf_brief`)에서, performance-brief 스킬이 생성한 JSON 을 읽어
대시보드가 네이티브 React 로 렌더할 payload 를 만든다.

파일명 규약 (스킬이 HTML 대신 이 JSON 을 생성한다):
    daily_YYYYMMDD.json              — 기준일 YYYYMMDD 데일리
    weekly_YYYYMMDD_YYYYMMDD.json    — 시작일_종료일 위클리

요일 규칙(사용자 확정): 월=위클리, 화~금=데일리, 주말=예정 없음.

'오늘 작성분'이 아직 없으면 status="pending" 으로 응답하고 **수치는 내려보내지
않는다** — 낡은 보고서를 오늘 것으로 오인하는 사고를 막는 게 이 규칙의 목적이라,
latest 는 무슨 보고서가 마지막이었는지 알리는 메타(기준일·작성일)만 담는다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

PERF_BRIEF_ROOT = os.environ.get("PERF_BRIEF_DIR", "/srv/legacy/perf_brief")

_DAILY_RE = re.compile(r"^daily_(\d{8})\.json$", re.IGNORECASE)
_WEEKLY_RE = re.compile(r"^weekly_(\d{8})_(\d{8})\.json$", re.IGNORECASE)

# path → (mtime, 파싱된 JSON, mtime 날짜). SMB 왕복을 매 폴링마다 반복하지 않기 위한 캐시.
# 한 요청이 건드리는 파일은 최대 2개(latest + expected)라 상한을 작게 잡는다.
_cache: dict[str, tuple[float, dict, str]] = {}
_CACHE_MAX = 4


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _dot(iso: str) -> str:
    return iso.replace("-", ".")


def _scan() -> list[dict]:
    """폴더의 성과보고 JSON 목록. 파일을 열지 않고 이름만으로 분류한다.

    성능: 항목당 stat 을 부르지 않는다 — SMB 에서 항목별 getsize/getmtime 이
    api 예산을 넘겼던 회의 탭의 전례(meeting.list_dir)를 그대로 따른다.
    """
    try:
        with os.scandir(PERF_BRIEF_ROOT) as it:
            names = [de.name for de in it if not de.name.startswith(".")]
    except OSError:
        return []

    out: list[dict] = []
    for name in names:
        m = _DAILY_RE.match(name)
        if m:
            out.append({"kind": "daily", "asOf": _iso(m.group(1)),
                        "start": None, "end": _iso(m.group(1)), "name": name})
            continue
        m = _WEEKLY_RE.match(name)
        if m:
            out.append({"kind": "weekly", "asOf": _iso(m.group(2)),
                        "start": _iso(m.group(1)), "end": _iso(m.group(2)), "name": name})
    # 기준일 내림차순 — [0] 이 최신.
    out.sort(key=lambda e: (e["asOf"], e["name"]), reverse=True)
    return out


def _load(entry: dict) -> tuple[dict, str] | None:
    """entry 의 (JSON 본문, 파일 mtime 날짜). mtime 기준 캐시. 실패는 None.

    본문에는 아무것도 주입하지 않는다 — 캐시된 dict 를 그대로 서빙하므로
    호출부가 지우고 붙이면 다음 요청이 오염된다.
    """
    path = os.path.join(PERF_BRIEF_ROOT, entry["name"])
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    mdate = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[path] = (mtime, data, mdate)
    return data, mdate


def _label(entry: dict) -> str:
    if entry["kind"] == "weekly" and entry["start"]:
        return f"위클리 · {_dot(entry['start'])[5:]}~{_dot(entry['end'])[5:]}"
    return f"데일리 · {_dot(entry['asOf'])} 기준"


def _written_on(report: dict, mtime_date: str) -> str:
    """보고서가 스스로 밝힌 작성일(writtenOn). 없으면 파일 mtime 날짜로 대체."""
    w = report.get("writtenOn")
    if isinstance(w, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", w):
        return w
    return mtime_date


def build(today: date | None = None) -> dict:
    """오늘 띄울 성과보고 payload.

    status:
      ready   — 오늘 작성된 해당 종류(월=weekly / 화~금=daily) 보고서가 있음
      pending — 요일상 나와야 하지만 오늘 작성분이 아직 없음 (report=None)
      off     — 주말: 예정된 보고서 없음
    """
    today = today or date.today()
    weekday = today.weekday()  # 0=월
    expected = "weekly" if weekday == 0 else ("daily" if weekday <= 4 else None)

    entries = _scan()
    latest_any = entries[0] if entries else None
    latest_meta = None
    if latest_any:
        loaded = _load(latest_any)
        latest_meta = {
            "kind": latest_any["kind"],
            "asOf": latest_any["asOf"],
            "label": _label(latest_any),
            "writtenOn": _written_on(*loaded) if loaded else None,
        }

    payload = {
        "today": today.isoformat(),
        "weekday": weekday,
        "expected": expected,
        "status": "off" if expected is None else "pending",
        "report": None,
        "latest": latest_meta,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if expected is None:
        return payload

    iso_today = today.isoformat()
    for entry in (e for e in entries if e["kind"] == expected):
        loaded = _load(entry)
        if loaded is None:
            continue
        report, mdate = loaded
        if _written_on(report, mdate) != iso_today:
            # 기준일이 아니라 '작성일'로 판정한다 — 데일리의 기준일은 늘 전영업일
            # 이라 기준일로 오늘을 판정할 수 없다(휴일 보정도 불필요해짐).
            continue
        payload["status"] = "ready"
        payload["report"] = report
        payload["source"] = entry["name"]
        break
    return payload
