"""★2026-10-09: 동시에 같은 종목을 물으면 상류에서는 한 번만 받는다(줄 선 요청은 캐시를 다시 본다)."""
from __future__ import annotations

import threading
import time
from decimal import Decimal

from app.core import quote_cache
from prices.base import Quote


class _SlowSource:
    name = "fake"

    def __init__(self, calls: list):
        self._calls = calls

    def quotes(self, symbols):
        self._calls.append(list(symbols))
        time.sleep(0.2)
        return {s: Quote(symbol=s, price=Decimal("1"), currency="USD") for s in symbols}

    def close(self):
        pass


def test_concurrent_requests_fetch_upstream_once(monkeypatch) -> None:
    quote_cache.clear_cache()
    calls: list = []
    monkeypatch.setattr(quote_cache, "_build_source", lambda: _SlowSource(calls))
    monkeypatch.setattr(quote_cache, "_note_toss", lambda source, bind: None)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(quote_cache.get_quotes(["NVDA", "TSLA"])[0]))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1
    assert all(set(r) == {"NVDA", "TSLA"} for r in results)
    quote_cache.clear_cache()
