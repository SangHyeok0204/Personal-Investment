"""토스 토큰 차단을 조용히 삼키지 않는다(2026-10-05).

★2026-10-05 23:40 KST 실측(미국 정규장): 맥의 공인 IP 가 바뀌어 토스가 토큰 발급을
  403(IP 미허용)으로 거부했다. 시세는 조용히 야후로 넘어갔고, 연동 화면은 계속
  '연동됨 · 지금 사용'이었으며 수집 상태에도 아무 경고가 없었다. 5초마다 종목 수만큼
  토큰 엔드포인트를 두드렸다.
⚠️실제 토스/야후를 부르지 않는다 — 가짜 소스만 쓴다(토스는 클라이언트당 유효 토큰 1개).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

import app.core.quote_cache as qc
from prices import PriceSource, Quote
from prices.toss import TossIpNotAllowed


class _FakeYahoo(PriceSource):
    name = "yahoo"

    def __init__(self, *a, **k):
        pass

    def quotes(self, symbols):
        return {s: Quote(symbol=s, price=Decimal("10"), source="yahoo") for s in symbols}


def _fake_toss(calls: list, mode: dict):
    class _FakeToss(PriceSource):
        name = "toss"

        def __init__(self, *a, **k):
            pass

        def quotes(self, symbols):
            calls.append(list(symbols))
            if mode["blocked"]:
                raise TossIpNotAllowed("토스 Open API 가 이 서버 IP 를 거부했습니다.")
            return {s: Quote(symbol=s, price=Decimal("11"), source="toss") for s in symbols}

    return _FakeToss


@pytest.fixture()
def fakes(monkeypatch):
    qc.clear_cache()
    calls: list = []
    mode = {"blocked": True}
    clock = {"t": 1000.0}
    monkeypatch.setattr(qc, "YahooPriceSource", _FakeYahoo)
    monkeypatch.setattr(qc, "TossPriceSource", _fake_toss(calls, mode))
    monkeypatch.setattr(qc.credentials_store, "read_env_value", lambda name: "dummy")
    monkeypatch.setattr(qc, "us_regular_session_open", lambda now=None: True)
    monkeypatch.setattr(qc.time, "monotonic", lambda: clock["t"])
    yield calls, mode, clock
    qc.clear_cache()


def _advance(clock, secs):
    clock["t"] += secs


def test_blocked_toss_falls_back_and_cools_down(fakes) -> None:
    calls, mode, clock = fakes
    got, _ = qc.get_quotes(["AAA", "BBB"])
    assert {q.source for q in got.values()} == {"yahoo"}       # 야후가 대신 준다
    assert len(calls) == 1                                     # 토스는 한 번만
    assert qc.toss_status()["state"] == "ip_blocked"
    assert qc.toss_status()["cooldown"] is True

    # 쿨다운 중에는 5초 폴링이 와도 토스를 부르지 않는다.
    for _ in range(5):
        _advance(clock, qc.TTL_SECONDS + 1)
        got, _ = qc.get_quotes(["AAA", "BBB"])
        assert got["AAA"].source == "yahoo"
    assert len(calls) == 1

    # 쿨다운이 지나면 다시 한 번 시도한다 — IP 를 등록했다면 토스로 돌아온다.
    mode["blocked"] = False
    _advance(clock, qc.TOSS_COOLDOWN_SECONDS)
    got, _ = qc.get_quotes(["AAA"])
    assert len(calls) == 2
    assert got["AAA"].source == "toss"
    assert qc.toss_status()["state"] == "ok"
    assert qc.toss_status()["cooldown"] is False


def _rows(db):
    return db.execute(
        text("SELECT source, last_ok_at, last_error_at, last_error_kind, last_error_message, updated_at "
             "FROM source_status WHERE source = 'toss'")
    ).all()


def test_source_status_is_written_only_on_state_change(fakes, db) -> None:
    calls, mode, clock = fakes
    bind = db.get_bind()  # 테스트 DB

    qc.get_quotes(["AAA"], bind=bind)
    rows = _rows(db)
    assert len(rows) == 1 and rows[0].last_error_kind == "config"
    assert "IP" in rows[0].last_error_message
    first_update = rows[0].updated_at

    # 쿨다운이 지나 다시 막혀도 상태가 같으면 쓰지 않는다.
    _advance(clock, qc.TOSS_COOLDOWN_SECONDS + 1)
    qc.get_quotes(["AAA"], bind=bind)
    assert len(calls) == 2
    db.commit()  # 스냅숏 갱신
    assert _rows(db)[0].updated_at == first_update

    # 풀리면 ok 를 한 번 쓴다.
    mode["blocked"] = False
    _advance(clock, qc.TOSS_COOLDOWN_SECONDS + 1)
    qc.get_quotes(["AAA"], bind=bind)
    db.commit()
    row = _rows(db)[0]
    assert row.last_ok_at is not None
    ok_update = row.updated_at

    _advance(clock, qc.TTL_SECONDS + 1)
    qc.get_quotes(["AAA"], bind=bind)                          # ok → ok: 쓰지 않는다
    db.commit()
    assert _rows(db)[0].updated_at == ok_update


def test_price_sources_shows_blocked_toss(fakes, client) -> None:
    qc.get_quotes(["AAA"])
    by = {s["id"]: s for s in client.get("/api/v1/brokerage/price-sources").json()["sources"]}
    assert by["toss"]["state"] == "ip_blocked"
    assert by["toss"]["rank"] is None                          # 지금 안 쓴다
    assert by["yahoo"]["rank"] == 1
    assert "IP" in by["toss"]["message"]


def test_toss_source_and_token_are_reused_across_polls(fakes) -> None:
    """★2026-10-05 캐시가 빌 때마다 토스 인스턴스(=토큰)를 새로 만들던 것 — 키가 같으면 재사용."""
    calls, mode, clock = fakes
    mode["blocked"] = False
    made = []
    orig = qc.TossPriceSource

    def counting(*a, **k):
        made.append(1)
        return orig(*a, **k)

    qc.TossPriceSource = counting
    try:
        qc.get_quotes(["AAA"])
        _advance(clock, qc.TTL_SECONDS + 1)
        qc.get_quotes(["AAA"])
    finally:
        qc.TossPriceSource = orig
    assert len(made) == 1 and len(calls) == 2
