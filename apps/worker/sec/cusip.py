"""CUSIP → 티커 해소 — 기존 `cusip_map` → **OpenFIGI** → SEC 회사명 정확 일치 (계획 A4).

원본 `13F기관내부자/src/resolver.py` 의 `CusipResolver` 는 ① 수동 CSV ② SEC `company_tickers`
회사명 정규화 **정확·유일** 일치만 썼다 — 거장 최근 분기 금액의 68.8%만 티커가 붙었다(실측).
BAC·무디스·GE 같은 대형주가 빠진 건 13F 의 발행사명("BANK AMER CORP")이 SEC 회사명과 달라서다.
OpenFIGI 는 CUSIP 으로 직접 찾으므로 이름 차이와 무관하다.

- 우선순위: manual > openfigi > exact > none. 이미 붙은 티커(manual·exact)는 건드리지 않는다.
- OpenFIGI 무키: **분당 25요청 · 요청당 10건**(응답 헤더 `ratelimit-limit: 25` 실측). 429 면 1분 쉰다.
- 첫 글자가 영문인 코드는 CINS 로 묻는다. 소문자로 적힌 CUSIP(실측 '48251w104')은 대문자로.
- 결과 고르기: 미국 통합 상장(`exchCode='US'`)을 먼저, 없으면 첫 결과. 티커의 `/`(BRK/B)는
  SEC·대시보드 표기(BRK-B)로 바꾼다.
- ★"찾아봤지만 없음"은 `figi = ''` 로 남긴다(NULL = 아직 안 찾아봄). 안 그러면 매 회차 같은
  CUSIP 을 다시 묻는다. 퍼지 이름 매칭은 하지 않는다(오연결 방지 — 원본 원칙 유지).
"""
from __future__ import annotations

import re
import time
from collections import Counter

import httpx

from sec.client import RateLimiter

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
BATCH = 10
_figi_limiter = RateLimiter(25 / 60)

_SUFFIX = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LLC", "LP",
    "LTD", "LIMITED", "PLC", "THE", "COM", "HLDG", "HLDGS", "HOLDING", "HOLDINGS",
    "GROUP", "GRP", "CL", "CLASS", "A", "B", "C", "SA", "NV", "AG", "ADR", "ADS",
    "NEW", "DEL", "TR", "TRUST", "FUND", "ETF",
}


def norm_name(name: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper())
    return " ".join(t for t in s.split() if t not in _SUFFIX)


def unique_name_map(company_tickers: dict) -> dict[str, str]:
    """정규화 회사명 → 티커. 정규화 후 여러 티커로 겹치는 이름은 버린다(원본 규칙)."""
    counts: Counter[str] = Counter()
    first: dict[str, str] = {}
    for v in company_tickers.values():
        tk = (v.get("ticker") or "").strip().upper()
        n = norm_name(v.get("title") or "")
        if not tk or not n:
            continue
        first.setdefault(n, tk)
        counts[n] += 1
    return {n: tk for n, tk in first.items() if counts[n] == 1}


def pick_figi(entry: dict) -> dict | None:
    """OpenFIGI 응답 한 칸 → {ticker, name, figi} 또는 None."""
    data = entry.get("data") or []
    if not data:
        return None
    best = next((d for d in data if d.get("exchCode") == "US"), data[0])
    ticker = (best.get("ticker") or "").strip().upper().replace("/", "-")
    if not ticker:
        return None
    return {"ticker": ticker, "name": best.get("name"),
            "figi": best.get("compositeFIGI") or best.get("figi") or ""}


def id_type(cusip: str) -> str:
    """첫 글자가 영문이면 CINS(미국 밖 발행사 — N=네덜란드, G=영국령 …). ID_CUSIP 으로 물으면 못 찾는다
    (실측: ASML N07059210 · 네비우스 N97284108 · 시게이트 G7997R103)."""
    return "ID_CINS" if cusip[:1].isalpha() else "ID_CUSIP"


def openfigi_lookup(client: httpx.Client, cusips: list[str], *, limiter: RateLimiter | None = None,
                    sleep=time.sleep, retries: int = 3) -> list[dict | None]:
    """CUSIP 최대 10개 → 같은 순서의 결과(없으면 None)."""
    assert len(cusips) <= BATCH
    body = [{"idType": id_type(c), "idValue": c.upper()} for c in cusips]
    limiter = limiter or _figi_limiter
    for attempt in range(retries + 1):
        limiter.acquire()
        try:
            resp = client.post(OPENFIGI_URL, json=body)
        except httpx.TransportError:
            # 실측: 맥이 잠든 사이 요청이 멈췄다가 깨며 timeout · "Server disconnected" → 회차 전체가 실패했다.
            if attempt < retries:
                sleep(2 ** attempt)
                continue
            raise
        if resp.status_code == 429 and attempt < retries:
            sleep(60)
            continue
        resp.raise_for_status()
        return [pick_figi(e) for e in resp.json()]
    resp.raise_for_status()
    return []
