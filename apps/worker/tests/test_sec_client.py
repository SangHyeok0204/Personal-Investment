"""계획 A3a — SEC 공용 클라이언트: 속도 제한 · 403 멈춤 · 429 백오프 · UA 필수."""
import httpx
import pytest

from sec import client as sc


@pytest.fixture(autouse=True)
def _reset():
    sc._reset_for_tests()
    yield
    sc._reset_for_tests()


class _Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 4))
        self.t += s


def test_rate_limiter_spaces_calls():
    c = _Clock()
    lim = sc.RateLimiter(4, clock=c.now, sleep=c.sleep)
    for _ in range(5):
        lim.acquire()
    # 첫 호출은 바로, 이후 0.25초 간격 → 5회에 1초
    assert c.slept == [0.25, 0.25, 0.25, 0.25]


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_403_blocks_process_for_ten_minutes():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(403)

    lim = sc.RateLimiter(1000)
    with _client(handler) as client:
        with pytest.raises(sc.SecBlocked):
            sc.sec_get(client, "https://www.sec.gov/x", limiter=lim)
        # 멈춘 동안은 SEC 에 닿지 않는다
        with pytest.raises(sc.SecBlocked):
            sc.sec_get(client, "https://www.sec.gov/y", limiter=lim)
    assert len(calls) == 1
    assert sc.blocked_for() > 590


def test_429_backs_off_then_succeeds():
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"ok": 1})])
    slept = []
    with _client(lambda r: next(responses)) as client:
        resp = sc.sec_get(client, "https://data.sec.gov/x", limiter=sc.RateLimiter(1000), sleep=slept.append)
    assert resp.status_code == 200 and slept == [1, 2]


def test_404_returned_as_is():
    with _client(lambda r: httpx.Response(404)) as client:
        assert sc.sec_get(client, "https://www.sec.gov/nope", limiter=sc.RateLimiter(1000)).status_code == 404


def test_required_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(sc.SecConfigError):
        sc.required_user_agent()
    assert sc.user_agent().endswith("(dashboard@personal-investment.local)")   # 공시 화면은 기본값으로 계속
    monkeypatch.setenv("SEC_USER_AGENT", "Someone contact@example.com")
    assert sc.required_user_agent() == "Someone contact@example.com"


def test_limiter_holds_across_threads():
    """4스레드가 동시에 불러도 전체 속도가 제한을 넘지 않는다(실시계, 초당 40 으로 빠르게)."""
    import threading
    import time

    lim = sc.RateLimiter(40)
    stamps = []
    lock = threading.Lock()

    def work():
        for _ in range(10):
            lim.acquire()
            with lock:
                stamps.append(time.monotonic())

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    span = stamps[-1] - stamps[0]
    assert len(stamps) == 40
    assert span >= 39 / 40 * 0.95          # 40회 = 최소 39 간격 × 25ms


def test_timeout_retried_then_raised():
    n = {"calls": 0}

    def flaky(request):
        n["calls"] += 1
        if n["calls"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200)

    slept = []
    with _client(flaky) as client:
        assert sc.sec_get(client, "https://www.sec.gov/a", limiter=sc.RateLimiter(1000),
                          sleep=slept.append).status_code == 200
    assert slept == [1]

    def dead(request):
        raise httpx.ReadTimeout("slow", request=request)

    with _client(dead) as client, pytest.raises(httpx.ReadTimeout):
        sc.sec_get(client, "https://www.sec.gov/b", retries=2, limiter=sc.RateLimiter(1000), sleep=lambda s: None)
