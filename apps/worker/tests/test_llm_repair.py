"""하네스 L1 — 작업 안 1회 수리 재시도 · 에스컬레이션 패킷. LLM · SEC 는 가짜(네트워크 없음)."""
import json
import re
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text

import main
from handlers import llm_watchpoints as wp
from llm.cli import LlmError, LlmResult
from llm.repair import REPAIR_INSTRUCTION, RepairFailed, run_with_repair

GOOD = '{"watching_points": [{"text": "데이터센터 매출 성장"}], "detail": "d"}'
BAD = "관전포인트를 만들 수 없습니다"
PACKET_KEYS = {"task", "decision_needed", "last_validator_errors", "prompt_sha256", "source", "alternatives_tried",
               "safe_default"}


class FakeRunner:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LlmResult(text=r, model="claude-test", cost_usd=None, duration_ms=1, calls_today=len(self.prompts))


def _validate(d):
    return bool(d["points"]), [] if d["points"] else ["watching_points 목록이 없거나 비었음"]


def test_bad_then_good_succeeds_with_two_calls():
    llm = FakeRunner(BAD, GOOD)
    rep = run_with_repair("원래 프롬프트", llm, wp.parse_watchpoints, _validate)
    assert rep.calls == 2 and len(llm.prompts) == 2
    assert rep.data["points"][0]["text"] == "데이터센터 매출 성장"


def test_repair_prompt_holds_warns_inside_fence():
    llm = FakeRunner(BAD, GOOD)
    run_with_repair("원래 프롬프트", llm, wp.parse_watchpoints, _validate)
    second = llm.prompts[1]
    assert second.startswith("원래 프롬프트")
    m = re.search(r"<<<DATA 검증 오류 ([0-9a-f]{6})>>>\n(.*?)\n<<<END 검증 오류 \1>>>", second, re.S)
    assert m and m.group(2) == "watching_points 목록이 없거나 비었음"
    assert second.rstrip().endswith(REPAIR_INSTRUCTION)


@pytest.mark.parametrize("kind", ["cap", "logged_out", "auth", "usage_limit", "stopped", "timeout"])
def test_llm_error_is_not_repaired(kind):
    llm = FakeRunner(LlmError(kind, "x"), GOOD)
    with pytest.raises(LlmError):
        run_with_repair("p", llm, wp.parse_watchpoints, _validate)
    assert len(llm.prompts) == 1


def test_bad_then_bad_raises_after_two_calls():
    llm = FakeRunner(BAD, BAD, GOOD)
    with pytest.raises(RepairFailed) as ei:
        run_with_repair("p", llm, wp.parse_watchpoints, _validate)
    assert len(llm.prompts) == 2 and ei.value.calls == 2 and ei.value.last_text == BAD


# ── 핸들러를 통째로(worker process_job): 수리까지 실패 → FAILED · 패킷 1장 · 더 부르지 않음 ──────────────


@contextmanager
def _fake_sec(*a, **k):
    yield object()


class _Resp:
    def json(self):
        return {"0": {"ticker": "NVDA", "cik_str": 1045810, "title": "NVIDIA"}}


@pytest.fixture
def fake_wp(monkeypatch):
    monkeypatch.setattr(wp, "target_quarter", lambda c, t, d: ("2026Q3", "NVIDIA"))
    monkeypatch.setattr(wp, "sec_client", _fake_sec)
    monkeypatch.setattr(wp, "sec_get", lambda sec, url: _Resp())
    monkeypatch.setattr(wp, "earnings_release", lambda sec, cik: {
        "text": "보도자료 본문", "filing_date": "2026-08-27", "url": "https://www.sec.gov/x.htm"})

    def use(llm):
        monkeypatch.setattr(wp, "run_claude", llm)
    return use


def _job(engine, job_type, payload):
    jid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO jobs (id, job_type, status, payload) VALUES (:i, :t, 'PENDING', CAST(:p AS JSONB))"),
                  {"i": jid, "t": job_type, "p": json.dumps(payload)})
    return jid


def test_handler_bad_bad_fails_with_one_packet_and_no_retry(db, tmp_path, fake_wp):
    llm = FakeRunner(BAD, BAD, GOOD)
    fake_wp(llm)
    jid = _job(db, "LLM_WATCHPOINTS", {"ticker": "NVDA", "quarter": "2026Q3"})
    assert main.run_one_cycle(db, str(tmp_path)) is True
    with db.begin() as c:
        status, err, attempts = c.execute(text("SELECT status, error_message, attempts FROM jobs WHERE id = :i"),
                                          {"i": jid}).one()
        src = c.execute(text("SELECT last_error_kind FROM source_status WHERE source = 'claude'")).scalar()
    assert (status, attempts, src) == ("FAILED", 1, "other") and "관전포인트" in err
    assert len(llm.prompts) == 2                               # 원래 1 + 수리 1 — 그 이상 없음
    files = list((tmp_path / "llm" / "escalations").glob("*.json"))
    assert len(files) == 1 and files[0].name.endswith("-LLM_WATCHPOINTS-NVDA-2026Q3.json")
    packet = json.loads(files[0].read_text())
    assert PACKET_KEYS <= set(packet)
    assert packet["last_validator_errors"] == ["watching_points 목록이 없거나 비었음"]
    assert packet["source"] == {"filing_url": "https://www.sec.gov/x.htm"} and len(packet["prompt_sha256"]) == 64
    assert main.run_one_cycle(db, str(tmp_path)) is False      # worker 가 스스로 다시 넣지 않는다


def test_handler_bad_good_succeeds(db, tmp_path, fake_wp, monkeypatch):
    stored = []
    monkeypatch.setattr(wp, "store_points", lambda c, t, q, pts, m: stored.append(pts) or len(pts))
    llm = FakeRunner(BAD, GOOD)
    fake_wp(llm)
    jid = _job(db, "LLM_WATCHPOINTS", {"ticker": "NVDA"})
    main.run_one_cycle(db, str(tmp_path))
    with db.begin() as c:
        assert c.execute(text("SELECT status FROM jobs WHERE id = :i"), {"i": jid}).scalar() == "SUCCESS"
    assert len(llm.prompts) == 2 and len(stored) == 1
    assert not (tmp_path / "llm" / "escalations").exists()


def test_handler_cap_makes_one_call_and_no_packet(db, tmp_path, fake_wp):
    llm = FakeRunner(LlmError("cap", "오늘 상한"), GOOD)
    fake_wp(llm)
    jid = _job(db, "LLM_WATCHPOINTS", {"ticker": "NVDA"})
    main.run_one_cycle(db, str(tmp_path))
    with db.begin() as c:
        assert c.execute(text("SELECT status FROM jobs WHERE id = :i"), {"i": jid}).scalar() == "FAILED"
    assert len(llm.prompts) == 1 and not (tmp_path / "llm" / "escalations").exists()
