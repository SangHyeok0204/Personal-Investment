"""[성과보고] S: 에서 만든 성과보고 HTML 리더 (2026-07-30).

`S:\\GE\\raw\\오퍼레이션\\성과분석\\운용 펀드 성과 분석 자동화` 를 read-only 로 마운트한
컨테이너 경로(`/srv/legacy/perf_analysis`)에서, S: 쪽 bat 이 만든 **자체완결 HTML** 을
찾아 목록과 원문을 준다. 대시보드는 회의 탭과 같은 방식으로 iframe(srcDoc) 렌더한다.

파일명 규약 (report-html.ts 의 다운로드 규칙과 동일):
    데일리_성과보고_YYYYMMDD.html          — YYYYMMDD = 기준일
    위클리_성과보고_YYYYMMDD_MMDD.html     — 시작일(8) _ 종료일(MMDD)

**판정 기준**: HTML 은 안을 파싱하지 않으므로 기준일은 **파일명**, 작성일은 **파일
mtime** 으로 본다. perf_brief 의 writtenOn 게이팅과 목적이 같다 — 어제 보고서를 오늘
것으로 오인하는 사고를 막는 게 전부라, 오늘 만든 파일이 없으면 status="pending" 이고
`current` 는 비운다(목록 `items` 는 과거분 조회용이라 그대로 준다).
요일 규칙(월=위클리 / 화~금=데일리 / 주말=off)도 perf_brief 와 같다.

스캔 범위는 마운트 루트와 그 바로 아래 `output/` 두 곳뿐이다 — 프로젝트 폴더에는
`.venv` 처럼 항목이 수만 개인 하위 트리가 있어 재귀 스캔은 SMB 왕복 비용을 감당할 수
없다(회의 탭에서 항목당 stat 이 api 예산을 넘겼던 전례).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime

PERF_REPORT_ROOT = os.environ.get("PERF_REPORT_DIR", "/srv/legacy/perf_analysis")

# 루트 기준 스캔 대상 폴더. "" = 마운트 루트.
_SCAN_DIRS = ("", "output")

_DAILY_RE = re.compile(r"^데일리_성과보고_(\d{8})\.html$")
_WEEKLY_RE = re.compile(r"^위클리_성과보고_(\d{8})_(\d{4})\.html$")


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _dot(iso: str) -> str:
    return iso.replace("-", ".")


def _safe_abs(rel: str | None) -> str | None:
    """루트 기준 상대경로 rel 의 절대경로. 루트 밖(traversal)이면 None."""
    root = os.path.realpath(PERF_REPORT_ROOT)
    target = os.path.realpath(os.path.join(root, rel or ""))
    if target == root or target.startswith(root + os.sep):
        return target
    return None


def _classify(name: str) -> dict | None:
    """파일명 → {kind, asOf, start, end}. 규약에 안 맞으면 None."""
    m = _DAILY_RE.match(name)
    if m:
        d = _iso(m.group(1))
        return {"kind": "daily", "asOf": d, "start": None, "end": d}
    m = _WEEKLY_RE.match(name)
    if m:
        start = _iso(m.group(1))
        end = f"{m.group(1)[0:4]}-{m.group(2)[0:2]}-{m.group(2)[2:4]}"
        return {"kind": "weekly", "asOf": end, "start": start, "end": end}
    return None


def _label(e: dict) -> str:
    if e["kind"] == "weekly" and e["start"]:
        return f"위클리 · {_dot(e['start'])[5:]}~{_dot(e['end'])[5:]}"
    return f"데일리 · {_dot(e['asOf'])} 기준"


def _scan() -> list[dict]:
    """성과보고 HTML 목록. 기준일 내림차순(같으면 작성일 최신순)으로 [0] 이 최신.

    mtime 은 항목당 stat 이라 SMB 왕복이 붙지만, 대상이 파일명 규약을 통과한 보고서
    몇 개뿐이라 회의 탭(수백 항목)과 달리 예산 안에 든다. 작성일 판정에 반드시 필요.
    """
    out: list[dict] = []
    for sub in _SCAN_DIRS:
        base = _safe_abs(sub)
        if not base or not os.path.isdir(base):
            continue
        try:
            with os.scandir(base) as it:
                names = [de.name for de in it if not de.name.startswith(".")]
        except OSError:
            continue
        for name in names:
            meta = _classify(name)
            if meta is None:
                continue
            rel = f"{sub}/{name}" if sub else name
            try:
                mtime = os.path.getmtime(os.path.join(base, name))
            except OSError:
                continue
            out.append({
                **meta,
                "rel": rel,
                "name": name,
                "writtenOn": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
                "savedAt": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                "label": _label(meta),
            })
    out.sort(key=lambda e: (e["asOf"], e["writtenOn"], e["rel"]), reverse=True)
    return out


def build(today: date | None = None) -> dict:
    """오늘 띄울 성과보고 HTML 메타 + 전체 목록.

    status:
      ready   — 오늘 만들어진 해당 종류(월=weekly / 화~금=daily) HTML 이 있음
      pending — 요일상 나와야 하지만 오늘 만든 파일이 아직 없음 (current=None)
      off     — 주말: 예정된 보고서 없음
    """
    today = today or date.today()
    weekday = today.weekday()  # 0=월
    expected = "weekly" if weekday == 0 else ("daily" if weekday <= 4 else None)

    items = _scan()
    iso_today = today.isoformat()
    current = None
    if expected is not None:
        for e in items:
            if e["kind"] == expected and e["writtenOn"] == iso_today:
                current = e
                break

    return {
        "today": iso_today,
        "weekday": weekday,
        "expected": expected,
        "status": "off" if expected is None else ("ready" if current else "pending"),
        "current": current,
        "latest": items[0] if items else None,
        "items": items,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def read_html(rel: str) -> str | None:
    """보고서 HTML 원문. 루트 밖이거나 파일명 규약에 안 맞으면 None.

    캐시하지 않는다 — S: 의 bat 이 같은 파일을 덮어쓰므로 매 호출이 디스크 재읽기여야
    '갱신'이 실제 최신본을 가져온다(회의 탭과 같은 정책).
    """
    target = _safe_abs(rel)
    if not target or not os.path.isfile(target):
        return None
    if _classify(os.path.basename(target)) is None:
        return None
    try:
        with open(target, encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return None
