"""보유 종목 시세 — 시세 소스 조립 + 짧은 TTL 캐시.

★왜 서버에 캐시를 두나(2026-09-22):
  화면이 5초마다 `/portfolio/quotes` 를 부른다. 탭을 두 개 열거나 새로고침을
  연타하면 그만큼 야후 호출이 배로 늘어난다. TTL 안에서는 같은 결과를 돌려주어
  **상류 호출 수를 화면 수와 무관하게** 묶는다.

  TTL 은 화면 주기(5초)보다 **살짝 짧게** 둔다. 같게 두면 매번 만료 직전에 걸려
  캐시가 사실상 동작하지 않거나, 반대로 한 주기를 통째로 건너뛴다.

⚠️캐시는 프로세스 메모리다. uvicorn 워커가 여럿이면 워커마다 따로 채워진다.
  지금은 단일 프로세스라 문제가 없고, 늘릴 때는 Redis 로 옮겨야 한다.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# worker 패키지(brokers/, prices/)를 재사용한다 — API 가 같은 계약을 두 번 쓰지 않는다.
_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices import CompositePriceSource, Quote, YahooPriceSource  # noqa: E402

TTL_SECONDS = 4.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, Quote]] = {}


def _build_source() -> CompositePriceSource:
    """시세 소스 사슬.

    지금은 야후 하나다. 토스는 자격증명(+IP 허용목록)이 들어오는 순간 여기에
    한 줄 추가하면 된다 — 앞 소스가 못 준 심볼만 뒤로 넘어간다.
    ⚠️토스를 조건 없이 끼워 두지 않는다. 키가 없으면 매 호출마다 토큰 발급이
      실패해 5초마다 쓸모없는 네트워크 왕복이 생긴다.
    """
    sources = [YahooPriceSource()]
    return CompositePriceSource(sources)


def get_quotes(symbols: list[str]) -> tuple[dict[str, Quote], int]:
    """심볼별 시세와 **상류에서 새로 받아온 개수**.

    캐시가 살아 있는 심볼은 그대로 쓰고, 만료된 것만 묶어서 한 번에 받아온다.
    """
    wanted = [s for s in dict.fromkeys(symbols) if s]
    if not wanted:
        return {}, 0

    now = time.monotonic()
    out: dict[str, Quote] = {}
    stale: list[str] = []

    with _lock:
        for symbol in wanted:
            hit = _cache.get(symbol)
            if hit and now - hit[0] < TTL_SECONDS:
                out[symbol] = hit[1]
            else:
                stale.append(symbol)

    if not stale:
        return out, 0

    source = _build_source()
    try:
        fetched = source.quotes(stale)
    finally:
        source.close()

    stored = time.monotonic()
    with _lock:
        for symbol, quote in fetched.items():
            _cache[symbol] = (stored, quote)
    out.update(fetched)
    # ⚠️못 받은 심볼은 out 에 없다. 호출부가 "—" 로 그린다 — 0 으로 채우지 않는다.
    return out, len(fetched)


def clear_cache() -> None:
    """테스트용. 프로덕션 경로에서는 부르지 않는다."""
    with _lock:
        _cache.clear()
