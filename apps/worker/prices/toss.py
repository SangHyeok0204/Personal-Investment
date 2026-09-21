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
    markets = ("KOSPI", "KOSDAQ", "KRX")

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
        """종목 기본정보 다건 조회(최대 200)로 현재가를 모은다.

        한 종목이라도 값이 없으면 그 종목만 결과에서 빠진다 — 호출부가 "—" 로 그린다.
        """
        out: dict[str, Quote] = {}
        for chunk in _chunks(symbols, 200):
            rows = self._get("/api/v1/stocks", {"symbols": ",".join(chunk)})
            for row in rows or []:
                symbol = row.get("symbol") or row.get("code")
                price = _dec(row.get("close") or row.get("closePrice") or row.get("price"))
                if not symbol or price is None:
                    continue
                out[symbol] = Quote(
                    symbol=symbol,
                    price=price,
                    currency=row.get("currency") or "KRW",
                    previous_close=_dec(row.get("prevClosePrice") or row.get("base")),
                    as_of=datetime.now(KST),
                    source=self.name,
                )
        return out


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
