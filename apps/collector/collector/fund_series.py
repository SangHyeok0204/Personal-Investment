"""[누적 수익률 비교] S: 에서 만든 펀드 시계열 JSON 리더 (2026-07-31).

`S:\\GE\\raw\\오퍼레이션\\성과분석\\운용 펀드 성과 분석 자동화` 를 read-only 로 마운트한
컨테이너 경로(`/srv/legacy/perf_analysis`) 아래 `funds/` 폴더에서 표준 스키마 JSON 을 읽어
그대로 넘긴다. 대시보드는 여기 담긴 계열만 그린다.

**왜 여기서 엑셀을 안 읽는가**: 엑셀 레이아웃은 펀드마다 다르고 같은 파일 안에서도 다르다
(실제로 한 워크북에서 Port_Bloommberg 는 2행, Port_Sharia 는 4행부터 데이터다). 그 편차는
S: 쪽 `register_funds.py`(claude 가 읽기 명세를 만듦) + `build_funds.py`(명세대로 결정론적
적재)가 흡수한다. collector 는 이미 정규화된 것만 읽으므로 펀드가 몇 개로 늘어나든
이 파일은 그대로다.

파일당 mtime 캐시. 폴더 스캔은 한 단계뿐이라(재귀 없음) SMB 왕복이 파일 수에 비례한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

FUNDS_ROOT = os.environ.get(
    "FUND_SERIES_DIR", "/srv/legacy/perf_analysis/funds"
)

# 계열이 갖춰야 할 최소 조건. 하나라도 어긋나면 그 펀드만 건너뛴다(전체를 죽이지 않는다).
_REQUIRED = ("id", "label", "points")

_cache: dict[str, tuple[float, dict]] = {}   # 파일명 → (mtime, payload)


def _load(path: str) -> dict | None:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED):
        return None
    pts = data.get("points")
    if not isinstance(pts, list) or len(pts) < 2:
        return None
    # 좌표는 [날짜, 값] 쌍만 남긴다. 형식이 어긋난 점은 조용히 버리지 않고 세어서 알린다.
    clean = [p for p in pts
             if isinstance(p, list) and len(p) == 2
             and isinstance(p[0], str) and isinstance(p[1], (int, float))]
    dropped = len(pts) - len(clean)
    if len(clean) < 2:
        return None
    out = {
        "id": str(data["id"]),
        "label": str(data["label"]),
        "inception": data.get("inception") or clean[0][0],
        "lastDate": data.get("lastDate") or clean[-1][0],
        "count": len(clean),
        "points": clean,
        "rebalancing": [d for d in (data.get("rebalancing") or []) if isinstance(d, str)],
        "source": data.get("source"),
        "sourceModified": data.get("sourceModified"),
        "generatedAt": data.get("generatedAt"),
        "qa": list(data.get("qa") or []) + (
            [f"형식이 맞지 않는 점 {dropped}개를 버렸습니다."] if dropped else []
        ),
    }
    _cache[path] = (mtime, out)
    return out


def build() -> dict:
    """등록된 펀드 전체. 인셉션이 이른 순으로 정렬한다(범례 순서 고정)."""
    funds: list[dict] = []
    skipped: list[str] = []
    if os.path.isdir(FUNDS_ROOT):
        try:
            with os.scandir(FUNDS_ROOT) as it:
                names = sorted(e.name for e in it
                               if e.name.endswith(".json") and not e.name.startswith("."))
        except OSError:
            names = []
        for name in names:
            got = _load(os.path.join(FUNDS_ROOT, name))
            if got is None:
                skipped.append(name)
            else:
                funds.append(got)
    funds.sort(key=lambda f: (f["inception"], f["id"]))
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "funds": funds,
        "skipped": skipped,
    }
