"""토스증권 Open API 시세 소스.

DailyPriceAgent(`src/sources/toss.py`)의 검증된 클라이언트를 **시세 소스 계약**에
맞춰 옮겼다. 원본에서 가져온 것: OAuth2 client_credentials 토큰 + 만료 여유,
호출 간 페이싱, 401 1회 재발급, 429 백오프(Retry-After / X-RateLimit-Reset).

★운영 제약 (원본 주석 승계 — 실측으로 확인된 것들이라 지운다고 사라지지 않는다)
  - 클라이언트당 유효 토큰 1개. 재발급하면 기존 토큰이 즉시 무효가 된다.
    같은 키를 쓰는 다른 수집기와 **동시 가동 금지**.
  - MARKET_DATA_CHART 그룹 실측 한도 20 req/s. min_interval=0.12(≈8/s)에서
    429 없이 Remaining 19 유지(2026-08-20 실측).
  - ★2026-10-08 0.07(≈14/s)로 낮춤 — 토스 우선(데이·프리장 포함) 뒤 관심종목 51개가 페이싱만으로 6초
    (51×0.12). 한도 20/s 아래이고, 429 가 나면 `_get` 의 백오프가 받는다.
  - 토스도 **IP 허용목록**을 쓴다. 미등록이면 토큰 발급이
    `403 access_denied / "IP address not allowed"` 로 거부된다(자격증명 문제 아님).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .base import PriceSource, Quote

_log = logging.getLogger(__name__)

BASE = "https://openapi.tossinvest.com"
KST = timezone(timedelta(hours=9))


def _bar_date(timestamp: str | None):
    """봉의 거래일. ⚠️시각은 **13:00 KST 로 라벨링**되므로 시:분은 의미가 없다 —
    날짜만 쓴다(2026-09-22 실측: 9/22 봉이 `2026-09-22T13:00:00+09:00`)."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp).date()
    except ValueError:
        return None


class TossError(RuntimeError):
    pass


class TossAuthError(TossError):
    """토큰 발급 단계 실패 — 종목 하나의 문제가 아니라 **호출 전체**가 안 된다.

    ★2026-10-05: 종목별 실패와 섞어 삼키면 16종목이면 토큰 엔드포인트를 16번 두드리고
      결과는 조용히 빈 dict 가 된다. 그래서 따로 나눠 한 번만 올린다(`quotes`).
    """


class TossIpNotAllowed(TossAuthError):
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
                 min_interval: float = 0.07, sleep=time.sleep):
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
        # ★2026-10-07 동시 요청(아래 quotes) — 토큰 발급·페이싱 슬롯은 잠금으로 한 번에 하나만.
        self._token_lock = threading.Lock()
        self._pace_lock = threading.Lock()

    def close(self):
        if self._owns_http:
            self._http.close()

    # ── 토큰 ────────────────────────────────────────────────────────────────
    def _ensure_token(self):
        with self._token_lock:
            self._ensure_token_locked()

    def _ensure_token_locked(self):
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
            raise TossAuthError(f"token: {r.status_code} {r.text[:200]}")
        d = r.json()
        self._token = d["access_token"]
        self._token_exp = time.time() + int(d["expires_in"])

    # ── 공통 GET (페이싱 → 401 재발급 1회 → 429 백오프 1회) ──────────────────
    def _get(self, path, params):
        self._ensure_token()
        for attempt in (1, 2):
            # 페이싱: 요청 **시작** 간격만 min_interval 로 지킨다 — 응답 대기는 겹쳐도 된다(유량 한도는 req/s).
            with self._pace_lock:
                wait = self._min_interval - (time.time() - self._last_call)
                if wait > 0:
                    self._sleep(wait)
                self._last_call = time.time()
            used = self._token
            t0 = time.time()
            r = self._http.get(BASE + path, params=params,
                               headers={"Authorization": f"Bearer {used}"})
            took = time.time() - t0
            if took > 2.0 or r.status_code != 200:
                _log.warning("toss %s %s %s %.1fs", path, params.get("productCode") or params.get("symbol") or "", r.status_code, took)
            rl = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
            if rl:
                self.last_ratelimit = rl
            if r.status_code == 401 and attempt == 1:
                # ⚠️동시 요청이 각자 재발급하면 토큰이 서로를 무효화한다(클라이언트당 1개) — 아직 같은 토큰일 때만.
                with self._token_lock:
                    if self._token == used:
                        self._token = ""
                        self._ensure_token_locked()
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

        ★봉 타임스탬프는 **13:00 KST 로 라벨링**된다(2026-09-22 실측). 미국
          거래일 9/21 의 봉이 `2026-09-21T13:00:00+09:00` 으로 온다 — 실제 체결
          시각이 아니라 거래일을 가리키는 표식이다. 그래서 한국 오전에 데이마켓이
          열리면 **아직 시작도 안 한 미국 거래일**의 봉이 얇은 값으로 먼저 생긴다.

        ★정규장이 끝난 뒤에는 야후와 값이 같다 — **단, 데이마켓이 열리기 전까지만.**
          (2026-09-22 ET 17:02 / KST 06:02 실측: 7종목 전부 0.00% 차이.)

        ★2026-09-22 실측 3회 — 한국 데이마켓이 도는 동안 토스 당일 봉이 새로
          생기고 야후와 갈린다. **거래량이 12배 붙는 동안 부호까지 뒤집혔다:**
              KST 17:22  NVDA +0.05%  SOXL +2.58%  (SOXL 거래량   108,875)
              KST 17:52  NVDA +0.15%  SOXL +3.50%  (            614,032)
              KST 17:53  NVDA -0.26%  SOXL -2.12%  (          1,355,817)
          그동안 야후 값은 토스의 **전일 봉 종가와 소수점까지 일치**했다
          (NVDA 227.38). 즉 정규장이 닫힌 동안의 올바른 "현재가"는 야후 쪽이다.
          살아 움직이는 시장이지 잡음이 아니므로 값을 버리지 않고 표시만 한다.

        ⚠️측정 시각을 처음엔 09:02/09:32 로 적었는데 **기계 시계가 8시간 40분
          어긋나 있었다**(구글 HTTP Date 헤더로 확인). 그 위에 데이마켓 창을
          09:00~16:50 으로 박았고, 정작 17:53 에도 봉이 자라고 있었다.
          → 시간표를 쓰지 않고 **봉 날짜**로 판단하도록 바꿨다
            (`quote_cache.is_thin_session_quote`).

        """
        out: dict[str, Quote] = {}
        uniq = list(dict.fromkeys(symbols))
        if not uniq:
            return out
        # ★2026-10-07: 토스 우선(데이·프리장 포함)으로 바꾼 뒤 관심종목 51개 첫 조회가 15.7초 — 하나씩 차례로
        #   부르느라 응답 대기가 쌓였다. 토큰을 먼저 한 번 받고(동시 발급 방지), 요청 시작 간격(페이싱)은 그대로
        #   둔 채 응답 대기만 겹치게 8개씩 동시에 부른다(2026-10-08 실측: 4개는 응답 0.5초 × 51/4 ≈ 6.5초가 병목).
        self._ensure_token()

        def fetch(symbol):
            return symbol, self._get("/api/v1/candles", {"symbol": symbol, "interval": "1d", "count": 2})

        with ThreadPoolExecutor(max_workers=min(8, len(uniq))) as pool:
            futures = [pool.submit(fetch, sym) for sym in uniq]
        results = []
        for symbol, fut in zip(uniq, futures):
            try:
                results.append(fut.result())
            except TossAuthError:
                # ★2026-10-05: 토큰 단계 실패(IP 미허용 등)는 종목 탓이 아니다 — 한 번만 올린다.
                #   ⚠️여기서 삼키면 종목마다 토큰 발급을 다시 시도하고(16종목=16회), 호출부는
                #   빈 결과만 보고 조용히 야후로 넘어가 아무도 차단을 모른다.
                raise
            except Exception:
                # 한 종목이 실패해도 나머지는 살린다(예: 그 티커만 404).
                continue
        for symbol, res in results:
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
                # 이 가격이 얼마나 얇은 체결로 만들어졌는지 **숨기지 않는다.**
                volume=_dec(candles[0].get("volume")),
                trade_date=_bar_date(candles[0].get("timestamp")),
            )
        return out


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
