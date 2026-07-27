"""[회의] 회의자료 파일 탐색기 리더 — PoC (2026-07-24).

S 공용 드라이브 `S:\\GE\\_Team\\07_회의자료` 를 read-only 로 마운트한 컨테이너 경로
(`/srv/legacy/meeting`)를 루트로, 폴더 트리를 탐색하고 임의의 HTML 파일을 골라 원문을
반환한다. 경로는 마운트 루트 밖으로 나갈 수 없도록 realpath 로 검증한다(traversal 방어).

회의 통합 HTML 은 외부 스크립트/이미지 없는 자체완결 문서라 대시보드에서 iframe(srcDoc)
으로 바로 렌더 가능. 가능성 검증용 최소 구현.
"""
from __future__ import annotations

import os

MEETING_ROOT = os.environ.get("MEETING_DIR", "/srv/legacy/meeting")
_HTML_EXT = (".html", ".htm")


def _safe_abs(rel: str | None) -> str | None:
    """루트 기준 상대경로 rel 의 절대경로. 루트 밖(traversal)이면 None."""
    root = os.path.realpath(MEETING_ROOT)
    target = os.path.realpath(os.path.join(root, rel or ""))
    if target == root or target.startswith(root + os.sep):
        return target
    return None


def list_dir(rel: str = "") -> dict | None:
    """폴더 rel 의 하위 항목(폴더 + HTML 파일)을 반환. 없거나 불량이면 None.

    반환: {path, parent, entries:[{name, type:'dir'|'html', rel}]}
    폴더는 이름 내림차순(최신 연월/일 우선), HTML 은 이름 오름차순(00. 통합본 우선).
    성능: SMB stat 왕복 최소화 위해 os.scandir(is_dir 캐시)만 쓰고 파일크기는 조회하지
    않는다 — 파일 많은 폴더에서 api 2초 예산을 넘기던 원인(항목당 getsize)을 제거.
    """
    base = _safe_abs(rel)
    if not base or not os.path.isdir(base):
        return None
    root = os.path.realpath(MEETING_ROOT)
    dirs: list[dict] = []
    files: list[dict] = []
    try:
        with os.scandir(base) as it:
            for de in it:
                if de.name.startswith("."):
                    continue
                full = os.path.join(base, de.name)
                r = "" if full == root else os.path.relpath(full, root)
                try:
                    is_dir = de.is_dir()
                except OSError:
                    continue
                if is_dir:
                    dirs.append({"name": de.name, "type": "dir", "rel": r})
                elif de.name.lower().endswith(_HTML_EXT):
                    files.append({"name": de.name, "type": "html", "rel": r})
    except OSError:
        return None
    dirs.sort(key=lambda e: e["name"], reverse=True)
    files.sort(key=lambda e: e["name"])
    cur = "" if base == root else os.path.relpath(base, root)
    parent = "" if cur == "" else os.path.dirname(cur)
    return {"path": cur, "parent": parent, "entries": dirs + files}


def read_file(rel: str) -> str | None:
    """HTML 파일 rel 의 원문. 루트 밖이거나 .html/.htm 아니면 None."""
    target = _safe_abs(rel)
    if not target or not os.path.isfile(target):
        return None
    if not target.lower().endswith(_HTML_EXT):
        return None
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None
