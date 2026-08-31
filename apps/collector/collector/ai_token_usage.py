"""[AI Key Data] OpenRouter 일간 토큰 사용량 판독 (2026-08-28).

이 페이지에서 **가장 조밀한 데이터**다. 602 일별 포인트(2025-01-01 ~) 대 ARR 카드 17포인트,
매일 자동 갱신 대 주 1회 수기. 최근 28일 평균이 1년 전 같은 창의 25배다.

원천은 상류 `fetch_token_usage.py`(OpenRouter `datasets/rankings-daily`)가 매일 굽는
`tokens_daily_long.csv` — `date,model,total_tokens` **3열 고정**.
★같은 폴더의 `tokens_daily_wide.csv` 는 읽지 않는다. 열이 397개고 top-50 이 교체될 때마다
  **스키마 자체가 변형**돼 필수 컬럼 계약을 걸 수 없다. long 의 합이 wide 의 `TOTAL` 과
  일치하는 것을 확인했으므로 정보 손실 없이 long 하나만 읽으면 된다.

⚠️구조 함정 4건 — 전부 실측으로 확정했고 payload 가 스스로 말하게 해 뒀다:

 1. **전수집계가 아니다.** 602일 내내 정확히 51행 = 상위 50 모델 + 나머지를 뭉친 `other`
    버킷 1개(최근 30일 평균 6.2%, 최대 11.3%). 총합 시계열은 신뢰할 수 있지만
    **"모델 N개 중 점유율" 류 표현은 하면 안 된다** — 분모가 top-50 이지 전체가 아니다.
    → `coverage`·`other_share_pct` 를 실어 화면 문구가 이걸 못 박게 한다.
 2. **모델별 결측은 `null` 이지 `0` 이 아니다.** top-50 은 하루 중앙값 3종씩 교체되는데,
    어떤 모델이 그날 빠진 건 "사용량 0"이 아니라 **"그날 51위 밖"** 이다. 0으로 채우면
    되돌릴 수 없는 손실이다. (칩 공급 카드가 결측 분기를 0으로 채우는 것과 **의도적으로
    다르다** — 거기서는 결측이 "그 분기 출하 보고 없음"이라 0이 옳다.)
 3. **요일 효과가 크다.** 최근 90일 요일별 지수 토 85 · 일 87 vs 수 109 → 일별 총합의 45%가
    전일 대비 마이너스인데 소급 정정이 아니라 주말이다(원값에 음수는 0건).
    → 기본 그레인은 주간이고, `ma7` 을 서버가 계산해 같이 내린다. 일별도 실어 가역이다.
 4. **마지막 주 버킷은 항상 부분주다.** 상류가 UTC 어제까지만 받아 93.4T → 71.4T 로 꺾여
    보이는데 실제로는 4일치다. → `incomplete_buckets` 로 화면이 점선 처리하게 한다.

⚠️라이선스가 Epoch 과 다르다. 이 데이터는 CC-BY 가 아니고 파일에 약관이 동봉돼 있지도 않다.
  `source.license` 는 **null 이고 출처만 싣는다** — 약관을 지어내지 않는다(§SOURCES).
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from collector import ai_key_data_io as _io

SRC_PATH = os.environ.get(
    "AI_TOKEN_USAGE_CSV", os.path.join(_io.RAW_DIR, "tokens_daily_long.csv")
)
_MEMBER = os.path.basename(SRC_PATH)
_REQUIRED = ("date", "model", "total_tokens")

# ── 집계 파라미터 (사람이 고치는 곳) ────────────────────────────────────────
OTHER_KEY = "other"       # top-50 밖 전부를 뭉친 버킷. **모델이 아니다** — 벤더 축에는 두되
                          # "점유율"의 분모로 쓰면 안 된다.
WINDOW_DAYS = 30          # 벤더·모델 순위를 매기는 창
TOP_MODELS = 10           # payload 에 계열을 실을 모델 수 (창 기준 상위 N)
MA_WINDOW = 7             # 요일 효과 평활. 앞 6일은 창이 안 차 null 이다
WEEKDAY_WINDOW = 90       # 요일 지수를 재는 창
YOY_WINDOW = 28           # "1년 전의 몇 배" 를 재는 창
UNIT = "tokens"
SCALE = 1e12              # 화면 표기 단위 힌트(T토큰)


# ── 순수 계산부 (파일 IO 없음 — 테스트는 여기를 겨눈다) ──────────────────────

def _month_totals(daily: list[tuple[date, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d, v in daily:
        out[f"{d.year:04d}-{d.month:02d}"] = out.get(f"{d.year:04d}-{d.month:02d}", 0) + v
    return out


def _window_mean(by_date: dict[date, int], end: date, days: int) -> float | None:
    """`end` 로 끝나는 `days` 일 창의 **일평균**. 창에 값이 하나도 없으면 None.

    결측일(실측 2일)은 분모에서 빼지 않고 창 길이로 나눈다 — 그래야 두 창의 비교가
    같은 자로 잰 값이 된다.
    """
    lo = end - timedelta(days=days - 1)
    vals = [v for d, v in by_date.items() if lo <= d <= end]
    return (sum(vals) / days) if vals else None


def build_payload(
    rows: list[tuple[date, str, int]],
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    """`[(날짜, 모델슬러그, 토큰수)]` → 카드 payload.

    `asof` 는 **인자다**(계산부 안에서 `today()` 를 부르지 않는다) — 고정 날짜 테스트가
    가능해야 하고, 상류가 미래 날짜를 실어 보내도 여기서 잘린다.
    """
    out: dict = {
        "generated_at": _io.generated_at(),
        "asof": None,
        "note": None,
        "source": source,
        "unit": UNIT,
        "scale": SCALE,
        # ★전수집계가 아님을 payload 가 스스로 말한다.
        "coverage": "top50_plus_other",
        "grain": "weekly",
        "totals": {"daily": [], "daily_ma7": [], "weekly": []},
        "incomplete_buckets": [],
        "missing_dates": [],
        "stats": {},
        "vendors": [],
        "models": [],
        "active_models_30d": 0,
        "other_share_pct": None,
    }
    if asof is not None:
        rows = [r for r in rows if r[0] <= asof]
    if not rows:
        return out

    by_date: dict[date, int] = {}
    by_date_model: dict[date, dict[str, int]] = {}
    for d, m, v in rows:
        by_date[d] = by_date.get(d, 0) + v
        by_date_model.setdefault(d, {})[m] = by_date_model.setdefault(d, {}).get(m, 0) + v

    days = sorted(by_date)
    first, last = days[0], days[-1]
    out["asof"] = last.isoformat()

    # 일별 — ⚠️결측일은 **아예 뺀다**. 0을 끼워 넣으면 가짜 급락이 생긴다.
    daily = [(d, by_date[d]) for d in days]
    out["totals"]["daily"] = [[d.isoformat(), v] for d, v in daily]
    ma = _io.moving_average([v for _, v in daily], MA_WINDOW)
    out["totals"]["daily_ma7"] = [
        [d.isoformat(), (None if v is None else round(v, 1))]
        for (d, _), v in zip(daily, ma)
    ]

    # 상류 공백. 보간하지 않고 화면이 알 수 있게만 한다.
    present = set(days)
    out["missing_dates"] = [
        (first + timedelta(days=i)).isoformat()
        for i in range((last - first).days + 1)
        if (first + timedelta(days=i)) not in present
    ]

    # 주간(W-SUN) — 요일 효과를 먹은 일별 톱니 대신 이게 기본 그레인이다.
    weekly: dict[date, int] = {}
    for d, v in daily:
        weekly[_io.week_end(d)] = weekly.get(_io.week_end(d), 0) + v
    wk = sorted(weekly)
    out["totals"]["weekly"] = [[d.isoformat(), weekly[d]] for d in wk]
    # ⚠️마지막 주가 아직 안 끝났으면 부분주다 — 안 찍으면 "감소 전환"으로 오독된다.
    if wk and wk[-1] > last:
        out["incomplete_buckets"] = [wk[-1].isoformat()]

    # ── stats ────────────────────────────────────────────────────────────
    months = _month_totals(daily)
    cur_month = f"{last.year:04d}-{last.month:02d}"
    # 그 달 마지막 날까지 데이터가 있어야 완결월이다.
    nxt = date(last.year + (last.month == 12), (last.month % 12) + 1, 1)
    full_months = sorted(m for m in months if m != cur_month or last == nxt - timedelta(days=1))
    mom = None
    if len(full_months) >= 2:
        a, b = months[full_months[-2]], months[full_months[-1]]
        mom = ((b / a - 1) * 100) if a else None

    now_mean = _window_mean(by_date, last, YOY_WINDOW)
    ago_mean = _window_mean(by_date, last - timedelta(days=365), YOY_WINDOW)

    # 요일 지수 — 최근 90일, 전체평균 = 100. 월~일 순서.
    lo90 = last - timedelta(days=WEEKDAY_WINDOW - 1)
    win90 = [(d, v) for d, v in daily if d >= lo90]
    weekday_index: list[float | None] = [None] * 7
    if win90:
        overall = sum(v for _, v in win90) / len(win90)
        for wd in range(7):
            vs = [v for d, v in win90 if d.weekday() == wd]
            weekday_index[wd] = round(sum(vs) / len(vs) / overall * 100, 1) if vs and overall else None

    out["stats"] = {
        "last_date": last.isoformat(),
        "last": by_date[last],
        "first_date": first.isoformat(),
        "n_days": len(days),
        "mtd_t": round(months.get(cur_month, 0) / SCALE, 1),
        "last_full_month": full_months[-1] if full_months else None,
        "mom_pct": None if mom is None else round(mom, 1),
        "yoy_x": (
            round(now_mean / ago_mean, 1)
            if now_mean is not None and ago_mean else None
        ),
        "weekday_index": weekday_index,
    }

    # ── 최근 창(WINDOW_DAYS) 기준 벤더·모델 ────────────────────────────────
    wlo = last - timedelta(days=WINDOW_DAYS - 1)
    wdays = [d for d in days if d >= wlo]
    wtot = sum(by_date[d] for d in wdays)

    model_tot: dict[str, int] = {}
    for d in wdays:
        for m, v in by_date_model[d].items():
            model_tot[m] = model_tot.get(m, 0) + v

    vendors: dict[str, dict] = {}
    for m, v in model_tot.items():
        # ⚠️`/` 가 없는 값은 실측상 `other` 하나뿐이다.
        vk = m.split("/")[0] if "/" in m else m
        e = vendors.setdefault(vk, {"key": _io.slug(vk), "name": vk, "tokens": 0, "n_models": 0})
        e["tokens"] += v
        e["n_models"] += 1
    out["vendors"] = sorted(
        (
            {**e, "share_pct": round(e["tokens"] / wtot * 100, 2) if wtot else None}
            for e in vendors.values()
        ),
        key=lambda e: -e["tokens"],
    )

    # 모델 계열 — ⚠️그날 top-50 밖이면 그 자리는 **null**(0 아님).
    ranked = sorted(
        (m for m in model_tot if m != OTHER_KEY), key=lambda m: -model_tot[m]
    )[:TOP_MODELS]
    for m in ranked:
        out["models"].append({
            "slug": m,
            "vendor": m.split("/")[0] if "/" in m else m,
            "tokens": model_tot[m],
            "share_pct": round(model_tot[m] / wtot * 100, 2) if wtot else None,
            "points": [[d.isoformat(), by_date_model[d].get(m)] for d in wdays],
        })

    out["active_models_30d"] = sum(1 for m in model_tot if m != OTHER_KEY)
    oth = [
        by_date_model[d].get(OTHER_KEY, 0) / by_date[d] * 100
        for d in wdays if by_date[d]
    ]
    out["other_share_pct"] = round(sum(oth) / len(oth), 2) if oth else None
    return out


# ── CSV 판독 ────────────────────────────────────────────────────────────────

def _read_rows(path: str = SRC_PATH) -> list[tuple[date, str, int]]:
    """`tokens_daily_long.csv` → `[(날짜, 모델, 토큰수)]`.

    3열 고정이라 위치 인덱스로 훑는다(§read_flat_csv). 헤더만 한 번 검증하면 안전하다.
    날짜·값이 깨진 행은 건너뛴다 — 한 줄 때문에 카드를 비우지 않는다.
    """
    tbl = _io.read_flat_csv(path)
    _io.require(tbl, _MEMBER, _REQUIRED)
    ix = {c: i for i, c in enumerate(tbl.columns)}
    di, mi, ti = ix["date"], ix["model"], ix["total_tokens"]
    top = max(di, mi, ti)

    out: list[tuple[date, str, int]] = []
    for r in tbl.rows:
        if len(r) <= top:
            continue
        d = _io.to_date(r[di])
        v = _io.to_int(r[ti])
        if d is None or v is None:
            continue
        out.append((d, (r[mi] or "").strip(), v))
    return out


def build_ai_token_usage(asof: date | None = None) -> dict:
    """CSV → 카드 payload 한 장.

    ★원천이 없거나 스키마가 바뀌면 **503 이 아니라 빈 payload + note** 다. 2026-08-27 에
      결측을 503 으로 냈다가 화면이 "collector 에 못 닿았습니다"를 띄워 네트워크·컨테이너를
      헛짚은 전례가 있다. 503 은 진짜 collector 결함 전용으로 남긴다(main.py 의 except).
    """
    src = _io.source_block("openrouter", SRC_PATH, "openrouter", asof)
    try:
        rows = _read_rows()
    except FileNotFoundError:
        out = build_payload([], asof, src)
        out["note"] = f"원천 파일이 없습니다 — {SRC_PATH}"
        return out
    except _io.SchemaError as exc:
        out = build_payload([], asof, src)
        out["note"] = str(exc)
        return out
    except OSError as exc:
        out = build_payload([], asof, src)
        out["note"] = f"원천 파일을 읽지 못했습니다({exc.__class__.__name__}) — {SRC_PATH}"
        return out

    out = build_payload(rows, asof, src)
    if not out["totals"]["daily"]:
        out["note"] = f"유효한 데이터 행이 0건입니다(총 {len(rows)}행) — {SRC_PATH}"
    return out
