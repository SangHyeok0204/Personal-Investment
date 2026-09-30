"""VS Code 확장 누적 설치수 — `POST marketplace.visualstudio.com/_apis/public/gallery/extensionquery`.

★드라이브 `vscode.py` 규칙:
  · filterType 7(= publisher.extensionName), flags 914, api-version 7.2-preview.1.
  · 마켓은 **현재 누적치만** 준다 → 일 1회 스냅샷이 하한이다(놓친 날은 복구 불가).
  · install / updateCount / downloadCount / version / rating 을 그대로 적는다.
  · **음수 델타도 원값 그대로** — 마켓이 집계를 고치면 누적이 줄 수 있다. 여기서 clip 하지 않는다.
  · 로스터 중 하나도 안 오면 실패(빈 스냅샷을 적지 않는다).
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from . import config


def build_query(ids: list[str]) -> dict:
    return {
        "filters": [
            {
                "criteria": [{"filterType": 7, "value": ext_id} for ext_id in ids],
                "pageNumber": 1,
                "pageSize": max(len(ids), 1),
            }
        ],
        "flags": config.VSCODE_FLAGS,
    }


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse(payload: dict, snapshot_utc: datetime | None = None) -> list[dict]:
    """→ [{extension, install, update_count, download_count, version, last_updated, avg_rating, rating_count, snapshot_utc}]."""
    snapshot_utc = snapshot_utc or datetime.now(timezone.utc)
    out: list[dict] = []
    for result in (payload or {}).get("results") or []:
        for ext in result.get("extensions") or []:
            publisher = ((ext.get("publisher") or {}).get("publisherName") or "").strip()
            name = (ext.get("extensionName") or "").strip()
            if not publisher or not name:
                continue
            stats = {s.get("statisticName"): s.get("value") for s in ext.get("statistics") or []}
            if stats.get("install") is None:
                continue
            versions = ext.get("versions") or [{}]
            out.append(
                {
                    "extension": f"{publisher}.{name}",
                    "install": int(float(stats["install"])),
                    "update_count": _num(stats.get("updateCount")),
                    "download_count": _num(stats.get("downloadCount")),
                    "version": versions[0].get("version"),
                    "last_updated": ext.get("lastUpdated") or versions[0].get("lastUpdated"),
                    "avg_rating": _num(stats.get("averagerating")),
                    "rating_count": _num(stats.get("ratingcount")),
                    "snapshot_utc": snapshot_utc.isoformat(),
                }
            )
    return out


def canonical(rows: list[dict], ids: list[str]) -> list[dict]:
    """마켓이 돌려준 대소문자와 상관없이 로스터 표기(`GitHub.copilot-chat`)로 맞춘다."""
    by_lower = {i.lower(): i for i in ids}
    for row in rows:
        row["extension"] = by_lower.get(row["extension"].lower(), row["extension"])
    return rows


def fetch(ids: list[str] | None = None, *, timeout: float = 30.0) -> list[dict]:
    ids = ids or [ext_id for ext_id, _ in config.VSCODE_EXTENSIONS]
    response = httpx.post(
        config.VSCODE_QUERY,
        json=build_query(ids),
        headers={
            "Accept": f"application/json;api-version={config.VSCODE_API_VERSION}",
            "Content-Type": "application/json",
            "User-Agent": config.UA,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    rows = canonical(parse(response.json()), ids)
    if not rows:
        raise RuntimeError("vscode: 빈 응답")
    return rows
