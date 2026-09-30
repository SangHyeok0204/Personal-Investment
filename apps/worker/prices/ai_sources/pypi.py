"""PyPI 최근 다운로드 — `GET pypistats.org/api/packages/{pkg}/recent`. 키 없음.

★드라이브 `pypi.py` 규칙:
  · last_day / last_week / last_month 를 **스냅샷**으로 적는다(pypistats 는 과거 일별을
    180일만 준다 — 장기 이력은 스냅샷을 쌓아야 남는다).
  · 패키지 사이 3s 간격. 429 는 3회까지 기다렸다 재시도, 그래도 429 면 그 패키지만 SKIP
    — 고장이 아니라 레이트리밋이다.
  · 전부 SKIP/실패면 예외(빈 스냅샷을 적지 않는다).
"""
from __future__ import annotations

import time

import httpx

from . import config


def parse(payload: dict) -> dict | None:
    data = (payload or {}).get("data") or {}
    if data.get("last_day") is None:
        return None
    return {
        "last_day": int(data["last_day"]),
        "last_week": int(data["last_week"]) if data.get("last_week") is not None else None,
        "last_month": int(data["last_month"]) if data.get("last_month") is not None else None,
    }


def fetch(
    packages: list[str] | None = None,
    *,
    timeout: float = 20.0,
    pacing: float = config.PYPI_PACING_SECONDS,
    sleep=time.sleep,
) -> dict:
    """→ {"rows": {pkg: {last_day, last_week, last_month}}, "skipped": [pkg], "failed": [pkg]}."""
    packages = packages or [p for p, _ in config.PYPI_PACKAGES]
    rows: dict[str, dict] = {}
    skipped: list[str] = []
    failed: list[str] = []
    with httpx.Client(timeout=timeout, headers={"User-Agent": config.UA}) as client:
        for i, package in enumerate(packages):
            if i:
                sleep(pacing)
            for attempt in range(config.PYPI_MAX_429 + 1):
                try:
                    response = client.get(config.PYPI_RECENT.format(package=package))
                except Exception:
                    failed.append(package)
                    break
                if response.status_code == 429:
                    if attempt >= config.PYPI_MAX_429:
                        skipped.append(package)
                        break
                    sleep(pacing * (attempt + 1))
                    continue
                parsed = parse(response.json()) if response.status_code == 200 else None
                if parsed is None:
                    failed.append(package)
                else:
                    rows[package] = parsed
                break
    if not rows:
        raise RuntimeError(f"pypi: 전부 실패(skipped={skipped}, failed={failed})")
    return {"rows": rows, "skipped": skipped, "failed": failed}
