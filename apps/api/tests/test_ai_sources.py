"""AI Key Data v2 (S5) — 원천 파서·규칙 단위 테스트. **네트워크 없음**(작은 픽스처만)."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import delete, select

from app.core import ai_live, ai_snapshot_sync
from app.models import AiMetricSnapshot

from prices.ai_sources import epoch, npm, openrouter, pypi, ramp, tool_calling, vscode  # noqa: E402 (경로는 ai_live 가 연다)


# ── npm ──────────────────────────────────────────────────────────────────────

def test_npm_parse_range_skips_bad_days():
    got = npm.parse_range({"downloads": [{"day": "2026-09-01", "downloads": 5}, {"day": "bad", "downloads": 1}]})
    assert got == {date(2026, 9, 1): 5}


def test_npm_zero_cutoff_drops_roster_wide_zero_tail_but_keeps_individual_zero():
    d = [date(2026, 9, i) for i in range(20, 28)]
    series = {
        "a": {d[0]: 10, d[1]: 0, d[2]: 7, d[3]: 0, d[4]: 0},
        "b": {d[0]: 3, d[1]: 4, d[2]: 0, d[3]: 0, d[4]: 0},
    }
    trimmed, cutoff = npm.apply_cutoff(series)
    assert cutoff == d[2]
    assert trimmed["a"] == {d[0]: 10, d[1]: 0, d[2]: 7}  # 개별 0(d1)은 진짜 0 — 남는다
    assert trimmed["b"] == {d[0]: 3, d[1]: 4, d[2]: 0}


def test_npm_zero_cutoff_all_zero_is_none():
    trimmed, cutoff = npm.apply_cutoff({"a": {date(2026, 1, 1): 0}})
    assert cutoff is None and trimmed == {"a": {}}


# ── Ramp ─────────────────────────────────────────────────────────────────────

def _flight(payload: str) -> str:
    """Next.js flight 조각처럼 — 두 push 로 쪼개고 따옴표를 이스케이프한다."""
    half = len(payload) // 2
    parts = [payload[:half], payload[half:]]
    return "".join(f"<script>self.__next_f.push([1,{json.dumps(p)}])</script>" for p in parts)


RAMP_JSON = (
    '5:["$","div",null,{"data":{"adoptionOverall":[{"date_month":"2026-07-01","adoption_rate_pct":55.71,'
    '"mom_change_pp":0.3,"yoy_change_pp":10.1},{"date_month":"2026-08-01","adoption_rate_pct":56.13,'
    '"mom_change_pp":0.42,"yoy_change_pp":11.15}],"adoptionVendor":[{"date_month":"2026-08-01","vendor":"OpenAI",'
    '"adoption_rate_pct":35.2,"mom_change_pp":0.1},{"date_month":"2026-07-01","vendor":"OpenAI","adoption_rate_pct":35.1,'
    '"mom_change_pp":0},{"date_month":"2026-08-01","vendor":"Anthropic","adoption_rate_pct":12.4,"mom_change_pp":1.1}]}}]'
)


def test_ramp_extracts_arrays_split_across_flight_chunks():
    html = "<html><body>" + _flight(RAMP_JSON) + "</body></html>"
    got = ramp.parse(html)
    assert got["overall"] == [(date(2026, 7, 1), 55.71), (date(2026, 8, 1), 56.13)]
    assert got["vendors"]["OpenAI"] == [(date(2026, 7, 1), 35.1), (date(2026, 8, 1), 35.2)]
    assert got["latest"] == date(2026, 8, 1)


def test_ramp_structure_change_raises():
    with pytest.raises(ValueError):
        ramp.parse("<html>" + _flight('{"somethingElse":[]}') + "</html>")


# ── OpenRouter / tool_calling ────────────────────────────────────────────────

def test_openrouter_last_complete_day_is_utc_yesterday():
    now = datetime(2026, 9, 27, 0, 30, tzinfo=timezone.utc)
    assert openrouter.last_complete_day(now) == date(2026, 9, 26)


def test_openrouter_chunks_clamp_floor_and_90_days():
    got = openrouter.chunks(date(2024, 6, 1), date(2025, 7, 1))
    assert got[0][0] == date(2025, 1, 1)
    assert all((hi - lo).days <= 89 for lo, hi in got)
    assert got[-1][1] == date(2025, 7, 1)
    assert all(got[i][1].toordinal() + 1 == got[i + 1][0].toordinal() for i in range(len(got) - 1))


def test_openrouter_parse_string_tokens_and_meta():
    rows, meta = openrouter.parse({
        "data": [{"date": "2026-05-11", "model_permaslug": "openai/gpt-4o", "total_tokens": "12345678"},
                 {"date": "2026-05-11", "model_permaslug": "other", "total_tokens": "42"}],
        "meta": {"as_of": "2026-05-12T02:00:00Z"},
    })
    assert rows == [(date(2026, 5, 11), "openai/gpt-4o", 12345678), (date(2026, 5, 11), "other", 42)]
    assert meta["as_of"] == "2026-05-12T02:00:00Z"


def test_openrouter_key_missing_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("키 없이 호출하면 안 된다")

    monkeypatch.setattr(openrouter.httpx, "Client", boom)
    assert openrouter.fetch(None)["status"] == "key_missing"
    assert tool_calling.fetch("")["status"] == "key_missing"


def test_tool_calling_uses_total_dates_and_fills_zero():
    d1, d2, d3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    total = [(d1, "m", 100), (d1, "other", 10), (d2, "m", 50)]
    tool = [(d1, "m", 90), (d3, "m", 5)]  # d2 없음 → 0, d3 은 전체에 없음 → 버림
    assert tool_calling.merge(total, tool) == [(d1, 110, 90), (d2, 50, 0)]


def test_openrouter_series_top_rest_other_no_zero_fill():
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    rows = [(d1, "a", 100), (d1, "b", 10), (d1, "other", 5), (d2, "a", 90), (d2, "other", 4)]
    series, last = ai_live.openrouter_series(rows, top=1)
    by = {s["key"]: s for s in series}
    assert last == d2
    assert by["total"]["points"] == [("2026-09-01", 115.0), ("2026-09-02", 94.0)]
    assert by["a"]["points"] == [("2026-09-01", 100.0), ("2026-09-02", 90.0)]
    assert by["rest"]["points"] == [("2026-09-01", 10.0)]  # d2 에 b 없음 → 점 없음(0 아님)
    assert by["other"]["group"] == "residual"


# ── VS Code ──────────────────────────────────────────────────────────────────

def test_vscode_query_shape():
    q = vscode.build_query(["GitHub.copilot-chat", "anthropic.claude-code"])
    assert q["flags"] == 914
    assert [c["filterType"] for c in q["filters"][0]["criteria"]] == [7, 7]


def test_vscode_parse_and_canonical_case():
    payload = {"results": [{"extensions": [{
        "publisher": {"publisherName": "github"}, "extensionName": "copilot-chat",
        "lastUpdated": "2026-05-15T22:33:59Z", "versions": [{"version": "0.48.1"}],
        "statistics": [{"statisticName": "install", "value": 78481263.0},
                       {"statisticName": "updateCount", "value": 652911889.0},
                       {"statisticName": "averagerating", "value": 2.8}],
    }, {"publisher": {"publisherName": "x"}, "extensionName": "nostats", "statistics": []}]}]}
    rows = vscode.canonical(vscode.parse(payload), ["GitHub.copilot-chat"])
    assert len(rows) == 1
    assert rows[0]["extension"] == "GitHub.copilot-chat"
    assert rows[0]["install"] == 78481263 and rows[0]["version"] == "0.48.1"


# ── PyPI ─────────────────────────────────────────────────────────────────────

def test_pypi_429_three_times_skips_not_fails(monkeypatch):
    calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        pkg = request.url.path.split("/")[3]
        calls[pkg] = calls.get(pkg, 0) + 1
        if pkg == "busy":
            return httpx.Response(429)
        return httpx.Response(200, json={"data": {"last_day": 1, "last_week": 7, "last_month": 30}})

    real = httpx.Client
    monkeypatch.setattr(pypi.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    got = pypi.fetch(["anthropic", "busy"], sleep=lambda s: None)
    assert got["rows"] == {"anthropic": {"last_day": 1, "last_week": 7, "last_month": 30}}
    assert got["skipped"] == ["busy"] and got["failed"] == []
    assert calls["busy"] == 4  # 최초 1 + 재시도 3


# ── Epoch ────────────────────────────────────────────────────────────────────

def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def test_epoch_extract_members_in_memory_with_multiline_cells():
    content = _zip({
        "README.md": "x",
        "timelines_by_chip.csv": (
            "Name,Chip manufacturer,Start date,Incomplete,Compute estimate in H100e (median),Notes\r\n"
            "Q1 - A,Nvidia,2022-01-01,,100,\"line1\nline2\"\r\n"
            "Q2 - A,Nvidia,2022-04-01,,50,\r\n"
            "Q2 - T,Google,2022-04-01,True,20,\r\n"
        ),
        "extra.csv": "a\n1\n",
    })
    got = epoch.extract_members(content, ["timelines_by_chip.csv"])
    rows = got["timelines_by_chip.csv"]
    assert list(got) == ["timelines_by_chip.csv"]
    assert len(rows) == 3 and rows[0]["Notes"] == "line1\nline2"

    chips = epoch.chip_h100e_cumulative(rows)
    assert chips["quarters"] == [date(2022, 1, 1), date(2022, 4, 1)]
    assert chips["by_maker"]["Nvidia"] == [100.0, 150.0]
    assert chips["by_maker"]["Google"] == [0.0, 20.0]  # 보고 없는 분기 = 출하 0
    assert chips["total"] == [100.0, 170.0]
    assert chips["incomplete"] == [date(2022, 4, 1)]


def test_epoch_missing_member_and_shrink_floor():
    with pytest.raises(ValueError):
        epoch.extract_members(_zip({"a.csv": "x\n1\n"}), ["b.csv"])
    assert epoch.shrunk({"m.csv": 100}, {"m.csv": 49}) == ["m.csv"]
    assert epoch.shrunk({"m.csv": 100}, {"m.csv": 50}) == []
    assert epoch.shrunk({}, {"m.csv": 1}) == []


def test_epoch_tables():
    dcs = epoch.top_data_centers([
        {"Name": "A", "Owner": "X #confident", "Current power (MW)": "10"},
        {"Name": "B", "Owner": "Y", "Current power (MW)": "900"},
        {"Name": "C", "Current power (MW)": ""},
    ], n=5)
    assert [d["name"] for d in dcs] == ["B", "A"] and dcs[1]["owner"] == "X"
    labs = epoch.lab_revenue_steps([
        {"Company": "O", "Date": "2026-01-01", "Annualized revenue (USD)": "2e10", "Scope": "Full company"},
        {"Company": "O", "Date": "2025-01-01", "Annualized revenue (USD)": "1e10", "Scope": "Full company"},
        {"Company": "O", "Date": "2025-06-01", "Annualized revenue (USD)": "5e9", "Scope": "Product/division"},
    ])
    assert labs == {"O": [(date(2025, 1, 1), 1e10), (date(2026, 1, 1), 2e10)]}


# ── 라이브 캐시: 실패 시 last-good ────────────────────────────────────────────

def test_live_cache_falls_back_to_last_good(monkeypatch):
    monkeypatch.setattr(ai_live, "_record", lambda *a, **k: None)
    monkeypatch.setitem(ai_live._slots, "ramp", ai_live._Slot())
    good = {"series": [{"key": "all", "label": "x", "points": [("2026-08-01", 1.0)]}], "latest_date": "2026-08-01"}
    monkeypatch.setitem(ai_live._BUILDERS, "ramp", lambda slot: dict(good))
    assert ai_live.get("ramp")["status"] == "ok"

    def fail(slot):
        raise RuntimeError("구조 변경")

    monkeypatch.setitem(ai_live._BUILDERS, "ramp", fail)
    stale = ai_live.get("ramp", refresh=True)
    assert stale["status"] == "stale" and stale["series"][0]["key"] == "all"
    assert "구조 변경" in stale["note"]


def test_status_cold_slot_in_flight_is_fetching_not_degraded(db, monkeypatch):
    """콜드 API: tool_calling 첫 조회가 도는 동안 상태 띠가 '미확인'(unknown)으로 보이면 안 된다."""
    monkeypatch.setattr(ai_live.settings, "OPENROUTER_API_KEY", "k")
    slot = ai_live._Slot()
    monkeypatch.setitem(ai_live._slots, "tool_calling", slot)
    by = lambda: {i["source"]: i for i in ai_live.status(db)}  # noqa: E731
    assert by()["tool_calling"]["status"] == "unknown"  # 아무도 안 물었다
    with slot.lock:  # get() 이 원천을 받는 중
        item = by()["tool_calling"]
        assert item["status"] == "fetching" and not item["ok"]
    slot.error = "ReadTimeout"
    with slot.lock:  # 실패 뒤 재시도 중이면 오류가 우선
        assert by()["tool_calling"]["status"] == "error"


# ── 스냅샷 업서트 멱등 ───────────────────────────────────────────────────────

def test_snapshot_upsert_is_idempotent(db):
    db.execute(delete(AiMetricSnapshot))
    db.commit()
    day = date(2026, 9, 27)
    rows = ai_snapshot_sync.vscode_rows(
        [{"extension": "anthropic.claude-code", "install": 100, "version": "1"}], day
    )
    ai_snapshot_sync.upsert(db, "vscode", rows)
    ai_snapshot_sync.upsert(db, "vscode", rows)
    again = ai_snapshot_sync.vscode_rows([{"extension": "anthropic.claude-code", "install": 95, "version": "2"}], day)
    ai_snapshot_sync.upsert(db, "vscode", again)  # 같은 날 재실행 = 덮어쓰기, 음수 델타도 원값
    got = db.execute(select(AiMetricSnapshot)).scalars().all()
    assert len(got) == 1
    assert int(got[0].value) == 95 and got[0].extra["version"] == "2"
    assert ai_snapshot_sync.has_snapshot(db, "vscode", day)
    db.execute(delete(AiMetricSnapshot))
    db.commit()


def test_snapshot_payload_delta_keeps_negative(db):
    db.execute(delete(AiMetricSnapshot))
    db.commit()
    ai_snapshot_sync.upsert(db, "vscode", [
        ("anthropic.claude-code", date(2026, 9, 1), 100, None),
        ("anthropic.claude-code", date(2026, 9, 2), 90, None),
    ])
    out = ai_live.snapshot_payload(db, "vscode")
    by = {s["key"]: s for s in out["series"]}
    assert by["anthropic.claude-code:delta"]["points"] == [("2026-09-02", -10.0)]
    assert out["latest_date"] == "2026-09-02" and out["status"] == "ok"
    db.execute(delete(AiMetricSnapshot))
    db.commit()


def test_ai_routes_status_and_bad_source(client):
    assert client.get("/api/v1/market/ai/bogus").status_code == 422
    r = client.get("/api/v1/market/ai/status")
    assert r.status_code == 200
    assert {i["source"] for i in r.json()["items"]} == set(ai_live.SOURCES)
