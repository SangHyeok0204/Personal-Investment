r"""[AI Key Data] Epoch AI 3종 데이터셋 판독 (2026-08-28).

데이터셋 세 벌 = 카드 세 장. `/epoch-companies`(AI Lab ARR) · `/epoch-chips`(분기 칩 출하) ·
`/epoch-datacenters`(데이터센터 빌드아웃).

★2026-08-31 원천 전환. 예전에는 `input\raw\*.zip` 을 풀지 않고 안에서 직독했다
  (`ai_key_data_io.read_zip_tables`). 이제는 **수집기가 zip 을 메모리에서 풀어 소비 대상
  CSV 6장만 `input\raw\epoch\` 에 놓고 zip 은 디스크에 남기지 않는다** — 여기서는 그
  평문 CSV 를 읽는다(`read_flat_csv`). 판독 위층(`build_*_payload`)은 `Table` 만 받으므로
  한 줄도 바뀌지 않았다. `read_zip_tables` 는 io 층에 그대로 남아 있다(다른 소비자 없음).

⚠️Epoch 3종은 **일별 시계열이 아니다.** ARR 은 3년에 수십 행짜리 뉴스 이벤트이고 칩 출하는
  분기, 데이터센터는 불규칙 시점 관측이다. 연속선으로 이으면 **없는 정밀도를 만든다** —
  그래서 payload 가 `kind`(step/bar/scatter)를 실어 연속·계단 판정을 서버가 소유한다.

★실측으로 확정한 함정 4건. 넷 다 "파싱은 성공하고 그럴듯한 숫자가 나오는" 종류라
  테스트가 없으면 안 잡힌다:

 1. **미래 날짜 (가장 큰 위험).** `data_center_timelines.csv` 486행 중 **78행이 2030년까지**
    앞서 있다. 안 자르면 IT 전력 합이 13,085 MW → **35,379 MW (2.70배)** 가 되어 카드가
    **계획을 현재로 발표한다.** → `asof` 를 순수계산 함수의 **인자로** 받고
    (`datetime.now()` 를 계산부 안에서 부르면 이 테스트를 못 쓴다) 두 숫자를 핀으로 박았다.
 2. **`Current power (MW)` 는 `IT power (MW)` 다, `Power (MW)` 가 아니다.**
    85개 DC 전부에서 전자는 85/85 일치, 후자는 18/85 뿐이다(`Power (MW)` 는 PUE 를 먹인
    총 시설전력). 섞으면 KPI 와 차트 끝점이 28% 어긋난다 → KPI·시계열 모두 `IT power` 로
    통일하고 총 시설전력은 `total_power_mw` 로 따로만 낸다.
 3. **ARR 은 `Revenue amount (normalize to annual)` 열이다**(59/65). `Annualized revenue
    (USD)`(53/65)를 쓰면 `Period type=Year` 로 들어온 행이 통째로 빠져 **OpenAI 5점 ·
    Anthropic 1점이 조용히 사라진다** — 하필 덱 차트의 주인공 둘이다.
 4. **`cumulative_timelines_by_designer.csv` 는 쓰지 않는다.** 이미 누적된 값인데 기산점이
    제조사마다 다르다(Nvidia 2022-01 / Google 2022-10 / 나머지 2024-01). 그대로 스택하면
    그래프는 그려지고 숫자도 나오지만 뜻이 없다. → `timelines_by_chip` 에서 공통 기산점으로
    직접 재누적한다. 재누적값이 Epoch 자체 값과 **-0.9%~+0.0%** 안에서 일치함을 확인했다.

★그룹 단위 격리: 한 엔드포인트가 여러 그룹을 내면 그룹마다 자기 `note` 를 갖는다 —
  revenue 가 스키마 변경으로 깨져도 funding 은 나가야 한다.

★값 보정 금지: 판독층은 단위 변환·필터·집계만 하고 값을 고치지 않는다. `Power (MW)` 가
  뒤로 감소하는 스텝이 2건 있으나(Colossus 1, Epoch 의 추정치 하향 정정) **단조성을
  강제하지 않는다.** 원본을 그대로 낸다.
"""
from __future__ import annotations

import os
from datetime import date

from collector import ai_key_data_io as _io

# 수집기 `agentetchers\epoch.py` 의 OUT_SUBDIR 과 같은 값이어야 한다.
SRC_EPOCH_DIR = os.environ.get("EPOCH_CSV_DIR", os.path.join(_io.RAW_DIR, "epoch"))


def member_path(name: str) -> str:
    return os.path.join(SRC_EPOCH_DIR, name)

M_REVENUE = "ai_companies_revenue_reports.csv"
M_FUNDING = "ai_companies_funding_rounds.csv"
M_TIMELINES_BY_CHIP = "timelines_by_chip.csv"
M_CHIP_TYPES = "chip_types.csv"
M_DATA_CENTERS = "data_centers.csv"
M_DC_TIMELINES = "data_center_timelines.csv"

# 정확히 소비하는 열. 하나라도 없으면 SchemaError → 그 그룹만 빈 채로 note 를 단다.
REQ_REVENUE = ("Company", "Date", "Revenue amount (normalize to annual)", "Scope")
REQ_FUNDING = ("Company", "Close date", "Funding (equity)")
REQ_TIMELINES_BY_CHIP = (
    "Chip manufacturer", "End date", "Chip type",
    "Number of Units", "Compute estimate in H100e (median)",
)
REQ_CHIP_TYPES = ("Name", "Designer", "H100e")
REQ_DATA_CENTERS = (
    "Name", "Current H100 equivalents", "Current power (MW)",
    "Current total capital cost (2025 USD billions)", "Country",
)
REQ_DC_TIMELINES = ("Data center", "Date", "IT power (MW)", "H100 equivalents")

# ── 관심 대상 (사람이 고치는 곳) ────────────────────────────────────────────
# `series` 순서 = 이 순서. 여기 없는 회사는 조용히 빠진다(compute_index.INDICES 와 같은 규칙).
# ★앞의 셋만 "살아 있다" — 나머지는 마지막 관측이 209~332일 전이라 같은 차트에 놓으면
#   "성장이 멈춘 회사"로 오독된다. 그래도 **지우지 않고** payload 의 `stats.stale_days` 로
#   내려보내 화면이 회색 처리하게 한다(판단은 화면 몫, 판독층은 사실만).
COMPANIES: list[str] = [
    "OpenAI", "Anthropic", "xAI",
    "Cohere", "Z.ai (Zhipu)", "Mistral AI", "Moonshot AI", "MiniMax", "DeepSeek",
]
REVENUE_SCOPE = "Full company"   # 나머지는 Product/division(5행) — 회사 합계와 섞으면 안 된다
TOP_CHIPS = 20                   # 분기 칩별 내역에 실을 행 수


def _group(fn, *args):
    """그룹 하나를 격리 판독. 스키마가 깨져도 다른 그룹은 그대로 나간다."""
    try:
        return fn(*args), None
    except _io.SchemaError as exc:
        return None, str(exc)


def _common(source: dict | None) -> dict:
    return {
        "generated_at": _io.generated_at(),
        "asof": None,
        "note": None,
        "source": source,
    }


# ══ 카드 A — AI Lab ARR ═════════════════════════════════════════════════════
# ── 순수 계산부 (파일 IO 없음 — 테스트는 여기를 겨눈다) ──────────────────────

def _revenue_group(table: _io.Table, asof: date | None) -> dict:
    """`ai_companies_revenue_reports.csv` → 회사별 ARR 스텝 계열.

    ⚠️연결이 아니라 **스텝**이다. ARR 은 "그 날짜에 그렇게 보고됐다"는 이벤트이지 연속
      계열이 아니라, 관측 사이를 직선으로 이으면 없던 중간값이 생긴다(policy_rate 와 같은 논리).
      점만 담고 계단으로 펴는 일은 화면이 한다.
    """
    _io.require(table, M_REVENUE, REQ_REVENUE)

    # ⚠️(회사, 날짜) 중복 1건 실측 — OpenAI 2024-12-31 에 **뜻이 다른 두 행**이 같이 있다:
    #     `Dec 2024 5.5B` → Annualized revenue type = ARR,      값 5.5B
    #     `2024 3.7B`     → Period type = Year(2024 연간 실적), 값 3.7B
    #   이건 축이 다른 관측이다. 이 카드는 **ARR 축**이므로 같은 날짜에 둘이 겹치면
    #   run-rate/ARR 행을 고른다. 뒷 행을 그냥 채택하면 4.0 → 3.7 → 10.0 이라는
    #   **없는 하락**이 그려진다(실제로 그렇게 나왔다).
    #   ★`Period type` 행 자체를 버리지는 않는다 — 경쟁 ARR 행이 없는 날짜(OpenAI 2022
    #     $28M 등 6행)에서는 그게 유일한 관측이고, 그 6행을 잃는 게 원래 함정이었다.
    seen: dict[tuple[str, date], tuple[int, dict]] = {}
    for r in table.rows:
        if (r.get("Scope") or "").strip() != REVENUE_SCOPE:
            continue
        d = _io.to_date(r.get("Date"))
        v = _io.to_num(r.get("Revenue amount (normalize to annual)"))
        if d is None or v is None:
            continue
        if asof is not None and d > asof:
            continue
        rank = 1 if (r.get("Annualized revenue type") or "").strip() else 0
        k = ((r.get("Company") or "").strip(), d)
        if k not in seen or rank >= seen[k][0]:   # 동순위면 나중 행
            seen[k] = (rank, r)
    seen = {k: r for k, (_, r) in seen.items()}

    per: dict[str, list[tuple[date, float, dict]]] = {}
    for (company, d), r in seen.items():
        per.setdefault(company, []).append((
            d,
            _io.to_num(r.get("Revenue amount (normalize to annual)")),
            {
                "type": (r.get("Annualized revenue type") or "").strip() or None,
                "confidence": (r.get("Confidence") or "").strip() or None,
                "note": (r.get("Graph note") or "").strip() or None,
            },
        ))

    today = asof or max((d for _, d in seen), default=None)
    series = []
    for company in COMPANIES:
        pts = sorted(per.get(company) or [])
        if not pts:
            continue
        last_d, last_v, _ = pts[-1]
        prev_d, prev_v = (pts[-2][0], pts[-2][1]) if len(pts) > 1 else (None, None)
        # 1년 전 값은 **스텝 조회**다 — 그 날짜 이하의 마지막 관측(보간 아님).
        ago = [v for d, v, _ in pts if (last_d - d).days >= 365]
        series.append({
            "key": _io.slug(company),
            "name": company,
            "points": [[d.isoformat(), v] for d, v, _ in pts],
            "marks": [m for _, _, m in pts],
            "stats": {
                "last": last_v,
                "last_date": last_d.isoformat(),
                "prev": prev_v,
                "prev_date": prev_d.isoformat() if prev_d else None,
                "chg_pct": ((last_v / prev_v - 1) * 100) if prev_v else None,
                "chg_1y_pct": ((last_v / ago[-1] - 1) * 100) if ago and ago[-1] else None,
                "first": pts[0][1],
                "first_date": pts[0][0].isoformat(),
                "n": len(pts),
                # 화면이 오래된 계열을 회색 처리하는 근거.
                "stale_days": (today - last_d).days if today else None,
            },
        })

    return {
        "unit": "USD",
        "scale": 1e9,
        "kind": "step",
        "note": None,
        "series": series,
    }


def _funding_group(table: _io.Table, asof: date | None) -> dict:
    """`ai_companies_funding_rounds.csv` → 조달 라운드 점.

    카드가 아니라 ARR 계열 위에 얹는 **주석**(밸류에이션 마커)용이라 `kind: scatter` 다.
    `Exclude from graph view` 는 Epoch 이 "이건 그리지 말라"고 표시한 행이라 존중한다.
    """
    _io.require(table, M_FUNDING, REQ_FUNDING)
    rounds = []
    for r in table.rows:
        if _io.is_true(r.get("Exclude from graph view")):
            continue
        d = _io.to_date(r.get("Close date"))
        if d is None or (asof is not None and d > asof):
            continue
        rounds.append({
            "company": (r.get("Company") or "").strip() or None,
            "date": d.isoformat(),
            "equity": _io.to_num(r.get("Funding (equity)")),
            "debt": _io.to_num(r.get("Funding (debt)")),
            "valuation": _io.to_num(r.get("Valuation (post-money)")),
            "status": (r.get("Status") or "").strip() or None,
            "type": (r.get("Type") or "").strip() or None,
            "confidence": (r.get("Confidence") or "").strip() or None,
        })
    rounds.sort(key=lambda e: e["date"])
    return {"unit": "USD", "scale": 1e9, "kind": "scatter", "note": None, "rounds": rounds}


def build_companies_payload(
    revenue: _io.Table | None,
    funding: _io.Table | None,
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    out = _common(source)
    out["revenue"] = {"unit": "USD", "scale": 1e9, "kind": "step", "note": None, "series": []}
    out["funding"] = {"unit": "USD", "scale": 1e9, "kind": "scatter", "note": None, "rounds": []}

    if revenue is not None:
        grp, note = _group(_revenue_group, revenue, asof)
        out["revenue"] = grp or {**out["revenue"], "note": note}
    if funding is not None:
        grp, note = _group(_funding_group, funding, asof)
        out["funding"] = grp or {**out["funding"], "note": note}

    dates = [s["stats"]["last_date"] for s in out["revenue"]["series"]]
    out["asof"] = max(dates, default=None)
    return out


# ══ 카드 B — 분기 AI 칩 출하 ════════════════════════════════════════════════

def build_chips_payload(
    timelines: _io.Table | None,
    chip_types: _io.Table | None,
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    """`timelines_by_chip.csv`(160행 결측 0) → 제조사별 분기 출하 H100e.

    ⚠️분기 결측은 `null` 이 아니라 **0** 이다 — 여기서 결측은 "그 분기 출하 보고 없음"이라
      0이 옳다. (토큰 카드의 모델별 결측이 `null` 인 것과 **의도적으로 다르다** —
      거기서는 결측이 "관측 창 밖"이라 0으로 채우면 거짓말이 된다.)
    ⚠️`Incomplete=True` 행 8건은 부분 분기다. 특히 마지막 분기는 제조사 한 곳만 있어
      **"전체 출하 급감"으로 보이는 착시가 확정적으로 발생한다** → `incomplete_quarters`.
    """
    out = _common(source)
    out.update({
        "unit": "H100e", "kind": "bar",
        "quarters": [], "incomplete_quarters": [], "last_complete_quarter": None,
        "designers": [],
        "chips_quarter": None, "chips": [],
        "totals": {"cum_h100e": None, "quarter": None},
    })
    if timelines is None:
        return out
    try:
        _io.require(timelines, M_TIMELINES_BY_CHIP, REQ_TIMELINES_BY_CHIP)
    except _io.SchemaError as exc:
        out["note"] = str(exc)
        return out

    # chip_types 는 조인표라 없거나 깨져도 카드가 죽지 않는다 — h100e_per_chip 만 빈다.
    per_chip: dict[str, dict] = {}
    if chip_types is not None:
        try:
            _io.require(chip_types, M_CHIP_TYPES, REQ_CHIP_TYPES)
            for r in chip_types.rows:
                per_chip[(r.get("Name") or "").strip()] = {
                    "h100e_per_chip": _io.to_num(r.get("H100e")),
                    "release_date": (
                        d.isoformat() if (d := _io.to_date(r.get("Release date"))) else None
                    ),
                }
        except _io.SchemaError as exc:
            out["note"] = f"{M_CHIP_TYPES} 조인 생략 — {exc}"

    rows = []
    for r in timelines.rows:
        q = _io.to_date(r.get("End date"))
        if q is None:
            continue
        # ⚠️여기서 `asof` 는 **분기 시작** 기준이다 — 데이터센터 카드와 뜻이 다르다.
        #   분기 라벨이 분기말이라 End date 로 자르면 **진행 중인 분기가 통째로 사라진다**
        #   (2026Q3 를 잘라 Nvidia 누적이 22.2M → 21.0M 로 실측 대비 5% 줄었다).
        #   진행 중 분기는 "미래 계획"이 아니라 "부분 관측"이고, 그건 버리는 게 아니라
        #   `Incomplete` 로 표시할 일이다. 진짜 미래 분기는 시작일로 걸러진다.
        if asof is not None and date(q.year, (q.month - 1) // 3 * 3 + 1, 1) > asof:
            continue
        rows.append((
            q,
            (r.get("Chip manufacturer") or "").strip(),
            (r.get("Chip type") or "").strip(),
            # ⚠️표시는 `Chip type`(사람이 읽는 이름), 조인은 `Chip type (linked)` —
            #   51행에서 값이 다르다(`H100/H200`→`H100`, `MI300X`→`Instinct MI300X`).
            (r.get("Chip type (linked)") or r.get("Chip type") or "").strip(),
            _io.to_num(r.get("Number of Units")) or 0.0,
            _io.to_num(r.get("Compute estimate in H100e (median)")) or 0.0,
            _io.to_num(r.get("Cost Estimate (USD)")),
            _io.is_true(r.get("Incomplete")),
        ))
    if not rows:
        return out

    quarters = sorted({r[0] for r in rows})
    incomplete = sorted({r[0] for r in rows if r[7]})
    out["quarters"] = [q.isoformat() for q in quarters]
    out["incomplete_quarters"] = [q.isoformat() for q in incomplete]
    # ★2026-08-31 사용자 지시로 신설. **끝난 분기 중 마지막** — 분기말이 asof 를 넘지 않은 것.
    #   `분기 신규(flow)` 차트가 여기까지만 그린다. 진행 중 분기는 제조사 한 곳만 보고돼
    #   있기 십상이라(2026Q3 실측: Nvidia 만 1.18M, Google·AMD 0) 그대로 그리면 직전 분기
    #   4.54M 대비 74% 급감으로 읽힌다 — 실제로 줄어든 게 아니라 아직 안 들어온 것이다.
    # ⚠️**누적(cum)에서는 자르지 않는다.** 진행 중 분기도 "부분 관측"이라 누적에는 유효한
    #   정보이고, 잘라내면 Nvidia 누적이 22.2M -> 21.0M 로 실측 대비 5% 과소계상된다
    #   (위 `asof` 주석의 근거와 같은 사례). 그래서 quarters 자체는 그대로 두고 이 경계만 싣는다.
    _complete = [q for q in quarters if asof is None or q <= asof]
    out["last_complete_quarter"] = _complete[-1].isoformat() if _complete else None
    out["asof"] = quarters[-1].isoformat()

    qi = {q: i for i, q in enumerate(quarters)}
    flows: dict[str, list[float]] = {}
    units: dict[str, list[float]] = {}
    seen_q: dict[str, set] = {}
    inc_q: dict[str, set] = {}
    for q, mfr, _chip, _linked, u, h, _cost, inc in rows:
        flows.setdefault(mfr, [0.0] * len(quarters))[qi[q]] += h
        units.setdefault(mfr, [0.0] * len(quarters))[qi[q]] += u
        seen_q.setdefault(mfr, set()).add(q)
        inc_q.setdefault(mfr, set())
        if inc:
            inc_q[mfr].add(q)

    designers = []
    for mfr, flow in flows.items():
        cum, run = [], 0.0
        for v in flow:
            run += v
            cum.append(run)
        # ★"완전한" 마지막 분기 — **그 제조사 자신이** Incomplete 로 표시하지 않은 마지막
        #   분기다(다른 제조사의 부분 분기까지 빼면 멀쩡한 값을 버린다).
        #   incomplete 분기를 그대로 flow_last 로 쓰면 "출하 급감"으로 읽힌다.
        good = sorted(seen_q[mfr] - inc_q[mfr])
        fq = good[-1] if good else None
        designers.append({
            "key": _io.slug(mfr),
            "name": mfr,
            "flow": flow,
            "cum": cum,
            "units": units[mfr],
            "stats": {
                "cum_last": cum[-1],
                "flow_last": flow[qi[fq]] if fq else None,
                "flow_last_quarter": fq.isoformat() if fq else None,
                "share_pct": None,   # 아래에서 전체 합이 나온 뒤 채운다
            },
        })

    grand = sum(d["stats"]["cum_last"] for d in designers)
    for d in designers:
        d["stats"]["share_pct"] = (
            round(d["stats"]["cum_last"] / grand * 100, 2) if grand else None
        )
    designers.sort(key=lambda d: -d["stats"]["cum_last"])
    out["designers"] = designers
    out["totals"] = {"cum_h100e": grand, "quarter": quarters[-1].isoformat()}

    # 칩별 내역은 **마지막 완전 분기** 기준이다(마지막 분기는 제조사 한 곳뿐일 수 있다).
    full = [q for q in quarters if q not in incomplete]
    cq = full[-1] if full else quarters[-1]
    out["chips_quarter"] = cq.isoformat()
    agg: dict[tuple[str, str], dict] = {}
    for q, mfr, chip, linked, u, h, cost, _inc in rows:
        if q != cq:
            continue
        e = agg.setdefault((mfr, chip), {
            "chip": chip, "designer": mfr, "units": 0.0, "h100e": 0.0, "cost_usd": 0.0,
            **per_chip.get(linked, {"h100e_per_chip": None, "release_date": None}),
        })
        e["units"] += u
        e["h100e"] += h
        e["cost_usd"] += cost or 0.0
    out["chips"] = sorted(agg.values(), key=lambda e: -e["h100e"])[:TOP_CHIPS]
    return out


# ══ 카드 C — AI 데이터센터 빌드아웃 ═════════════════════════════════════════

def _last_obs(rows: list[tuple], cut: date | None) -> dict[str, tuple]:
    """DC 별 **마지막 관측 한 행**. `cut` 이 None 이면 미래 행까지 그대로 들어온다.

    ⚠️이 함수의 `cut` 인자가 카드 C 전체에서 제일 중요한 스위치다 — None 이면 IT 전력이
      13,085 MW 대신 35,379 MW(2.70배)가 되어 **계획을 현재로 발표한다.**
    """
    best: dict[str, tuple] = {}
    for row in rows:
        d, name = row[0], row[1]
        if cut is not None and d > cut:
            continue
        if name not in best or d > best[name][0]:
            best[name] = row
    return best


def _sum_obs(best: dict[str, tuple]) -> dict:
    return {
        "sites": len(best),
        "it_power_mw": sum(r[2] or 0.0 for r in best.values()),
        "total_power_mw": sum(r[3] or 0.0 for r in best.values()),
        "h100e": sum(r[4] or 0.0 for r in best.values()),
        "capex_bn": sum(r[5] or 0.0 for r in best.values()),
    }


def build_datacenters_payload(
    masters: _io.Table | None,
    timelines: _io.Table | None,
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    """`data_centers.csv`(마스터 85) + `data_center_timelines.csv`(486) → 빌드아웃 카드.

    ⚠️`asof` 를 넘기지 않으면 미래 행 78건이 그대로 섞인다. 그게 이 데이터셋 전체에서
      제일 큰 오류 위험이라 `totals.it_power_mw`(과거 asof) 와
      `totals.planned_it_power_mw`(미래 포함) 두 값을 **다른 필드로** 낸다 —
      절대 같은 자리에 렌더하지 않는다(13,085 vs 35,379 = 2.70배).
    """
    out = _common(source)
    out.update({
        "asof_date": asof.isoformat() if asof else None,
        "units": {"power": "MW (IT)", "compute": "H100e", "capex": "2025 USD bn"},
        "kind": "step",
        "totals": {}, "buildout": [], "owners": [], "sites": [],
    })
    if timelines is None:
        return out
    try:
        _io.require(timelines, M_DC_TIMELINES, REQ_DC_TIMELINES)
    except _io.SchemaError as exc:
        out["note"] = str(exc)
        return out

    tl: list[tuple] = []
    for r in timelines.rows:
        d = _io.to_date(r.get("Date"))
        if d is None:
            continue
        tl.append((
            d,
            (r.get("Data center") or "").strip(),
            # ★KPI 도 차트 끝점도 `IT power (MW)` 다. `Power (MW)` 는 PUE 를 먹인 총
            #   시설전력이라 섞으면 28% 어긋난다 — 참고용으로만 따로 낸다.
            _io.to_num(r.get("IT power (MW)")),
            _io.to_num(r.get("Power (MW)")),
            _io.to_num(r.get("H100 equivalents")),
            _io.to_num(r.get("Total capital cost (2025 USD billions)")),
        ))
    if not tl:
        return out

    past = _last_obs(tl, asof)
    out["totals"] = _sum_obs(past)
    # ⚠️계획 총량. `totals.it_power_mw` 와 같은 자리에 렌더하면 안 된다.
    out["totals"]["planned_it_power_mw"] = _sum_obs(_last_obs(tl, None))["it_power_mw"]

    dates = sorted(d for d, *_ in tl if asof is None or d <= asof)
    out["asof"] = dates[-1].isoformat() if dates else None

    # 분기 asof 곡선 — 각 분기말 시점에 "그때까지 알려진 마지막 관측"의 합.
    if dates:
        for q in _io.quarter_ends(dates[0], asof or dates[-1]):
            snap = _sum_obs(_last_obs(tl, q))
            out["buildout"].append({"date": q.isoformat(), **{
                k: snap[k] for k in ("sites", "it_power_mw", "h100e", "capex_bn")
            }})

    # 마스터는 '현재값' 스냅샷이라 날짜 열이 없다. 오너 집계·사이트 목록만 여기서 온다
    # (마스터의 Current power 합이 과거 asof 합과 85/85 일치함을 확인했다).
    if masters is not None:
        try:
            _io.require(masters, M_DATA_CENTERS, REQ_DATA_CENTERS)
        except _io.SchemaError as exc:
            out["note"] = f"{M_DATA_CENTERS} 생략 — {exc}"
            return out

        owners: dict[str, dict] = {}
        for r in masters.rows:
            name = (r.get("Name") or "").strip()
            owner, conf = _io.strip_tag(r.get("Owner"))
            users = []
            for part in (r.get("Users") or "").split(","):
                u, uc = _io.strip_tag(part)
                if u:
                    users.append({"name": u, "confidence": uc})
            it = _io.to_num(r.get("Current power (MW)")) or 0.0
            h = _io.to_num(r.get("Current H100 equivalents")) or 0.0
            cx = _io.to_num(r.get("Current total capital cost (2025 USD billions)")) or 0.0
            obs = past.get(name)
            out["sites"].append({
                "name": name,
                "owner": owner,
                "owner_confidence": conf,
                "users": users,
                "country": (r.get("Country") or "").strip() or None,
                "it_power_mw": it,
                "h100e": h,
                "capex_bn": cx,
                "chips": [c.strip() for c in (r.get("Current chip types") or "").split(",") if c.strip()],
                "last_observed": obs[0].isoformat() if obs else None,
            })
            ok = owner or "Unknown"
            e = owners.setdefault(ok, {
                "key": _io.slug(ok), "name": ok, "sites": 0,
                "it_power_mw": 0.0, "h100e": 0.0, "capex_bn": 0.0,
            })
            e["sites"] += 1
            e["it_power_mw"] += it
            e["h100e"] += h
            e["capex_bn"] += cx

        grand = sum(e["it_power_mw"] for e in owners.values())
        out["owners"] = sorted(
            (
                {**e, "share_pct": round(e["it_power_mw"] / grand * 100, 2) if grand else None}
                for e in owners.values()
            ),
            key=lambda e: -e["it_power_mw"],
        )
        out["sites"].sort(key=lambda s: -s["it_power_mw"])
    return out


# ── zip 판독 + 실패 흡수 ────────────────────────────────────────────────────
# ★결측·손상·스키마 변경은 전부 **200 + 빈 payload + note** 다. 503 은 collector 장애
#   전용으로 남긴다(main.py 의 except Exception). 2026-08-27 에 결측을 503 으로 냈다가
#   화면이 "collector 에 못 닿았습니다"를 띄워 엉뚱한 층을 의심하게 만든 전례가 있다.
#   Epoch 은 수집기가 주 1회 받아 놓는 스냅샷이라 결측/구버전이 정상 경로로 존재한다.

def _load(members: tuple[str, ...]) -> tuple[dict | None, str | None]:
    """멤버 CSV 들을 한 번에. 하나라도 없으면 그 카드 전체를 빈 payload + note 로 낸다."""
    tables: dict[str, _io.Table] = {}
    for m in members:
        p = member_path(m)
        try:
            tables[m] = _io.read_flat_csv_dicts(p)
        except FileNotFoundError:
            return None, (f"원천 CSV 가 없습니다 - {p} "
                          f"(수집기 `ai_key_data.bat` 을 한 번 돌리면 생깁니다)")
        except OSError as exc:
            return None, f"CSV 를 읽지 못했습니다({exc.__class__.__name__}) - {p}"
    return tables, None


def build_epoch_companies(asof: date | None = None) -> dict:
    asof = asof or _io.today_kst()
    src = _io.source_block("ai_companies", member_path(M_REVENUE), "epoch", asof)
    tables, note = _load((M_REVENUE, M_FUNDING))
    if tables is None:
        out = build_companies_payload(None, None, asof, src)
        out["note"] = note
        return out
    return build_companies_payload(
        tables.get(M_REVENUE), tables.get(M_FUNDING), asof, src
    )


def build_epoch_chips(asof: date | None = None) -> dict:
    asof = asof or _io.today_kst()
    src = _io.source_block("ai_chip_sales", member_path(M_TIMELINES_BY_CHIP), "epoch", asof)
    tables, note = _load((M_TIMELINES_BY_CHIP, M_CHIP_TYPES))
    if tables is None:
        out = build_chips_payload(None, None, asof, src)
        out["note"] = note
        return out
    return build_chips_payload(
        tables.get(M_TIMELINES_BY_CHIP), tables.get(M_CHIP_TYPES), asof, src
    )


def build_epoch_datacenters(asof: date | None = None) -> dict:
    """★`asof` 기본값은 오늘(KST)이다. **None 을 넘기면 미래 행이 섞인다** — 계산부가
    그 판단을 하지 않도록 일부러 인자로 뺐고, 테스트가 두 값을 핀으로 박고 있다."""
    asof = asof or _io.today_kst()
    src = _io.source_block("data_centers", member_path(M_DC_TIMELINES), "epoch", asof)
    tables, note = _load((M_DATA_CENTERS, M_DC_TIMELINES))
    if tables is None:
        out = build_datacenters_payload(None, None, asof, src)
        out["note"] = note
        return out
    return build_datacenters_payload(
        tables.get(M_DATA_CENTERS), tables.get(M_DC_TIMELINES), asof, src
    )
