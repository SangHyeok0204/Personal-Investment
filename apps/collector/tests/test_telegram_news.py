"""telegram_news 회귀 테스트 (상류 집계 JSON 리더).

집계 자체는 S: Telegram_Bot 이 Opus 로 하고, 이 모듈은 읽어 넘기기만 한다. 그래서
여기서 고정할 값어치가 있는 건 '조용히 틀리는' 판독·판정 경로뿐이다.

  1) 리포트의 top 3 + notable 2 가 열당 5장으로, notable 표시를 달고 들어오는가
  2) summary 의 '·' 나열이 칩으로 끊기는가
  3) 카드 id 가 제목 기준으로 안정적인가 (풀링마다 바뀌면 애니메이션이 헛돈다)
  4) 풀링을 빠뜨렸을 때 stale 이 서는가  ← 하루 2회뿐이라 한 번 빠지면 반나절 옛 집계
  5) 유예시간 안(집계가 도는 중)에는 stale 이 서지 않는가
  6) 집계 파일이 없을 때 500 대신 available=false 로 내려가는가
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import telegram_news as tn  # noqa: E402


def _issue(title, summary="A · B · C", mentions=5):
    return {"title": title, "summary": summary, "mentions": mentions}


def _analysis(generated: datetime) -> dict:
    return {
        "generatedAt": generated.isoformat(),
        "windowStart": (generated - timedelta(hours=24)).isoformat(),
        "windowEnd": generated.isoformat(),
        "windowHours": 24,
        "topics": 1085,
        "rooms": 63,
        "sections": {
            "macro": {
                "top": [_issue(f"매크로 상위 {i}", mentions=30 - i) for i in range(3)],
                "notable": [_issue(f"매크로 특이 {i}", mentions=3) for i in range(2)],
            },
            "industry": {
                "top": [_issue(f"산업 상위 {i}") for i in range(3)],
                "notable": [_issue(f"산업 특이 {i}") for i in range(2)],
            },
            "stock": {
                "top": [_issue(f"종목 상위 {i}") for i in range(3)],
                "notable": [_issue(f"종목 특이 {i}") for i in range(2)],
            },
        },
    }


@pytest.fixture()
def news(tmp_path, monkeypatch):
    path = tmp_path / "output" / "dashboard_analysis.json"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(tn, "ANALYSIS_PATH", str(path))
    return tn.TelegramNews(), path


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# 1) 5×3 격자 -----------------------------------------------------------------
def test_three_by_five_grid_with_notable_flag(news):
    store, path = news
    _write(path, _analysis(datetime.now(tn.KST)))
    store.refresh()
    payload, _ = store.serve()

    assert [s["key"] for s in payload["categories"]] == ["macro", "industry", "stock"]
    for sec in payload["categories"]:
        assert len(sec["cards"]) == 5, sec["key"]
        # 리포트 구조 그대로 — 앞 3장이 상위, 뒤 2장이 단독·특이
        assert [c["notable"] for c in sec["cards"]] == [False, False, False, True, True]
    macro = payload["categories"][0]["cards"]
    assert macro[0]["mentions"] == 30
    assert payload["topics"] == 1085 and payload["rooms"] == 63


# 2) summary → 칩 -------------------------------------------------------------
def test_summary_splits_into_chips(news):
    store, path = news
    data = _analysis(datetime.now(tn.KST))
    data["sections"]["macro"]["top"][0]["summary"] = (
        "WTI 82.1달러(+5.1%) · 브렌트 91.9달러 · 美 10Y 4.71% · 유가 급등 후 되돌림"
    )
    _write(path, data)
    store.refresh()
    payload, _ = store.serve()

    chips = payload["categories"][0]["cards"][0]["chips"]
    assert chips[0] == "WTI 82.1달러(+5.1%)"
    assert "美 10Y 4.71%" in chips
    assert len(chips) == 4


def test_chip_count_is_capped(news):
    store, path = news
    data = _analysis(datetime.now(tn.KST))
    data["sections"]["macro"]["top"][0]["summary"] = " · ".join(f"항목{i}" for i in range(20))
    _write(path, data)
    store.refresh()
    payload, _ = store.serve()
    assert len(payload["categories"][0]["cards"][0]["chips"]) == tn.MAX_CHIPS


# 3) 카드 id 안정성 -----------------------------------------------------------
def test_card_id_is_stable_for_same_title(news):
    """풀링마다 id 가 바뀌면 내용이 같아도 전부 '신규 카드'로 깜빡인다."""
    store, path = news
    now = datetime.now(tn.KST)
    _write(path, _analysis(now))
    store.refresh()
    first = [c["id"] for c in store.serve()[0]["categories"][0]["cards"]]

    later = _analysis(now + timedelta(hours=5))  # 다음 풀링, 제목은 그대로
    _write(path, later)
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    store.refresh()
    second = [c["id"] for c in store.serve()[0]["categories"][0]["cards"]]
    assert first == second

    changed = _analysis(now + timedelta(hours=5))
    changed["sections"]["macro"]["top"][0]["title"] = "완전히 다른 이슈"
    _write(path, changed)
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 20))
    store.refresh()
    third = [c["id"] for c in store.serve()[0]["categories"][0]["cards"]]
    assert third[0] != first[0] and third[1:] == first[1:]


# 4) 풀링 누락 ----------------------------------------------------------------
def test_missed_pooling_marks_stale(news):
    store, path = news
    now = datetime.now(tn.KST)
    expected = tn._expected_pool(now)
    # 유예시간을 넘겨 예정 시각이 지났는데 집계는 그 전 것 = 풀링이 빠졌다
    if (now - expected) <= timedelta(minutes=tn.POOL_GRACE_MIN):
        pytest.skip("지금은 유예시간 안이라 이 판정을 시험할 수 없다")
    _write(path, _analysis(expected - timedelta(hours=1)))
    store.refresh()
    payload, _ = store.serve()
    assert payload["stale"] is True
    assert payload["available"] is True  # 파일은 있다 — 낡았을 뿐


def test_fresh_pooling_is_not_stale(news):
    store, path = news
    _write(path, _analysis(datetime.now(tn.KST)))
    store.refresh()
    assert store.serve()[0]["stale"] is False


# 5) 파일 부재 ----------------------------------------------------------------
def test_missing_file_degrades_not_crashes(news):
    store, path = news
    store.refresh()  # 아직 아무도 안 구웠다
    payload, etag = store.serve()
    assert payload is not None and etag
    assert payload["available"] is False
    assert payload["stale"] is True
    assert all(s["cards"] == [] for s in payload["categories"])
    assert [s["key"] for s in payload["categories"]] == ["macro", "industry", "stock"]


def test_corrupt_file_keeps_last_good(news):
    """쓰는 도중 읽어 깨진 JSON 이 와도 화면이 비지 않아야 한다."""
    store, path = news
    _write(path, _analysis(datetime.now(tn.KST)))
    store.refresh()
    good = store.serve()[0]["categories"][0]["cards"][0]["title"]

    path.write_text("{ 깨진", encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 30))
    store.refresh()
    assert store.serve()[0]["categories"][0]["cards"][0]["title"] == good
