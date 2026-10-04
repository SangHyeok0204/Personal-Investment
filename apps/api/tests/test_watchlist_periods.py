"""시장 리서치 표의 5D/20D/60D(거래일) 변화율 · 티커 → 밸류체인 L1 색 — 2026-10-04."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core import quote_cache
from app.core import valuechain as vc
from app.core.market_history import Series


def _closes(n: int) -> list[Decimal]:
    # 종가 = 100, 101, …, 100+n-1. N거래일 전 종가가 무엇인지 눈으로 바로 보인다.
    return [Decimal(100 + i) for i in range(n)]


def test_trading_day_changes_use_index_minus_n() -> None:
    closes = _closes(61)                      # 마지막 = 160
    got = quote_cache.trading_day_changes(closes)
    assert got[5] == Decimal(160) / Decimal(155) - 1      # closes[-6]
    assert got[20] == Decimal(160) / Decimal(140) - 1     # closes[-21]
    assert got[60] == Decimal(160) / Decimal(100) - 1     # closes[-61] = 첫 값


def test_short_history_is_none_not_zero() -> None:
    """⚠️60거래일이 안 되면 60D 는 None — 있는 만큼으로 줄여 계산하지 않는다."""
    got = quote_cache.trading_day_changes(_closes(60))
    assert got[60] is None
    assert got[20] is not None and got[5] is not None
    got = quote_cache.trading_day_changes(_closes(5))
    assert got == {5: None, 20: None, 60: None}
    assert quote_cache.trading_day_changes([]) == {5: None, 20: None, 60: None}


def _series(last: date, n: int = 61, currency: str = "USD") -> Series:
    dates = [last - timedelta(days=n - 1 - i) for i in range(n)]
    closes = _closes(n)
    return Series(symbol="X", dates=dates, closes=closes, currency=currency, latest=closes[-1])


def test_in_progress_bar_is_dropped() -> None:
    """★마지막 **완결** 일 종가 기준 — 장중의 오늘 봉은 빼고 센다."""
    day = date(2026, 10, 1)                   # 목요일
    intraday = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)   # 11:00 ET, 장중
    after = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)      # 17:00 ET, 마감 후
    s = _series(day)
    assert quote_cache._completed_closes(s, intraday) == s.closes[:-1]
    assert quote_cache._completed_closes(s, after) == s.closes
    # 한국 종목은 15:30 KST 마감으로 본다.
    k = _series(day, currency="KRW")
    assert quote_cache._completed_closes(k, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)) == k.closes[:-1]
    assert quote_cache._completed_closes(k, datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)) == k.closes


def test_history_is_cached_and_missing_symbol_is_none(monkeypatch) -> None:
    quote_cache.clear_cache()
    calls: list[list[str]] = []

    def fake(symbols, range_):
        calls.append(list(symbols))
        return {"AAA": _series(date(2026, 9, 30))}

    monkeypatch.setattr(quote_cache, "fetch_history", fake)
    now = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
    first = quote_cache.get_trading_changes(["AAA", "BBB"], now)
    second = quote_cache.get_trading_changes(["AAA", "BBB"], now)
    assert calls == [["AAA", "BBB"]]          # 두 번째는 캐시 — 상류 호출 없음
    assert first == second
    assert first["AAA"][60] == Decimal(160) / Decimal(100) - 1
    assert first["BBB"] == {5: None, 20: None, 60: None}
    quote_cache.clear_cache()


def test_ticker_l1_map_taxonomy_only() -> None:
    """★분류 섹터(L1)만, 첫 L1 규칙. 테마 섹터·ETF 는 매핑 없음(추측하지 않는다)."""
    m = vc.ticker_l1_map()
    tx = {s.code: s for s in vc.load_all()[0] if s.kind == "taxonomy"}
    assert m["NVDA"] == (tx["tx-digital"].name, tx["tx-digital"].color)
    assert m["NVDA"][1].startswith("#")
    assert m["JPM"] == (tx["tx-financials"].name, tx["tx-financials"].color)
    # 지정 안 된 ETF 는 매핑 없음(추측하지 않는다).
    assert "SCHD" not in m
    # 바이오 테마 전용 한국 종목(분류 생성물에 없음)도 L1 이 없다.
    assert "468530" not in m
    assert set(m.values()) <= {(s.name, s.color) for s in tx.values()}
    assert vc.ticker_l1_map() is m            # 파일이 그대로면 결과를 재사용한다


def test_etf_l1_overrides_follow_user_assignment() -> None:
    """★2026-10-04 사용자 지정 ETF L1 — SOXL 디지털·컴퓨팅, TSL = TSLA 의 L1, 원자재·금·코인 = 자원·기초소재."""
    m = vc.ticker_l1_map()
    tx = {s.name: s.color for s in vc.load_all()[0] if s.kind == "taxonomy" and s.color}
    assert m["SOXL"] == ("디지털·컴퓨팅", tx["디지털·컴퓨팅"])
    assert m["TSL"] == m["TSLA"]
    for etf in ("XLB", "GLD", "BITO", "EETH"):
        assert m[etf] == ("자원·기초소재", tx["자원·기초소재"])


def test_l1_palette_follows_catalog_order() -> None:
    pal = vc.l1_palette()
    assert len(pal) == 12 and len({c for _, c in pal}) == 12
    assert [n for n, _ in pal][:3] == ["산업재·건설", "금융", "재량소비"]      # 허브 묶음 순서
