"""USD/KRW 현재 환율 — 네이버 증권(하나은행 고시 회차) HTTP GET.

★2026-09-25 사용자 지시: 현재 환율은 **네이버 환율**을 쓴다. 세 방식을 실측했다
  (scratchpad/fx_stability.py):
    · 웹 검색 도구   — 탈락. 검색 결과 요약이 3주 전 값(1,373.7, 9/1 기준)을
                       현재처럼 돌려줬다. 실시간 값의 출처가 될 수 없다.
    · 헤드리스 브라우저 — 동작은 한다(m.stock 페이지 본문에서 1,358.70 추출).
                       하지만 한 번에 리소스 88개를 받는다. 값 하나에 너무 무겁다.
    · HTTP GET(JSON) — 채택. 같은 페이지가 쓰는 JSON 을 직접 받는다. 약 60ms.
  ⚠️finance.naver.com/marketindex(HTML)는 이제 stock.naver.com 으로 302 된다.
    옛 HTML 파서 예제를 따라가면 빈 페이지를 긁는다.

★요청 주기에 **무작위**를 섞는다. 캐시 수명을 매번 40~80초 사이에서 새로 뽑고,
  실패하면 지수 백오프(+무작위)로 물러난다. 화면이 몇 개가 떠 있든 상류 호출은
  이 캐시 하나로 묶인다(quote_cache 와 같은 이유).

⚠️실패해도 예외를 올리지 않는다. 마지막으로 받은 값을 `stale=True` 로 돌려주고,
  그것도 없으면 None — 부르는 쪽이 증권사 환율로 물러난다.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

_URLS = (
    # 주 경로. 응답 최상위가 exchangeInfo.
    "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW",
    # 예비 경로. 같은 값이 result 아래에 온다.
    "https://m.stock.naver.com/front-api/marketIndex/productDetail"
    "?category=exchange&reutersCode=FX_USDKRW",
)
_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
)

TTL_RANGE = (40.0, 80.0)  # 성공 뒤 다음 요청까지(초). 매번 새로 뽑는다.
BACKOFF_BASE = 30.0  # 실패 뒤 첫 대기(초). 연속 실패마다 두 배.
BACKOFF_MAX = 600.0
TIMEOUT = 5.0


@dataclass(frozen=True)
class FxRate:
    rate: Decimal
    bank: str | None  # "하나은행"
    round: int | None  # 고시 회차
    traded_at: str | None  # 네이버가 준 고시 시각(ISO, KST)
    fetched_at: datetime
    stale: bool = False


_lock = threading.Lock()
_last: FxRate | None = None
_next_at = 0.0
_failures = 0


def parse(body: dict) -> FxRate | None:
    """두 경로의 응답을 같은 모양으로. 값이 없거나 숫자가 아니면 None."""
    info = body.get("exchangeInfo") or body.get("result") or {}
    raw = info.get("closePrice")
    if not raw:
        return None
    try:
        rate = Decimal(str(raw).replace(",", ""))
    except InvalidOperation:
        return None
    if rate <= 0:
        return None
    bank = (info.get("stockExchangeType") or {}).get("nameKor")
    return FxRate(
        rate=rate,
        bank=bank,
        round=info.get("degreeCount"),
        traded_at=info.get("localTradedAt"),
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch() -> FxRate | None:
    for i, url in enumerate(_URLS):
        if i:
            # 예비 경로로 넘어갈 때도 바로 연달아 치지 않는다.
            time.sleep(random.uniform(0.3, 1.2))
        try:
            response = httpx.get(
                url,
                timeout=TIMEOUT,
                headers={
                    "User-Agent": random.choice(_USER_AGENTS),
                    "Accept": "application/json",
                    "Referer": "https://m.stock.naver.com/",
                },
            )
            response.raise_for_status()
            parsed = parse(response.json())
        except (httpx.HTTPError, ValueError):
            continue
        if parsed is not None:
            return parsed
    return None


def get_usdkrw() -> FxRate | None:
    """캐시된 USD/KRW. 만료됐으면 네이버에서 다시 받는다."""
    global _last, _next_at, _failures
    with _lock:
        now = time.monotonic()
        if now < _next_at:
            return _last
        fresh = _fetch()
        if fresh is not None:
            _last = fresh
            _failures = 0
            _next_at = now + random.uniform(*TTL_RANGE)
            return _last
        _failures += 1
        wait = min(BACKOFF_BASE * 2 ** (_failures - 1), BACKOFF_MAX)
        _next_at = now + wait * random.uniform(0.8, 1.2)
        if _last is not None:
            _last = replace(_last, stale=True)
        return _last
