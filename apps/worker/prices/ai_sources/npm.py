"""npm 일간 다운로드 — `GET api.npmjs.org/downloads/range/{from}:{to}/{pkg}`. 키 없음.

★드라이브 `npm.py` 규칙:
  · 스코프 패키지는 벌크 조회가 안 된다 → 1개씩, 0.3s 간격.
  · ⚠️스코프 패키지도 경로에 **그대로** 넣는다(URL 인코딩하면 404, 실측).
  · **로스터 전체가 0 인 최근일 = 아직 집계 전** → 그 경계부터 뒤를 잘라낸다.
    개별 패키지의 0 은 진짜 0 이다(자르지 않는다). 실측(2026-09-27): 오늘·어제가 전 패키지 0.
  · 라이브 조회라 매번 창 전체(기본 540일 = 18개월 한도)를 다시 받는다 — 트레일링
    재요청·병합이 저절로 된다.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import httpx

from . import config


def parse_range(payload: dict) -> dict[date, int]:
    """range 응답 → {날짜: 다운로드}. 날짜가 깨진 행은 버린다."""
    out: dict[date, int] = {}
    for row in (payload or {}).get("downloads") or []:
        try:
            day = date.fromisoformat(str(row.get("day")))
        except ValueError:
            continue
        out[day] = int(row.get("downloads") or 0)
    return out


def zero_cutoff(series: dict[str, dict[date, int]]) -> date | None:
    """로스터 **전체**가 0 인 꼬리 날짜들을 걷어낸 뒤의 마지막 날짜.

    최근일부터 거꾸로 보며, 그날 모든 패키지 합이 0 이면 "집계 전"으로 보고 넘긴다.
    한 패키지라도 0 이 아니면 거기가 경계다. 전부 0 이면 None.
    """
    days = sorted({d for s in series.values() for d in s}, reverse=True)
    for day in days:
        if any(s.get(day, 0) for s in series.values()):
            return day
    return None


def apply_cutoff(series: dict[str, dict[date, int]]) -> tuple[dict[str, dict[date, int]], date | None]:
    cutoff = zero_cutoff(series)
    if cutoff is None:
        return {k: {} for k in series}, None
    return {k: {d: v for d, v in s.items() if d <= cutoff} for k, s in series.items()}, cutoff


def fetch_package(client: httpx.Client, package: str, start: date, end: date) -> dict[date, int]:
    response = client.get(f"{config.NPM_RANGE}/{start.isoformat()}:{end.isoformat()}/{package}")
    response.raise_for_status()
    return parse_range(response.json())


def fetch_roster(
    packages: list[tuple[str, str]],
    *,
    days: int = config.NPM_MAX_DAYS,
    today: date | None = None,
    timeout: float = 20.0,
    pacing: float = config.NPM_SCOPED_PACING_SECONDS,
) -> dict:
    """로스터 전체 → {"series": {pkg: {date: n}}, "cutoff": date|None, "failed": [pkg]}.

    ⚠️하나도 못 받으면 RuntimeError — 빈 결과를 "0 다운로드"로 내보내지 않는다.
    """
    end = today or date.today()
    start = end - timedelta(days=min(days, config.NPM_MAX_DAYS) - 1)
    raw: dict[str, dict[date, int]] = {}
    failed: list[str] = []
    with httpx.Client(timeout=timeout, headers={"User-Agent": config.UA}) as client:
        for i, (package, _label) in enumerate(packages):
            if i and package.startswith("@"):
                time.sleep(pacing)
            try:
                got = fetch_package(client, package, start, end)
            except Exception:
                failed.append(package)
                continue
            if got:
                raw[package] = got
            else:
                failed.append(package)
    if not raw:
        raise RuntimeError(f"npm: 패키지 {len(packages)}개 전부 실패")
    series, cutoff = apply_cutoff(raw)
    return {"series": series, "cutoff": cutoff, "failed": failed}
