"""AI Key Data 판독 3종 회귀 테스트 — 순수 계산부.

파일 판독(`_read_rows` / `read_zip_tables`)은 겨누지 않는다(마운트 의존) — 합성 표를
`build_*_payload` 에 넣는다. 예외는 §미래날짜 핀 두 건으로, 원천 zip 이 있을 때만 돈다.

겨누는 것:
  1) ★미래 날짜 컷 — `asof` 를 안 넘기면 IT 전력이 2.7배가 된다(이 데이터셋 최대 위험)
  2) 토큰: 모델별 결측은 `null` 이지 `0` 이 아니다 / ma7 앞 6일 null / 부분주 플래그
  3) VS Code: 스톡이지 플로우가 아니다 / 1일치면 delta 빈 배열 + note /
     음수 델타 clip 금지 / 수집 구멍은 **영구 손실**이라 반드시 드러난다
  4) 칩: 분기 결측은 `0` 이다(토큰과 의도적으로 반대) / 공통 기산점 재누적 / 부분 분기
  5) ARR: `Revenue amount (normalize to annual)` 을 읽는가 / Scope 필터 / (회사,날짜) 중복
  6) fail-soft: 빈 입력 → 빈 payload, 예외 없음
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import ai_key_data_io as _io  # noqa: E402
from collector import ai_token_usage as tu  # noqa: E402
from collector import epoch_datasets as ed  # noqa: E402
from collector import npm_downloads as npm  # noqa: E402
from collector import vscode_installs as vsc  # noqa: E402


def _table(cols: list[str], rows: list[list]) -> _io.Table:
    return _io.Table(cols, [dict(zip(cols, r)) for r in rows])


TL_COLS = [
    "Data center", "Date", "IT power (MW)", "Power (MW)",
    "H100 equivalents", "Total capital cost (2025 USD billions)",
]


# ── 1. 미래 날짜 컷 ─────────────────────────────────────────────────────────

def test_future_rows_inflate_power_when_asof_is_not_applied():
    """미래 관측이 섞이면 '계획'이 '현재'로 발표된다 — 이 카드 최대의 조용한 오류."""
    tl = _table(TL_COLS, [
        ["A", "2025-01-01", "100", "130", "1000", "3.0"],
        ["A", "2030-01-01", "500", "650", "9000", "30.0"],   # ⚠️미래 계획
        ["B", "2026-01-01", "50", "62", "400", "1.0"],
    ])
    cut = ed.build_datacenters_payload(None, tl, asof=date(2026, 8, 28))
    assert cut["totals"]["it_power_mw"] == pytest.approx(150.0)
    # 계획 총량은 **다른 필드로** 나간다 — 같은 자리에 렌더하면 안 된다.
    assert cut["totals"]["planned_it_power_mw"] == pytest.approx(550.0)

    raw = ed.build_datacenters_payload(None, tl, asof=None)
    assert raw["totals"]["it_power_mw"] == pytest.approx(550.0)


def test_it_power_is_not_total_facility_power():
    """`Power (MW)` 는 PUE 를 먹인 총 시설전력이라 KPI 로 쓰면 차트 끝점과 어긋난다."""
    tl = _table(TL_COLS, [["A", "2026-01-01", "100", "130", "1000", "3.0"]])
    out = ed.build_datacenters_payload(None, tl, asof=date(2026, 8, 28))
    assert out["totals"]["it_power_mw"] == pytest.approx(100.0)
    assert out["totals"]["total_power_mw"] == pytest.approx(130.0)
    assert out["units"]["power"] == "MW (IT)"


def test_buildout_curve_is_asof_per_quarter():
    tl = _table(TL_COLS, [
        ["A", "2025-02-01", "100", "0", "0", "0"],
        ["A", "2025-08-01", "300", "0", "0", "0"],
    ])
    out = ed.build_datacenters_payload(None, tl, asof=date(2025, 12, 31))
    curve = {r["date"]: r["it_power_mw"] for r in out["buildout"]}
    assert curve["2025-03-31"] == pytest.approx(100.0)
    assert curve["2025-06-30"] == pytest.approx(100.0)   # 새 관측 전엔 직전 값이 유지된다
    assert curve["2025-09-30"] == pytest.approx(300.0)


@pytest.mark.skipif(
    not os.path.exists(ed.member_path(ed.M_DC_TIMELINES)),
    reason="epoch CSV 마운트 없음",
)
def test_real_csv_pins_measured_power_totals():
    """★2026-08-31 스냅샷 실측 핀.

    Epoch 스냅샷이 갱신되면 이 숫자는 바뀐다. 바뀌면 새 값으로 갱신하되 **두 값의 비(2.7배)가
    유지되는지 먼저 확인해라** — 비가 1에 가까워졌다면 미래행 필터가 죽은 것이다.
    """
    tl = _io.read_flat_csv_dicts(ed.member_path(ed.M_DC_TIMELINES))
    dc = _io.read_flat_csv_dicts(ed.member_path(ed.M_DATA_CENTERS))

    out = ed.build_datacenters_payload(dc, tl, asof=date(2026, 8, 28))
    assert out["totals"]["it_power_mw"] == pytest.approx(13257.12971, rel=1e-9)
    assert out["totals"]["planned_it_power_mw"] == pytest.approx(35676.12971, rel=1e-9)

    # 마스터의 'Current power (MW)' 합과 과거 asof 합이 일치한다(86/86). 이 항등이
    # 깨지면 KPI 와 차트 끝점이 갈라진 것이다.
    master = sum(_io.to_num(r["Current power (MW)"]) or 0 for r in dc.rows)
    assert out["totals"]["it_power_mw"] == pytest.approx(master, rel=1e-9)

    raw = ed.build_datacenters_payload(dc, tl, asof=None)
    assert raw["totals"]["it_power_mw"] == pytest.approx(35676.12971, rel=1e-9)


# ── 2. 토큰 사용량 ──────────────────────────────────────────────────────────

def _tokens(days: int = 10) -> list[tuple[date, str, int]]:
    rows = []
    for i in range(days):
        d = date(2026, 1, 1) + __import__("datetime").timedelta(days=i)
        rows.append((d, "openai/gpt-x", 100))
        rows.append((d, "other", 10))
        if i != 3:                      # ⚠️4일차에 이 모델이 top-50 밖으로 밀렸다
            rows.append((d, "deepseek/v4", 50))
    return rows


def test_model_gap_is_null_not_zero():
    """top-50 이탈은 '사용 중단'이 아니라 '관측 창 밖'이다 — 0으로 채우면 비가역 손실."""
    out = tu.build_payload(_tokens(), asof=date(2026, 1, 10))
    series = {m["slug"]: m for m in out["models"]}
    pts = dict(series["deepseek/v4"]["points"])
    assert pts["2026-01-04"] is None
    assert pts["2026-01-05"] == 50
    assert 0 not in [v for v in pts.values() if v is not None]


def test_ma7_leaves_first_six_days_null():
    out = tu.build_payload(_tokens(), asof=date(2026, 1, 10))
    ma = [v for _, v in out["totals"]["daily_ma7"]]
    assert ma[:6] == [None] * 6
    assert ma[6] is not None
    assert len(ma) == len(out["totals"]["daily"])


def test_missing_days_are_dropped_not_zero_filled():
    """상류 공백에 0을 끼워 넣으면 가짜 급락이 생긴다 — 빼고 `missing_dates` 로만 알린다."""
    rows = [(date(2026, 1, d), "other", 10) for d in (1, 2, 4, 5)]
    out = tu.build_payload(rows, asof=date(2026, 1, 5))
    assert [d for d, _ in out["totals"]["daily"]] == [
        "2026-01-01", "2026-01-02", "2026-01-04", "2026-01-05"
    ]
    assert out["missing_dates"] == ["2026-01-03"]


def test_partial_week_bucket_is_flagged():
    """마지막 주가 4일치면 '감소 전환'으로 오독된다 — 화면이 점선 처리할 근거를 준다."""
    # 2026-01-05 는 월요일이라 그 주는 01-11(일)에 끝난다.
    rows = [(date(2026, 1, d), "other", 10) for d in (5, 6, 7, 8)]
    out = tu.build_payload(rows, asof=date(2026, 1, 8))
    assert out["totals"]["weekly"] == [["2026-01-11", 40]]
    assert out["incomplete_buckets"] == ["2026-01-11"]


def test_coverage_is_declared_and_other_is_not_a_model():
    out = tu.build_payload(_tokens(), asof=date(2026, 1, 10))
    assert out["coverage"] == "top50_plus_other"
    assert "other" not in [m["slug"] for m in out["models"]]
    assert "other" in [v["name"] for v in out["vendors"]]   # 벤더 축에는 남는다
    # ⚠️일별 비중의 평균이지 '합계의 비중'이 아니다. 모델이 빠진 날(4일차)은 그날 총합이
    #   작아져 other 비중이 커진다 — 9일 × 10/160 + 1일 × 10/110.
    assert out["other_share_pct"] == pytest.approx(
        (9 * (10 / 160) + (10 / 110)) / 10 * 100, rel=1e-3
    )


def test_token_empty_input_is_soft():
    out = tu.build_payload([])
    assert out["totals"]["daily"] == []
    assert out["asof"] is None
    assert out["source"] is None


# ── 3. npm ──────────────────────────────────────────────────────────────────

def test_npm_ranks_by_recent_window_and_smooths():
    import datetime as _dt
    rows = []
    for i in range(10):
        d = date(2026, 1, 1) + _dt.timedelta(days=i)
        rows.append((d, "@openai/codex", 100))
        rows.append((d, "@anthropic-ai/claude-code", 300))
    out = npm.build_payload(rows, asof=date(2026, 1, 10))
    assert [p["name"] for p in out["packages"]] == [
        "@anthropic-ai/claude-code", "@openai/codex"
    ]
    ma = [v for _, v in out["packages"][0]["ma7"]]
    assert ma[:6] == [None] * 6
    assert ma[6] == pytest.approx(300.0)
    assert out["totals"]["daily"][-1] == ["2026-01-10", 400]


def test_npm_empty_input_is_soft():
    out = npm.build_payload([])
    assert out["packages"] == []
    assert out["note"] is None       # note 는 IO 층이 사유를 알고 붙인다


# ── 3b. VS Code 설치수 (누적 스톡) ──────────────────────────────────────────

def _vsc(day: int, ext: str, install: int, utc: str | None = None) -> dict:
    return {
        "date": date(2026, 8, day), "extension": ext, "install": install,
        "snapshot_utc": utc or f"2026-08-{day:02d}T07:24:37Z",
        "update_count": None, "download_count": None, "version": "1.0",
        "last_updated": "2026-08-01", "avg_rating": 3.7, "rating_count": 10,
    }


def test_single_snapshot_yields_stock_but_no_delta():
    """★1일치면 delta 가 **빈 배열 + note** 다 — 0을 만들면 없는 관측이 생긴다."""
    out = vsc.build_payload([_vsc(28, "anthropic.claude-code", 24193183)],
                            asof=date(2026, 8, 28))
    e = out["extensions"][0]
    assert out["measure"] == "stock"
    assert e["stock"] == [["2026-08-28", 24193183]]
    assert e["delta"] == [] and e["delta_marks"] == []
    assert e["stats"]["delta_last"] is None
    assert out["n_snapshots"] == 1
    assert "스냅샷이 1일치뿐" in out["note"]
    # 카드가 비지 않는다 — 누적값과 스냅샷 시각은 그대로 나간다.
    assert e["install"] == 24193183
    assert e["snapshot_utc"] == "2026-08-28T07:24:37Z"


def test_delta_appears_once_a_second_snapshot_lands():
    out = vsc.build_payload(
        [_vsc(28, "anthropic.claude-code", 100), _vsc(29, "anthropic.claude-code", 130)],
        asof=date(2026, 8, 29),
    )
    e = out["extensions"][0]
    assert e["delta"] == [["2026-08-29", 30]]
    assert e["delta_marks"] == [{"negative": False, "span_days": 1, "from": "2026-08-28"}]
    assert out["note"] is None
    assert out["totals"]["delta"] == [["2026-08-29", 30]]


def test_negative_delta_is_kept_not_clipped():
    """★MS 소급 정정으로 누적값이 줄 수 있다. 0으로 자르면 비가역 손실이고,
    '소급 정정했다'는 사실 자체가 관측 대상이다."""
    out = vsc.build_payload(
        [_vsc(28, "openai.chatgpt", 500), _vsc(29, "openai.chatgpt", 480)],
        asof=date(2026, 8, 29),
    )
    e = out["extensions"][0]
    assert e["delta"] == [["2026-08-29", -20]]          # clip 되지 않았다
    assert e["delta_marks"][0]["negative"] is True
    assert e["stats"]["negative_days"] == 1
    assert out["revisions"] == [{
        "extension": "openai.chatgpt", "date": "2026-08-29",
        "delta": -20, "from": 500, "to": 480,
    }]


def test_collection_gap_is_reported_and_span_is_marked():
    """★수집이 멈춘 날은 **영영 못 채운다** — 조용히 지나가면 안 된다.
    구멍을 건너뛴 델타는 하루치가 아니므로 `span_days` 로 구분한다."""
    out = vsc.build_payload(
        [_vsc(26, "anthropic.claude-code", 100), _vsc(28, "anthropic.claude-code", 160)],
        asof=date(2026, 8, 28),
    )
    assert out["gaps"] == ["2026-08-27"]
    assert out["extensions"][0]["delta_marks"][0]["span_days"] == 2
    assert [s["utc"] for s in out["snapshots"]] == [
        "2026-08-26T07:24:37Z", "2026-08-28T07:24:37Z"
    ]


def test_vscode_source_is_the_only_irrecoverable_one():
    src = _io.source_block("vscode", "/nonexistent/x.csv", "vscode", date(2026, 8, 28))
    assert src["irrecoverable"] is True
    for other in ("npm", "openrouter", "ai_companies", "ai_chip_sales", "data_centers"):
        assert _io.source_block(other, "/nonexistent/x.csv", None,
                                date(2026, 8, 28))["irrecoverable"] is False


def test_vscode_empty_input_is_soft():
    out = vsc.build_payload([])
    assert out["extensions"] == [] and out["snapshots"] == []
    assert out["asof"] is None


# ── 4. 칩 출하 ──────────────────────────────────────────────────────────────

CHIP_COLS = [
    "Chip manufacturer", "End date", "Chip type", "Chip type (linked)",
    "Number of Units", "Compute estimate in H100e (median)", "Incomplete",
]


def test_chip_quarters_zero_fill_and_common_anchor_cumsum():
    """★칩 카드의 결측 분기는 `0` 이다 — 토큰 카드가 `null` 인 것과 의도적으로 반대다.

    여기서 결측은 '그 분기 출하 보고 없음'이라 0이 옳고, 화면이 선을 끊으면
    '출하가 멈춘 게 아니라 갱신이 안 된 것'을 표현할 수 없다.
    """
    t = _table(CHIP_COLS, [
        ["Nvidia", "2025-03-31", "H100", "H100", "10", "100", ""],
        ["Nvidia", "2025-09-30", "B200", "B200", "20", "300", ""],
        ["AMD", "2025-09-30", "MI300X", "Instinct MI300X", "5", "50", ""],
    ])
    out = ed.build_chips_payload(t, None, asof=date(2026, 8, 28))
    assert out["quarters"] == ["2025-03-31", "2025-09-30"]
    nv = next(d for d in out["designers"] if d["name"] == "Nvidia")
    amd = next(d for d in out["designers"] if d["name"] == "AMD")
    assert nv["flow"] == [100.0, 300.0]
    assert nv["cum"] == [100.0, 400.0]
    # AMD 는 첫 분기에 데이터가 없다 → null 이 아니라 0, 그리고 누적이 같은 기산점에서 시작한다.
    assert amd["flow"] == [0.0, 50.0]
    assert amd["cum"] == [0.0, 50.0]
    assert out["totals"]["cum_h100e"] == pytest.approx(450.0)


def test_incomplete_quarter_is_flagged_and_excluded_from_flow_last():
    t = _table(CHIP_COLS, [
        ["Nvidia", "2026-03-31", "B200", "B200", "10", "100", ""],
        ["Nvidia", "2026-06-30", "B300", "B300", "2", "20", "True"],   # 부분 분기
    ])
    out = ed.build_chips_payload(t, None, asof=date(2026, 8, 28))
    assert out["incomplete_quarters"] == ["2026-06-30"]
    nv = out["designers"][0]
    assert nv["stats"]["flow_last_quarter"] == "2026-03-31"
    assert nv["stats"]["flow_last"] == pytest.approx(100.0)
    assert nv["stats"]["cum_last"] == pytest.approx(120.0)   # 누적에는 그대로 들어간다
    assert out["chips_quarter"] == "2026-03-31"


def test_in_progress_quarter_is_kept_but_future_quarter_is_cut():
    """★분기 라벨이 분기말이라 `End date <= asof` 로 자르면 **진행 중 분기가 사라진다**.

    데이터센터 카드의 미래행 컷과 뜻이 다르다 — 저긴 2030년 계획이고 여긴 이번 분기의
    부분 관측이다. 부분 관측은 버리는 게 아니라 `Incomplete` 로 표시한다.
    """
    t = _table(CHIP_COLS, [
        ["Nvidia", "2026-06-30", "B300", "B300", "10", "100", ""],
        ["Nvidia", "2026-09-30", "B300", "B300", "5", "50", "True"],    # 진행 중 분기
        ["Nvidia", "2027-03-31", "Rubin", "Rubin", "99", "999", ""],    # 진짜 미래
    ])
    out = ed.build_chips_payload(t, None, asof=date(2026, 8, 28))
    assert out["quarters"] == ["2026-06-30", "2026-09-30"]
    assert out["incomplete_quarters"] == ["2026-09-30"]
    assert out["totals"]["cum_h100e"] == pytest.approx(150.0)


def test_chip_join_uses_linked_name_but_displays_raw_name():
    """`Chip type` 과 `Chip type (linked)` 는 51행에서 값이 다르다."""
    t = _table(CHIP_COLS, [
        ["AMD", "2025-09-30", "MI300X", "Instinct MI300X", "5", "50", ""],
    ])
    ct = _table(["Name", "Designer", "H100e", "Release date"], [
        ["Instinct MI300X", "AMD", "0.8", "2023-12-06"],
    ])
    out = ed.build_chips_payload(t, ct, asof=date(2026, 8, 28))
    chip = out["chips"][0]
    assert chip["chip"] == "MI300X"                  # 표시는 사람이 읽는 이름
    assert chip["h100e_per_chip"] == pytest.approx(0.8)   # 조인은 linked 로 성공했다
    assert chip["release_date"] == "2023-12-06"


# ── 5. ARR ──────────────────────────────────────────────────────────────────

REV_COLS = [
    "Company", "Date", "Annualized revenue (USD)",
    "Revenue amount (normalize to annual)", "Scope", "Period type",
    "Annualized revenue type", "Confidence", "Graph note",
]


def test_arr_reads_normalized_column_not_annualized():
    """★`Annualized revenue (USD)` 를 쓰면 `Period type=Year` 행이 조용히 사라진다."""
    t = _table(REV_COLS, [
        ["OpenAI", "2024-12-31", "", "3700000000", "Full company", "Year", "", "", ""],
        ["OpenAI", "2026-08-13", "40000000000", "40000000000", "Full company",
         "Annualized", "Annualized run rate", "Likely", "\"More than 40B\""],
    ])
    out = ed.build_companies_payload(t, None, asof=date(2026, 8, 28))
    oai = out["revenue"]["series"][0]
    assert oai["points"] == [
        ["2024-12-31", 3700000000.0], ["2026-08-13", 40000000000.0]
    ]
    assert out["revenue"]["kind"] == "step"     # 연속선이 아니다
    assert oai["marks"][1]["confidence"] == "Likely"
    assert oai["stats"]["stale_days"] == 15


def test_arr_filters_scope_and_dedupes_company_date():
    t = _table(REV_COLS, [
        ["OpenAI", "2025-01-01", "", "1000", "Product/division", "", "", "", ""],
        ["OpenAI", "2025-06-01", "", "2000", "Full company", "", "", "", ""],
        ["OpenAI", "2025-06-01", "", "2500", "Full company", "", "", "", ""],
    ])
    out = ed.build_companies_payload(t, None, asof=date(2026, 8, 28))
    assert out["revenue"]["series"][0]["points"] == [["2025-06-01", 2500.0]]


def test_same_date_arr_beats_full_year_revenue():
    """★같은 날짜에 뜻이 다른 두 행이 있다(OpenAI 2024-12-31 실측).

    `Period type=Year` 는 그 해 연간 실적이고 ARR 행은 그 시점 런레이트다. 축이 다르므로
    ARR 축 카드에서는 후자를 고른다 — 뒷 행을 그냥 채택하면 **없는 하락**이 그려진다.
    """
    t = _table(REV_COLS, [
        ["OpenAI", "2024-12-31", "5500000000", "5500000000", "Full company", "",
         "Annual recurring revenue (ARR)", "Likely", ""],
        ["OpenAI", "2024-12-31", "", "3700000000", "Full company", "Year", "", "Likely", ""],
    ])
    out = ed.build_companies_payload(t, None, asof=date(2026, 8, 28))
    assert out["revenue"]["series"][0]["points"] == [["2024-12-31", 5500000000.0]]


def test_arr_series_order_follows_companies_constant():
    t = _table(REV_COLS, [
        ["xAI", "2025-01-01", "", "400", "Full company", "", "", "", ""],
        ["OpenAI", "2025-01-01", "", "1000", "Full company", "", "", "", ""],
    ])
    out = ed.build_companies_payload(t, None, asof=date(2026, 8, 28))
    assert [s["name"] for s in out["revenue"]["series"]] == ["OpenAI", "xAI"]


def test_group_isolation_revenue_break_does_not_kill_funding():
    """★revenue 가 스키마 변경으로 깨져도 funding 은 나가야 한다."""
    broken = _table(["Company", "Date"], [["OpenAI", "2025-01-01"]])
    funding = _table(
        ["Company", "Close date", "Funding (equity)", "Exclude from graph view"],
        [["OpenAI", "2025-03-01", "6600000000", ""]],
    )
    out = ed.build_companies_payload(broken, funding, asof=date(2026, 8, 28))
    assert out["revenue"]["series"] == []
    assert "필수 컬럼 결측" in out["revenue"]["note"]
    assert out["funding"]["rounds"][0]["equity"] == pytest.approx(6.6e9)
    assert out["funding"]["note"] is None


# ── 6. 공용 판독층 ──────────────────────────────────────────────────────────

def test_strip_confidence_tag():
    assert _io.strip_tag("Google #confident") == ("Google", "confident")
    assert _io.strip_tag("") == (None, None)


def test_moving_average_head_is_null_and_nulls_propagate():
    assert _io.moving_average([1, 2, 3], 3) == [None, None, 2.0]
    assert _io.moving_average([1, None, 3], 3) == [None, None, None]


def test_fetch_status_absence_is_not_an_error(monkeypatch):
    """ws3 배포 전에는 이 파일이 없다 — 없는 것이 정상 경로다."""
    monkeypatch.setattr(_io, "STATUS_PATH", "/nonexistent/_fetch_status.json")
    assert _io.fetch_status("npm") is None
    src = _io.source_block("npm", "/nonexistent/x.csv", "npm", date(2026, 8, 28))
    assert src["name"] == "npm registry"
    assert src["fetched_at"] is None and src["fetch_ok"] is None
    assert src["license"] is None      # ⚠️약관을 지어내지 않는다
