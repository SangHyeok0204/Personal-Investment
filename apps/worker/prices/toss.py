"""토스증권 Open API 시세 소스.

DailyPriceAgent(`src/sources/toss.py`)의 검증된 클라이언트를 **시세 소스 계약**에
맞춰 옮겼다. 원본에서 가져온 것: OAuth2 client_credentials 토큰 + 만료 여유,
호출 간 페이싱, 401 1회 재발급, 429 백오프(Retry-After / X-RateLimit-Reset).

★운영 제약 (원본 주석 승계 — 실측으로 확인된 것들이라 지운다고 사라지지 않는다)
  - 클라이언트당 유효 토큰 1개. 재발급하면 기존 토큰이 즉시 무효가 된다.
    같은 키를 쓰는 다른 수집기와 **동시 가동 금지**.
  - MARKET_DATA_CHART 그룹 실측 한도 20 req/s. min_interval=0.12(≈8/s)에서
    429 없이 Remaining 19 유지(2026-08-20 실측).
  - 토스도 **IP 허용목록**을 쓴다. 미등록이면 토큰 발급이
    `403 access_denied / "IP address not allowed"` 로 거부된다(자격증명 문제 아님).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .base import PriceSource, Quote

BASE = "https://openapi.tossinvest.com"
KST = timezone(timedelta(hours=9))


class TossError(RuntimeError):
    pass


class TossIpNotAllowed(TossError):
    """토큰 발급이 IP 허용목록에 막힘 — 자격증명 문제가 아니다."""


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class TossPriceSource(PriceSource):
    name = "toss"
    # ★미국 종목도 지원한다(2026-09-22 실측: AAPL → market=NASDAQ, currency=USD).
    #   이식 당시 KRX 만 적어 두었는데 틀렸다.
    markets = ("KOSPI", "KOSDAQ", "KRX", "NASDAQ", "NYSE", "AMEX", "US")

    def __init__(self, client_id, client_secret, http_client=None,
                 min_interval: float = 0.12, sleep=time.sleep):
        self._cid = client_id
        self._sec = client_secret
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=15.0)
        self._token = ""
        self._token_exp = 0.0
        self._min_interval = min_interval
        self._last_call = 0.0
        self._sleep = sleep
        self.last_ratelimit: dict = {}

    def close(self):
        if self._owns_http:
            self._http.close()

    # ── 토큰 ────────────────────────────────────────────────────────────────
    def _ensure_token(self):
        if self._token and time.time() < self._token_exp - 60:
            return
        r = self._http.post(
            f"{BASE}/oauth2/token",
            data={"grant_type": "client_credentials",
                  "client_id": self._cid, "client_secret": self._sec},
        )
        if r.status_code == 403 and "IP address not allowed" in r.text:
            raise TossIpNotAllowed(
                "토스 Open API 가 이 서버 IP 를 거부했습니다. WTS 설정→Open API 에서 "
                "현재 공인 IP 를 허용목록에 등록하세요(자격증명 문제 아님)."
            )
        if r.status_code != 200:
            # ⚠️본문 전체를 싣지 않는다 — 시크릿이 에코될 여지를 남기지 않는다.
            raise TossError(f"token: {r.status_code} {r.text[:200]}")
        d = r.json()
        self._token = d["access_token"]
        self._token_exp = time.time() + int(d["expires_in"])

    # ── 공통 GET (페이싱 → 401 재발급 1회 → 429 백오프 1회) ──────────────────
    def _get(self, path, params):
        self._ensure_token()
        wait = self._min_interval - (time.time() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        for attempt in (1, 2):
            self._last_call = time.time()
            r = self._http.get(BASE + path, params=params,
                               headers={"Authorization": f"Bearer {self._token}"})
            rl = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
            if rl:
                self.last_ratelimit = rl
            if r.status_code == 401 and attempt == 1:
                self._token = ""
                self._ensure_token()
                continue
            if r.status_code == 429 and attempt == 1:
                self._sleep(self._backoff_secs(r.headers))
                continue
            if r.status_code != 200:
                raise TossError(f"{path}: {r.status_code} {r.text[:200]}")
            return r.json()["result"]
        raise TossError(f"{path}: 재시도 소진")

    @staticmethod
    def _backoff_secs(headers) -> float:
        ra = headers.get("Retry-After")
        if ra and str(ra).replace(".", "", 1).isdigit():
            return min(float(ra), 120.0)
        reset = headers.get("X-RateLimit-Reset")
        if reset and str(reset).replace(".", "", 1).isdigit():
            v = float(reset)
            if v > 1e9:  # epoch 형식
                return max(0.0, min(v - time.time(), 120.0))
            return min(v, 120.0)  # 남은 초 형식
        return 5.0

    # ── 시세 ────────────────────────────────────────────────────────────────
    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """현재가를 일봉 최신 2개에서 뽑는다.

        ⚠️이식 당시 `/api/v1/stocks` 를 봤는데 **거기엔 가격이 없다**(2026-09-22
          실측). 그 엔드포인트는 종목명·ISIN·시장·통화·상장주식수 같은 기본정보만
          준다. 그래서 `close`/`closePrice` 를 찾던 파서가 늘 빈 결과를 냈다.
          가격은 `/api/v1/candles` 에 있다.

        ⚠️봉은 **최신순**으로 온다. candles[0] 이 오늘(진행 중), [1] 이 전일이다.
          오름차순으로 착각하면 현재가와 전일종가가 뒤바뀐다.

        ⚠️다건 조회가 없다 — 심볼마다 한 번씩 부른다. 유량제한이 있으므로
          `_get` 의 페이싱(min_interval)을 그대로 탄다.

        ⚠️미국 종목의 **당일 봉은 한국 데이마켓(KST 09:00~16:50) 체결을 포함**한다.
          미국 정규장이 닫혀 있는 동안 이 값은 거래량이 정규장의 1% 미만인 얇은
          체결가라 "현재가"로 쓰면 안 된다(DailyPriceAgent 실측: NVDA 371,568주
          vs 정규장 9,400만주). 그래서 호출부가 세션을 보고 소스 순서를 정한다.
        """
        out: dict[str, Quote] = {}
        for symbol in dict.fromkeys(symbols):
            try:
                res = self._get(
                    "/api/v1/candles",
                    {"symbol": symbol, "interval": "1d", "count": 2},
                )
            except Exception:
                # 한 종목이 실패해도 나머지는 살린다.
                continue
            candles = (res or {}).get("candles") or []
            if not candles:
                continue
            price = _dec(candles[0].get("closePrice"))
            if price is None:
                continue
            out[symbol] = Quote(
                symbol=symbol,
                price=price,
                currency=candles[0].get("currency") or "KRW",
                previous_close=(
                    _dec(candles[1].get("closePrice")) if len(candles) > 1 else None
                ),
                as_of=datetime.now(KST),
                source=self.name,
            )
        return out


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
