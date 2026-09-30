"""Ramp AI Index — `GET ramp.com/data/ai-index` HTML 안의 JSON. 키 없음.

페이지는 Next.js(App Router)라 데이터가 `self.__next_f.push([1,"…"])` **문자열 조각**
안에 따옴표가 이스케이프된 채(`\\"adoptionVendor\\":[…]`) 들어 있다.
  1) push 조각을 모두 JSON 문자열로 풀어 이어 붙이고(조각 경계에 배열이 걸쳐도 이어진다)
  2) 키(`"adoptionOverall":`, `"adoptionVendor":`)를 찾아 그 자리에서 `raw_decode`.
  조각 정규식이 안 맞으면 HTML 전체의 `\\"` 를 풀어 한 번 더 찾는다.

⚠️구조가 바뀌면(키 없음·필드 없음) **예외**를 던진다 — 호출 쪽이 last-good 을 유지한다.
  빈 배열을 "도입률 0"으로 내보내지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import date

import httpx

from . import config

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)
_DECODER = json.JSONDecoder()


def _flight_text(html: str) -> str:
    parts: list[str] = []
    for chunk in _PUSH.findall(html):
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except ValueError:
            continue
    return "".join(parts)


def extract_array(text: str, key: str) -> list | None:
    """`"key":[…]` 의 배열. 없거나 배열이 아니면 None."""
    needle = f'"{key}":'
    idx = text.find(needle)
    while idx != -1:
        start = idx + len(needle)
        while start < len(text) and text[start] in " \t\r\n":
            start += 1
        try:
            value, _ = _DECODER.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, list):
            return value
        idx = text.find(needle, idx + 1)
    return None


def extract(html: str, keys: tuple[str, ...] = ("adoptionOverall", "adoptionVendor")) -> dict[str, list]:
    candidates = [_flight_text(html), html.replace('\\"', '"')]
    out: dict[str, list] = {}
    for key in keys:
        for text in candidates:
            found = extract_array(text, key)
            if found is not None:
                out[key] = found
                break
    return out


def _month(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]).replace(day=1)
    except ValueError:
        return None


def parse(html: str) -> dict:
    """→ {"overall": [(월초, 도입률%)], "vendors": {vendor: [(월초, 도입률%)]}, "latest": date}."""
    arrays = extract(html)
    overall_raw = arrays.get("adoptionOverall")
    vendor_raw = arrays.get("adoptionVendor")
    if not overall_raw or not vendor_raw:
        raise ValueError(f"ramp: 구조 변경 — 찾은 키 {sorted(arrays)}")

    overall: list[tuple[date, float]] = []
    for row in overall_raw:
        day = _month(row.get("date_month"))
        if day is None or row.get("adoption_rate_pct") is None:
            continue
        overall.append((day, float(row["adoption_rate_pct"])))

    vendors: dict[str, list[tuple[date, float]]] = {}
    for row in vendor_raw:
        day = _month(row.get("date_month"))
        vendor = str(row.get("vendor") or "").strip()
        if day is None or not vendor or row.get("adoption_rate_pct") is None:
            continue
        vendors.setdefault(vendor, []).append((day, float(row["adoption_rate_pct"])))

    if not overall or not vendors:
        raise ValueError("ramp: 필드 변경 — date_month/adoption_rate_pct 를 못 읽음")
    overall.sort()
    for points in vendors.values():
        points.sort()
    return {"overall": overall, "vendors": vendors, "latest": overall[-1][0]}


def fetch(*, timeout: float = 30.0) -> dict:
    response = httpx.get(
        config.RAMP_URL,
        headers={"User-Agent": config.UA, "Accept": "text/html"},
        timeout=timeout,
        follow_redirects=True,
    )
    response.raise_for_status()
    return parse(response.text)
