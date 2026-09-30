"""SEC EDGAR 공용 요청 — 속도 제한 · 429/5xx 백오프 · 403 이면 멈춤 (계획 A3a).

SEC 공정 접근 규칙: **초당 10회 이하**, 연락처가 담긴 User-Agent. 어기면 403 과 함께 IP 가
한동안 막힌다(실측: 파이썬 기본 UA → www.sec.gov 403).

★속도 제한은 **프로세스마다** 건다. SEC 를 부르는 프로세스가 둘이다 — API(공시 화면,
  `prices/filings.py`)와 sec_crawl worker(13F·Form 4 수집). 프로세스 사이를 맞추는 대신
  각자 초당 4회로 묶어 **합계가 8회를 넘지 않게** 한다(`SEC_RATE_PER_PROCESS` 로 조정).
⚠️403 을 받으면 그 프로세스의 SEC 요청을 **10분 동안 전부 멈춘다.** 막힌 상태에서 계속
  두드리면 차단이 길어진다. 멈춘 동안의 호출은 SEC 에 닿지 않고 바로 `SecBlocked` 를 낸다.
"""
from __future__ import annotations

import os
import threading
import time

import httpx

_DEFAULT_UA = "Personal-Investment-Dashboard/1.0 (dashboard@personal-investment.local)"
BLOCK_SECONDS = 10 * 60


class SecBlocked(Exception):
    """403 을 받았거나 403 뒤 쉬는 중. 재시도하지 말 것."""


class SecConfigError(Exception):
    """SEC_USER_AGENT 가 없다 — 새 수집 작업은 연락처 없이 돌지 않는다."""


class RateLimiter:
    """스레드 안전한 최소 간격 제한기. `rate` 회/초."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=time.sleep):
        self._interval = 1.0 / rate
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            self._sleep(wait)


_limiter = RateLimiter(float(os.environ.get("SEC_RATE_PER_PROCESS", "4")))
_block_lock = threading.Lock()
_blocked_until = 0.0


def user_agent() -> str:
    """공시 화면용 UA — 설정이 없으면 앱 이름(개인 이메일을 말없이 보내지 않는다)."""
    return (os.environ.get("SEC_USER_AGENT") or "").strip() or _DEFAULT_UA


def required_user_agent() -> str:
    """새 수집 작업용 UA. 없으면 돌지 않는다 — `/data-operations` 에 'SEC UA 미설정'."""
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua:
        raise SecConfigError("SEC_USER_AGENT 미설정 — .env.local 에 연락처가 담긴 UA 를 넣어야 한다")
    return ua


def sec_client(timeout: float = 15.0, *, require_ua: bool = False) -> httpx.Client:
    ua = required_user_agent() if require_ua else user_agent()
    return httpx.Client(timeout=timeout, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})


def blocked_for() -> float:
    """403 뒤 남은 휴식 시간(초). 0 이면 요청 가능."""
    with _block_lock:
        return max(0.0, _blocked_until - time.monotonic())


def sec_get(client: httpx.Client, url: str, *, retries: int = 3, limiter: RateLimiter | None = None,
            sleep=time.sleep, **kwargs) -> httpx.Response:
    """속도 제한을 지켜 GET. 429·5xx·연결 끊김·시간 초과는 1·2·4초 물러나 재시도, 403 은 멈춤.

    200·404 등은 그대로 돌려준다(404 = 없는 문서 — 호출한 쪽이 판단).
    """
    global _blocked_until
    if blocked_for() > 0:
        raise SecBlocked(f"SEC 403 뒤 휴식 중 — {blocked_for():.0f}초 남음")
    limiter = limiter or _limiter
    response = None
    for attempt in range(retries + 1):
        limiter.acquire()
        try:
            response = client.get(url, **kwargs)
        except httpx.TransportError:
            # 실측: 문서 하나의 읽기 시간 초과(맥 잠듦)로 한 회차 전체가 실패했다 — 끊김·시간 초과는 재시도.
            if attempt < retries:
                sleep(2 ** attempt)
                continue
            raise
        if response.status_code == 403:
            with _block_lock:
                _blocked_until = time.monotonic() + BLOCK_SECONDS
            raise SecBlocked(f"SEC 403 — {BLOCK_SECONDS // 60}분 멈춤 ({url})")
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < retries:
                sleep(2 ** attempt)
                continue
        return response
    return response


def _reset_for_tests() -> None:
    global _blocked_until
    with _block_lock:
        _blocked_until = 0.0
