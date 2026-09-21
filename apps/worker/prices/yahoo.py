"""야후 파이낸스 시세 소스 — 인증 없이 미국 상장 종목의 현재가.

★왜 야후를 먼저 붙였나(2026-09-22):
  사용자는 토스로 보유 종목 실시간 가격을 받고 싶어 했는데, 이 계좌는 **해외주식
  전용**이라 보유 17종목이 전부 미국 상장이다. 토스는 자격증명도 IP 허용목록도
  아직 없어서 **지금 검증이 불가능**하다. 야후는 키가 필요 없고 17종목 전부
  실측으로 받아진다(2026-09-22, 17/17 성공).
  `base.py` 에 적힌 DailyPriceAgent 의 원래 순서도 "yahoo 우선, toss 폴백" 이다.
  토스 키가 들어오면 CompositePriceSource 뒤에 붙기만 하면 된다.

⚠️v7 `/finance/quote` 는 쓰지 않는다. 2026-09-22 기준 **401** 이다(crumb/cookie 요구).
  v8 `/finance/chart/{symbol}` 은 인증 없이 동작한다.

⚠️전일종가는 `previousClose` 가 아니라 `chartPreviousClose` 를 쓴다.
  v8 meta 에 `previousClose` 는 **None 으로 온다**. 실측 교차검증:
  price / (1 + regularMarketChangePercent/100) 로 역산한 값과 chartPreviousClose 가
  0.002 이내로 일치한다(SOXL·MSFT·GLD·NVDA). 그래서 chartPreviousClose 가 정본이다.

한 심볼에 한 번씩 호출해야 해서(다건 조회가 없다) **동시에** 던진다. 순차로 하면
17종목에 2.9초가 걸려 5초 폴링에 맞지 않는다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .base import PriceSource, Quote

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

# 야후는 브라우저 UA 가 아니면 종종 거부한다. 실측으로 필요했다.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _dec(value) -> Decimal | None:
    """숫자를 Decimal 로. 실패하면 None — 0 으로 만들지 않는다."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class YahooPriceSource(PriceSource):
    name = "yahoo"
    # 야후는 접미사로 시장을 구분한다(005930.KS 처럼). 접미사 없는 심볼은 미국이다.
    markets = ("US", "NASDAQ", "NYSE", "AMEX", "NYSEArca", "BATS")

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        *,
        timeout: float = 8.0,
        max_workers: int = 8,
    ):
        self._own_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=timeout, headers={"User-Agent": _UA}
        )
        self._max_workers = max_workers

    def close(self):
        if self._own_client:
            self._http.close()

    def _one(self, symbol: str) -> Quote | None:
        try:
            response = self._http.get(
                f"{BASE}/{symbol}", params={"range": "1d", "interval": "1d"}
            )
            if response.status_code != 200:
                return None
            results = (response.json().get("chart") or {}).get("result") or []
            if not results:
                return None
            meta = results[0].get("meta") or {}
        except Exception:
            # ⚠️한 종목이 실패해도 전체를 죽이지 않는다 — 그 종목만 "—" 로 그린다.
            return None

        price = _dec(meta.get("regularMarketPrice"))
        if price is None:
            return None

        traded_at = meta.get("regularMarketTime")
        return Quote(
            symbol=symbol,
            price=price,
            currency=meta.get("currency") or "USD",
            # ⚠️previousClose 가 아니다 — v8 meta 에서는 None 으로 온다.
            previous_close=_dec(meta.get("chartPreviousClose")),
            as_of=(
                datetime.fromtimestamp(traded_at, tz=timezone.utc)
                if isinstance(traded_at, (int, float))
                else None
            ),
            source=self.name,
        )

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        wanted = [s for s in dict.fromkeys(symbols) if s]
        if not wanted:
            return {}
        workers = min(self._max_workers, len(wanted))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            found = pool.map(self._one, wanted)
        return {q.symbol: q for q in found if q is not None}
