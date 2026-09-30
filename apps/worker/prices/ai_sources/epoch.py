"""Epoch AI 데이터셋 zip — `epoch.ai/data/{ai_companies,ai_chip_sales,data_centers/data_centers}.zip`.

★드라이브 `epoch.py` 규칙:
  · **ETag If-None-Match** — 304 면 받지 않는다(단 캐시가 비어 있으면 호출 쪽이 etag 없이 다시 받는다).
  · zip 은 **메모리에서** 푼다. 멤버 CSV 6개만 읽는다(config.EPOCH_DATASETS).
  · ⚠️`newline=""` 필수 — Notes 열에 줄바꿈이 든 따옴표 셀이 흔하다(실측). 안 주면 행이 쪼개진다.
  · **전량 스냅샷 교체**(병합 금지 — 원본에서 지워진 행이 유령으로 남는다).
  · 행수가 이전의 50% 미만으로 줄면 실패로 본다(잘린 파일 방어).
  · CC-BY 4.0 — 출처 표기 필수(config.EPOCH_ATTRIBUTION).

아래 집계 함수는 화면용 요약이다(모든 열을 싣지 않는다).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date

import httpx

from . import config

_TAG = re.compile(r"\s*#\w+")


def fetch_zip(url: str, etag: str | None = None, *, timeout: float = 60.0) -> dict:
    """→ {"status": 200|304, "content": bytes|None, "etag": str|None}."""
    headers = {"User-Agent": config.UA}
    if etag:
        headers["If-None-Match"] = etag
    response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    if response.status_code == 304:
        return {"status": 304, "content": None, "etag": etag}
    response.raise_for_status()
    return {"status": 200, "content": response.content, "etag": response.headers.get("etag")}


def extract_members(content: bytes, members: tuple[str, ...] | list[str]) -> dict[str, list[dict]]:
    """zip 바이트 → {멤버: [행 dict]}. 멤버가 없거나 비면 ValueError."""
    out: dict[str, list[dict]] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = {n.rsplit("/", 1)[-1]: n for n in zf.namelist()}
        for member in members:
            if member not in names:
                raise ValueError(f"epoch: zip 에 {member} 없음")
            with zf.open(names[member]) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
                rows = list(csv.DictReader(text))
            if not rows:
                raise ValueError(f"epoch: {member} 가 비었음")
            out[member] = rows
    return out


def shrunk(old: dict[str, int], new: dict[str, int], floor: float = config.EPOCH_SHRINK_FLOOR) -> list[str]:
    """이전 행수 대비 floor 미만으로 줄어든 멤버."""
    return [m for m, n in new.items() if old.get(m) and n < old[m] * floor]


# ── 집계(화면용 요약) ────────────────────────────────────────────────────────

def _f(value) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _d(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _clean(value) -> str | None:
    text = _TAG.sub("", str(value or "")).strip()
    return text or None


def chip_h100e_cumulative(rows: list[dict]) -> dict:
    """timelines_by_chip → 분기별 출하 H100e(중앙값)를 제조사별로 합산, **누적**.

    분기에 보고가 없는 제조사는 그 분기 출하 0 으로 본다(누적이 끊기지 않게).
    → {"quarters": [date], "by_maker": {maker: [누적]}, "total": [누적], "incomplete": [date]}.
    """
    per: dict[str, dict[date, float]] = {}
    incomplete: set[date] = set()
    for row in rows:
        start = _d(row.get("Start date"))
        value = _f(row.get("Compute estimate in H100e (median)"))
        maker = (row.get("Chip manufacturer") or "").strip() or "기타"
        if start is None or value is None:
            continue
        quarter = date(start.year, (start.month - 1) // 3 * 3 + 1, 1)
        per.setdefault(maker, {})
        per[maker][quarter] = per[maker].get(quarter, 0.0) + value
        if str(row.get("Incomplete") or "").strip().lower() == "true":
            incomplete.add(quarter)
    quarters = sorted({q for m in per.values() for q in m})
    by_maker: dict[str, list[float]] = {}
    for maker, values in per.items():
        run = 0.0
        acc = []
        for q in quarters:
            run += values.get(q, 0.0)
            acc.append(run)
        by_maker[maker] = acc
    total = [sum(v[i] for v in by_maker.values()) for i in range(len(quarters))]
    return {"quarters": quarters, "by_maker": by_maker, "total": total, "incomplete": sorted(incomplete)}


def top_data_centers(rows: list[dict], n: int = 20) -> list[dict]:
    """data_centers → 현재 전력(MW) 상위 n."""
    out = []
    for row in rows:
        power = _f(row.get("Current power (MW)"))
        if power is None:
            continue
        out.append(
            {
                "name": (row.get("Name") or "").strip(),
                "owner": _clean(row.get("Owner")),
                "users": _clean(row.get("Users")),
                "country": _clean(row.get("Country")),
                "power_mw": power,
                "h100e": _f(row.get("Current H100 equivalents")),
                "capex_busd": _f(row.get("Current total capital cost (2025 USD billions)")),
            }
        )
    out.sort(key=lambda r: -r["power_mw"])
    return out[:n]


def lab_revenue_steps(rows: list[dict]) -> dict[str, list[tuple[date, float]]]:
    """revenue_reports → 회사별 연환산 매출(ARR) 계단. 회사 전체(Full company)만."""
    out: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        if (row.get("Scope") or "").strip() not in ("", "Full company"):
            continue
        day = _d(row.get("Date"))
        value = _f(row.get("Annualized revenue (USD)"))
        company = (row.get("Company") or "").strip()
        if day is None or value is None or not company:
            continue
        out.setdefault(company, []).append((day, value))
    for points in out.values():
        points.sort()
    return out


def funding_rounds(rows: list[dict], limit: int = 50) -> list[dict]:
    """funding_rounds → 최근 순. 마감일이 없으면 보도일로."""
    out = []
    for row in rows:
        day = _d(row.get("Close date")) or _d(row.get("Report date"))
        out.append(
            {
                "company": (row.get("Company") or "").strip(),
                "date": day.isoformat() if day else None,
                "status": (row.get("Status") or "").strip() or None,
                "equity_usd": _f(row.get("Funding (equity)")),
                "debt_usd": _f(row.get("Funding (debt)")),
                "valuation_usd": _f(row.get("Valuation (post-money)")),
                "type": (row.get("Type") or "").strip() or None,
            }
        )
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out[:limit]
