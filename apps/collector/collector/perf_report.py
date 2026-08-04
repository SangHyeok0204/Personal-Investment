"""[성과보고] S: 에서 만든 성과분석 HTML 리더 (2026-08-03 개편).

`S:\\GE\\raw\\오퍼레이션\\성과분석\\운용 펀드 성과 분석 자동화` 를 read-only 로 마운트한
컨테이너 경로(`/srv/legacy/perf_analysis`)에서 **자체완결 HTML** 을 찾아 목록과 원문을
준다. 대시보드는 회의 탭과 같은 방식으로 iframe(srcDoc) 렌더한다.

━━ 파일명이 곧 계약 ━━
현행 (단일PORT_분석.bat · 비교PORT_분석.bat 산출물)
    {펀드}_단일보고서_{일간|주간|월간}_{YYYYMMDD}.html
    {펀드1}_{펀드2}_비교보고서_{일간|주간|월간}_{YYYYMMDD}.html
레거시 (은퇴한 파이프라인 산출물. 지난 보고서가 목록에서 사라지지 않게 계속 읽는다)
    데일리_성과보고_{YYYYMMDD}.html
    위클리_성과보고_{YYYYMMDD}_{MMDD}.html
    월간_성과보고_{YYYYMM}.html

기준일은 **파일명**, 작성일은 **파일 mtime** 으로 본다. HTML 안을 파싱하지 않는다.

━━ 2026-08-03 변경: 요일 기대치를 버렸다 ━━
예전에는 월=위클리 / 화~금=데일리 스케줄을 가정하고, 오늘 만든 파일이 없으면 pending 이라
아무것도 보여 주지 않았다. 지금은 운용역이 필요할 때 bat 을 돌리는 주문형이라 그 가정이
성립하지 않는다. 그래서 **가장 최근 보고서를 늘 보여 주고**, 오늘 만든 것이 아니면
작성일 배지로 알린다. 낡은 값을 오늘 것으로 오인하는 사고는 배지가 막는다.

━━ 어디를 훑는가 (2026-08-04) ━━
산출물은 `output/{생성일 YYYYMMDD}/` 로 들어간다. 그래서 마운트 루트 · `output/` ·
`output/` 아래 **날짜 폴더**들을 훑는다. 날짜 폴더는 최신 순으로 잘라 왕복 횟수를 묶어
둔다. 재귀 스캔은 하지 않는다. 프로젝트 폴더에는 항목이 수만 개인 하위 트리(.venv 등)가
있을 수 있어 SMB 왕복 비용을 감당할 수 없다.

루트와 `output/` 을 계속 보는 것은 날짜 폴더 규칙 이전에 만든 보고서가 목록에서
사라지지 않게 하기 위해서다.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta

PERF_REPORT_ROOT = os.environ.get("PERF_REPORT_DIR", "/srv/legacy/perf_analysis")

# 고정 스캔 대상. "" = 마운트 루트.
# 2026-08-04 부터 산출물은 `output/{생성일 YYYYMMDD}/` 로 들어간다. 그 날짜 폴더들도
# 함께 훑는다(아래 _scan_dirs). 루트와 output 을 남겨 둔 것은 그 전에 만든 보고서가
# 목록에서 사라지지 않게 하기 위해서다.
_FIXED_DIRS = ("", "output")

# 날짜 폴더는 하루에 하나씩 늘어난다. SMB 왕복이 폴더 수에 비례하므로 최근 것만 본다.
_DAY_DIR_RE = re.compile(r"^\d{8}$")
_MAX_DAY_DIRS = 40

_PERIODS = "일간|주간|월간"
_SINGLE_RE = re.compile(rf"^(?P<who>.+?)_단일보고서_(?P<kind>{_PERIODS})_(?P<d>\d{{8}})\.html$")
_COMPARE_RE = re.compile(rf"^(?P<who>.+?)_비교보고서_(?P<kind>{_PERIODS})_(?P<d>\d{{8}})\.html$")
# ── 레거시 ──
_DAILY_RE = re.compile(r"^데일리_성과보고_(\d{8})\.html$")
_WEEKLY_RE = re.compile(r"^위클리_성과보고_(\d{8})_(\d{4})\.html$")
_MONTHLY_RE = re.compile(r"^월간_성과보고_(\d{6})\.html$")


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _dot(iso: str) -> str:
    return iso.replace("-", ".")


def _month_end(yyyymm: str) -> str:
    """YYYYMM → 그 달 말일 ISO. 레거시 월간 보고서의 기준일 대용."""
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def _safe_abs(rel: str | None) -> str | None:
    """루트 기준 상대경로 rel 의 절대경로. 루트 밖(traversal)이면 None."""
    root = os.path.realpath(PERF_REPORT_ROOT)
    target = os.path.realpath(os.path.join(root, rel or ""))
    if target == root or target.startswith(root + os.sep):
        return target
    return None


def _classify(name: str) -> dict | None:
    """파일명 → {kind, scope, asOf, label}. 규약에 안 맞으면 None."""
    m = _SINGLE_RE.match(name)
    if m:
        d = _iso(m.group("d"))
        who = m.group("who")
        return {"kind": "single", "scope": m.group("kind"), "who": who, "asOf": d,
                "label": f'단일 · {who} · {m.group("kind")} · {_dot(d)} 기준'}
    m = _COMPARE_RE.match(name)
    if m:
        d = _iso(m.group("d"))
        who = m.group("who").replace("_", " vs ")
        return {"kind": "compare", "scope": m.group("kind"), "who": who, "asOf": d,
                "label": f'비교 · {who} · {m.group("kind")} · {_dot(d)} 기준'}

    m = _DAILY_RE.match(name)
    if m:
        d = _iso(m.group(1))
        return {"kind": "legacy", "scope": "데일리", "who": "운용자산", "asOf": d,
                "label": f"데일리 · {_dot(d)} 기준"}
    m = _WEEKLY_RE.match(name)
    if m:
        s = _iso(m.group(1))
        e = f"{m.group(1)[0:4]}-{m.group(2)[0:2]}-{m.group(2)[2:4]}"
        return {"kind": "legacy", "scope": "위클리", "who": "운용자산", "asOf": e,
                "label": f"위클리 · {_dot(s)[5:]}~{_dot(e)[5:]}"}
    m = _MONTHLY_RE.match(name)
    if m:
        ym = m.group(1)
        return {"kind": "legacy", "scope": "월간", "who": "운용자산",
                "asOf": _month_end(ym),
                "label": f"월간 · {ym[:4]}.{ym[4:]}"}
    return None


def _scan_dirs() -> list[str]:
    """훑을 폴더 목록. 고정 두 곳 + `output/` 아래 날짜 폴더(최근 순).

    날짜 폴더를 최신부터 자르므로, 폴더가 아무리 쌓여도 왕복 횟수가 일정하다.
    """
    dirs = list(_FIXED_DIRS)
    base = _safe_abs("output")
    if base and os.path.isdir(base):
        try:
            with os.scandir(base) as it:
                days = sorted((e.name for e in it
                               if e.is_dir() and _DAY_DIR_RE.match(e.name)),
                              reverse=True)
        except OSError:
            days = []
        dirs += [f"output/{d}" for d in days[:_MAX_DAY_DIRS]]
    return dirs


def _scan() -> list[dict]:
    """성과보고 HTML 목록. 기준일 내림차순(같으면 작성일 최신순)으로 [0] 이 최신.

    mtime 은 항목당 stat 이라 SMB 왕복이 붙지만, 대상이 파일명 규약을 통과한 보고서
    몇 개뿐이라 예산 안에 든다. 작성일 판정에 반드시 필요하다.
    """
    out: list[dict] = []
    for sub in _scan_dirs():
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
            })
    # 2차 정렬은 savedAt(분까지)이라야 한다. writtenOn(날짜)으로 자르면 같은 날 만든
    # 보고서끼리 파일명 순으로 밀려서, 방금 만든 것이 아침 것보다 뒤로 간다.
    out.sort(key=lambda e: (e["asOf"], e["savedAt"], e["rel"]), reverse=True)
    return out


def build(today: date | None = None) -> dict:
    """가장 최근 보고서 + 전체 목록.

    status:
      ready  — 보여 줄 보고서가 있음 (오늘 것인지는 writtenOn 으로 판단)
      empty  — 아직 만들어진 보고서가 없음
    """
    today = today or date.today()
    items = _scan()
    current = items[0] if items else None
    return {
        "today": today.isoformat(),
        "status": "ready" if current else "empty",
        "current": current,
        "latest": current,
        "items": items,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def read_html(rel: str) -> str | None:
    """보고서 HTML 원문. 루트 밖이거나 파일명 규약에 안 맞으면 None.

    캐시하지 않는다. S: 의 bat 이 같은 파일을 덮어쓸 수 있으므로 매 호출이 디스크
    재읽기여야 '갱신' 이 실제 최신본을 가져온다(회의 탭과 같은 정책).
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
