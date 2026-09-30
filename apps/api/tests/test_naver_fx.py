from decimal import Decimal

from app.core import naver_fx


def _reset(monkeypatch):
    monkeypatch.setattr(naver_fx, "_last", None)
    monkeypatch.setattr(naver_fx, "_next_at", 0.0)
    monkeypatch.setattr(naver_fx, "_failures", 0)


def test_parse_both_shapes():
    info = {
        "closePrice": "1,358.50",
        "degreeCount": 5411,
        "localTradedAt": "2026-09-25T23:16:55+09:00",
        "stockExchangeType": {"nameKor": "하나은행"},
    }
    for body in ({"exchangeInfo": info}, {"result": info}):
        rate = naver_fx.parse(body)
        assert rate is not None
        assert rate.rate == Decimal("1358.50")
        assert rate.round == 5411
        assert rate.bank == "하나은행"


def test_parse_rejects_missing_or_bad_price():
    assert naver_fx.parse({}) is None
    assert naver_fx.parse({"exchangeInfo": {"closePrice": "N/A"}}) is None
    assert naver_fx.parse({"exchangeInfo": {"closePrice": "0"}}) is None


def test_cache_then_stale_on_failure(monkeypatch):
    _reset(monkeypatch)
    good = naver_fx.parse({"exchangeInfo": {"closePrice": "1,360.00"}})
    calls = []
    monkeypatch.setattr(naver_fx, "_fetch", lambda: calls.append(1) or good)
    first = naver_fx.get_usdkrw()
    second = naver_fx.get_usdkrw()  # TTL 안 — 상류를 다시 부르지 않는다
    assert first == second and len(calls) == 1

    # 만료 뒤 실패하면 마지막 값을 stale 로 돌려주고 백오프한다.
    monkeypatch.setattr(naver_fx, "_next_at", 0.0)
    monkeypatch.setattr(naver_fx, "_fetch", lambda: None)
    stale = naver_fx.get_usdkrw()
    assert stale is not None and stale.stale and stale.rate == Decimal("1360.00")
    assert naver_fx._failures == 1


def test_no_value_ever_returns_none(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(naver_fx, "_fetch", lambda: None)
    assert naver_fx.get_usdkrw() is None
