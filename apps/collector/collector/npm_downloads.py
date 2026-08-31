"""[AI Key Data] 코딩 에이전트 npm 다운로드 판독 (2026-08-28).

`@anthropic-ai/claude-code` · `@openai/codex` 등 코딩 에이전트 CLI 의 일별 npm 다운로드 수.
"AI 코딩 도구가 실제로 얼마나 쓰이는가"의 대리 지표로, 토큰 사용량 카드와 같은 축이다.

원천은 ws3 수집기가 매일 10:00 KST 에 굽는 `npm_downloads_long.csv` —
`date,package,downloads` 3열. **원시 일간값만 들어 있다**(평활은 수집기가 하지 않는다).

★이 파일은 ws3 배포 전까지 **존재하지 않는다**. 그때는 빈 series + note 로 200 을 낸다 —
  "수집 시작 전"이 문구로 그대로 드러나야 한다(503 이면 인프라 장애로 오진된다).

⚠️주중/주말 스윙이 크다 — 같은 패키지가 토요일 806K, 화요일 2.70M(**3.3배**)다. 토큰 카드
  (1.3배)보다 훨씬 심해서 일별 원본만 그리면 톱니만 보인다. 그래서 `ma7` 을 **collector 가
  계산해 같이 내린다**(하우스 선례: ADP 카드가 서버가 준 `ma12` 를 그린다). 앞 6일은 null.

★패키지 목록은 여기에 하드코딩하지 않고 **데이터에서 뽑는다.** 무엇을 받을지는 ws3 쪽
  `agent\\config.toml` 이 정본이라 여기에 또 적으면 두 곳이 조용히 어긋난다. 사람이 config 에
  패키지를 추가하면 다음 갱신부터 카드에 저절로 나타난다.
  아래 상수는 "몇 개를 어떤 창으로 줄 세우나" 만 정한다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from collector import ai_key_data_io as _io

SRC_PATH = os.environ.get(
    "NPM_DOWNLOADS_CSV", os.path.join(_io.RAW_DIR, "npm_downloads_long.csv")
)
_MEMBER = os.path.basename(SRC_PATH)
_REQUIRED = ("date", "package", "downloads")

# ── 집계 파라미터 (사람이 고치는 곳) ────────────────────────────────────────
RANK_WINDOW = 28          # 패키지 순서를 정하는 창(최근 4주 합계 내림차순)
MAX_PACKAGES = 0          # 0 = 전부. 목록이 길어지면 여기서 자른다
MA_WINDOW = 7             # 주중/주말 3.3배 스윙 평활. 앞 6일은 null
UNIT = "downloads"


# ── 순수 계산부 (파일 IO 없음 — 테스트는 여기를 겨눈다) ──────────────────────

def _series(days: list[date], by_day: dict[date, int]) -> tuple[list, list]:
    """공통 날짜 축 위의 `points` 와 `ma7`.

    ⚠️결측일은 `null` 이다. npm 은 "그 날 0회 다운로드"와 "그 날 응답이 없었다"가 다르고,
      후자를 0으로 채우면 평균이 조용히 내려앉는다(토큰 카드의 top-50 이탈과 같은 판단).
    """
    vals = [by_day.get(d) for d in days]
    ma = _io.moving_average(vals, MA_WINDOW)
    points = [[d.isoformat(), v] for d, v in zip(days, vals)]
    ma7 = [[d.isoformat(), (None if v is None else round(v, 1))] for d, v in zip(days, ma)]
    return points, ma7


# ── 이상치 탐지 (2026-08-31 사용자 지시) ────────────────────────────────────
# 판정 기준을 **중앙값 대비**로 잡는다. 평균/이웃평균은 스파이크 자신에게 끌려가고,
# 이 데이터는 주중/주말 스윙이 3.3배라 단순 배수로는 요일 효과를 못 가른다.
#   · 창 = 자기 자신을 뺀 앞뒤 ±ANOM_WIN 일의 중앙값(요일 효과가 창 안에서 상쇄된다)
#   · 임계 = ANOM_RATIO 배. 요일 효과(3.3배)보다 위에 둬서 월요일 피크가 안 걸리게 한다
#   · 하한 = ANOM_MIN. 초기 구간의 한 자릿수 값(3 -> 8)이 x2.7 로 걸리는 걸 막는다
# ★판정만 하고 원값은 건드리지 않는다. `adj` 는 **따로** 실어 화면이 둘을 겹쳐 그린다 —
#   이 폴더 규칙대로 이상치를 지우지 않고 보이게 둔다.
# ★창을 ±21 일로 넓히고 **2패스**로 돈다. ±7 로는 실측 사례를 못 잡는다 —
#   2026-04-30~05-06 은 **7일 연속** 부풀어 있어서(codex 가 전체의 86~98%) 좁은 창에서는
#   중앙값 자신이 블록에 끌려 올라가 배수가 임계 밑으로 내려간다(블록 양끝을 통째로 놓쳤다).
#   1패스에서 걸린 점을 빼고 중앙값을 다시 구하면 블록 전체가 드러난다.
ANOM_WIN = 21
ANOM_RATIO = 4.0
ANOM_MIN = 10_000
ANOM_PASSES = 2
ANOM_TOTALS_SHARE = 0.20   # 총합에 올릴 기준 ①: 보정이 그날 총합을 20% 이상 움직임(비율)
ANOM_TOTALS_ABS = 0.01     # 기준 ②: 그 초과분이 계열 최댓값의 1% 이상(= 차트에서 보이는가)


def _median(xs: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    ys = sorted(xs)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def _anomalies(points: list[list]) -> tuple[list[dict], list[list]]:
    """(이상치 목록, 보정 계열). 보정은 이상치를 좌우 창 중앙값의 작은 쪽으로 갈아 끼운 것.

    ★★판정은 **양쪽 창을 따로** 본다. 한쪽만 보면 신규 패키지의 **출시 램프**가 통째로
      이상치가 된다 — 실측: `@anthropic-ai/claude-code` 2025-02-24~28 이 0 -> 수만으로
      올라가고 **그대로 유지**되는데, 왼쪽 창만 보면 x3891 로 걸린다. 그건 레벨 시프트지
      이상치가 아니다. 오른쪽 창도 함께 요구하면 램프는 자동으로 탈락한다(오른쪽이 이미 높다).
    ★이상치는 "튀었다가 **돌아온다**" — 그래서 좌우 둘 다 임계를 넘어야 한다.
    """
    vals = [v for _, v in points]
    n = len(vals)
    flagged: set[int] = set()
    expected: dict[int, float] = {}

    for _ in range(ANOM_PASSES):
        for i in range(n):
            if vals[i] < ANOM_MIN:
                continue
            # 이전 패스에서 걸린 점은 중앙값 계산에서 뺀다 — 안 빼면 연속 블록이
            # 자기 자신을 정상으로 만든다(2026-04-30~05-06 실측).
            left = [vals[k] for k in range(max(0, i - ANOM_WIN), i) if k not in flagged]
            right = [vals[k] for k in range(i + 1, min(n, i + ANOM_WIN + 1)) if k not in flagged]
            if len(left) < 5 or len(right) < 5:
                continue                      # 계열 양끝은 판정하지 않는다(창이 안 찬다)
            ml, mr = _median(left), _median(right)
            if ml <= 0 or mr <= 0:
                continue
            if vals[i] / ml >= ANOM_RATIO and vals[i] / mr >= ANOM_RATIO:
                flagged.add(i)
                expected[i] = min(ml, mr)

    marks: list[dict] = []
    adj = [list(p) for p in points]
    for i in sorted(flagged):
        med = expected[i]
        marks.append({
            "date": points[i][0],
            "value": vals[i],
            "expected": round(med),
            "ratio": round(vals[i] / med, 2),
        })
        adj[i][1] = round(med)
    return marks, adj

def build_payload(
    rows: list[tuple[date, str, int]],
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    """`[(날짜, 패키지, 다운로드수)]` → 카드 payload.

    `asof` 는 인자다 — 계산부 안에서 `today()` 를 부르지 않는다(고정 날짜 테스트).
    """
    out: dict = {
        "generated_at": _io.generated_at(),
        "asof": None,
        "note": None,
        "source": source,
        "unit": UNIT,
        "kind": "line",
        "grain": "daily",
        "rank_window_days": RANK_WINDOW,
        # ★2026-08-31(2차) 사용자 지시 — 화면은 **7일평균선 한 개**만 그린다.
        #   보정 계열을 따로 그어 두 줄로 만들지 않는다. 대신 이상치에 오염된 구간만
        #   `daily_ma7_interp` 에서 **선형보간**으로 이어 두고, 그 구간 날짜를
        #   `ma7_interp_dates` 로 알려 화면이 그 부분만 빨갛게 잇는다.
        "totals": {"daily": [], "daily_ma7": [], "daily_ma7_interp": []},
        # 이상치 판정 결과(원값은 그대로 둔다). 화면이 이 날짜를 빨갛게 찍고 보정선을 겹친다.
        "anomalies": [],
        "totals_anomaly_dates": [],
        "ma7_interp_dates": [],
        "packages": [],
        "n_packages": 0,
    }
    if asof is not None:
        rows = [r for r in rows if r[0] <= asof]
    if not rows:
        return out

    by_pkg: dict[str, dict[date, int]] = {}
    by_day: dict[date, int] = {}
    for d, p, v in rows:
        by_pkg.setdefault(p, {})[d] = by_pkg.setdefault(p, {}).get(d, 0) + v
        by_day[d] = by_day.get(d, 0) + v

    days = sorted(by_day)
    last = days[-1]
    out["asof"] = last.isoformat()

    out["totals"]["daily"], out["totals"]["daily_ma7"] = _series(days, by_day)

    # ★★이상치는 **패키지별로** 판정한다. 총합에서 보면 다른 패키지가 희석해 놓친다 —
    #   실측: 2026-05-11 codex 7.86M 은 자기 기준 8.7배인데 총합에서는 2.6배라 임계 미달이다.
    #   판정 후 보정된 패키지 계열을 다시 더해(`adj_by_day`) '그날 총합이 얼마나 부풀었나'를
    #   재고, 20% 이상 움직인 날만 `totals_anomaly_dates` 로 화면에 넘긴다.
    #   대표 사례: 2026-04-30~05-06 `@openai/codex` 가 평시 0.9M -> 최대 46M(약 50배)로
    #   7일간 부풀었다가 그대로 복귀했다. 그 기간 codex 가 전체의 86~98% 였고 나머지 12개
    #   패키지는 정상이었다. codex 는 하루 17개꼴로 상시 발행하므로 릴리스로 설명되지 않는다
    #   — 미러/CI 대량 pull 이 다운로드로 집계된 신호로 본다(npm 카운트는 자동화 fetch 포함).
    marks: list[dict] = []
    adj_by_day: dict[str, int] = {d.isoformat(): 0 for d in days}
    for pkg, m in by_pkg.items():
        ppts = [[d.isoformat(), m.get(d, 0)] for d in days]
        pmarks, padj = _anomalies(ppts)
        for mk in pmarks:
            mk["package"] = pkg
            marks.append(mk)
        for dt, v in padj:
            adj_by_day[dt] += v
    marks.sort(key=lambda x: (x["date"], x["package"]))
    out["anomalies"] = marks

    # ── 총합 곡선에서 **실제로 보이는** 이상치만 고른다 ──────────────────────
    # 두 조건을 모두 만족해야 한다:
    #   ① 보정이 그날 총합을 ANOM_TOTALS_SHARE 이상 움직였는가 (비율)
    #   ② 그 초과분이 계열 최댓값의 ANOM_TOTALS_ABS 이상인가 (절대량 = 눈에 보이는가)
    # ②가 없으면 2025-05-27(6.7만 -> 3.5만, -47%)처럼 비율만 큰 날이 걸리는데, 4,700만
    # 스케일의 차트에서는 점 하나도 안 된다. 거기에 빨간 구간을 칠하면 아무 변화도 없는
    # 자리에 경고만 뜬다 — 사용자 지시("팍 튄 부분만")의 뜻은 눈에 보이는 스파이크다.
    _peak = max(by_day.values()) if by_day else 0
    out["totals_anomaly_dates"] = [
        d.isoformat()
        for d in days
        if by_day.get(d, 0) > 0
        and abs(by_day[d] - adj_by_day[d.isoformat()]) / by_day[d] >= ANOM_TOTALS_SHARE
        and abs(by_day[d] - adj_by_day[d.isoformat()]) >= _peak * ANOM_TOTALS_ABS
    ]

    # ── 그 구간의 7일평균을 선형보간으로 잇는다 ─────────────────────────────
    # ★화면은 **선을 한 개만** 그린다(2026-08-31 사용자 지시). 보정 계열을 따로 그어
    #   두 줄로 만들지 않는다 — 오염된 구간을 이 계열 안에서 직선으로 갈아 끼우고,
    #   그 구간 날짜만 화면이 빨갛게 덧그린다.
    # ⚠️오염 범위는 이상치 날짜 그 자체가 아니라 **그 날부터 MA_WINDOW-1 일 뒤까지**다 —
    #   ma7[i] 가 daily[i-6..i] 를 쓰므로 이상치 하루가 평균 7점을 밀어 올린다. 이걸
    #   안 넓히면 보간 구간 바로 오른쪽에 부풀린 봉우리가 그대로 남는다.
    # ⚠️기준은 `marks`(패키지별 41건)가 아니라 위 `totals_anomaly_dates` 다. 전자를 쓰면
    #   총합에서 보이지도 않는 소형 스파이크까지 이어 127일 12구간이 빨개진다(실측).
    idx = {d.isoformat(): k for k, d in enumerate(days)}
    bad: set[int] = set()
    for dt in out["totals_anomaly_dates"]:
        k0 = idx.get(dt)
        if k0 is None:
            continue
        for k in range(k0, min(len(days), k0 + MA_WINDOW)):
            bad.add(k)

    interp = [list(p) for p in out["totals"]["daily_ma7"]]
    interp_dates: list[str] = []
    n = len(interp)
    k = 0
    while k < n:
        if k not in bad:
            k += 1
            continue
        j2 = k
        while j2 < n and j2 in bad:
            j2 += 1
        lo, hi = k - 1, j2                      # 구간 양옆의 성한 점
        v0 = interp[lo][1] if lo >= 0 else None
        v1 = interp[hi][1] if hi < n else None
        if v0 is None and v1 is None:           # 앞 6일은 ma7 이 null 이라 이 경우가 생긴다
            k = j2
            continue
        v0 = v1 if v0 is None else v0
        v1 = v0 if v1 is None else v1
        span = hi - lo
        for t in range(k, j2):
            interp[t][1] = round(v0 + (v1 - v0) * (t - lo) / span)
            interp_dates.append(interp[t][0])
        k = j2

    out["totals"]["daily_ma7_interp"] = interp
    # ★화면은 이 날짜들만 빨간 선으로 덧그린다. 양 끝 한 점씩은 성한 값과 이어져야
    #   선이 끊겨 보이지 않으므로, 잇는 일은 화면 쪽에서 처리한다.
    out["ma7_interp_dates"] = interp_dates

    wlo = last - timedelta(days=RANK_WINDOW - 1)
    win_tot = {
        p: sum(v for d, v in m.items() if d >= wlo) for p, m in by_pkg.items()
    }
    ranked = sorted(by_pkg, key=lambda p: -win_tot[p])
    if MAX_PACKAGES:
        ranked = ranked[:MAX_PACKAGES]
    grand = sum(win_tot[p] for p in ranked)

    for p in ranked:
        m = by_pkg[p]
        pts, ma7 = _series(days, m)
        pdays = sorted(m)
        plast = pdays[-1]
        prev = m.get(plast - timedelta(days=1))
        # 전주 동요일 대비 — 요일 효과를 타지 않는 유일한 일간 비교다(3.3배 스윙 때문).
        wow = m.get(plast - timedelta(days=7))
        out["packages"].append({
            "key": _io.slug(p),
            "name": p,
            "kind": "line",
            "points": pts,
            "ma7": ma7,
            "stats": {
                "last": m[plast],
                "last_date": plast.isoformat(),
                "chg_1d_pct": ((m[plast] / prev - 1) * 100) if prev else None,
                "chg_1w_pct": ((m[plast] / wow - 1) * 100) if wow else None,
                "window_total": win_tot[p],
                "share_pct": round(win_tot[p] / grand * 100, 2) if grand else None,
                "n": len(pdays),
                "stale_days": (last - plast).days,
            },
        })

    out["n_packages"] = len(out["packages"])
    return out


# ── CSV 판독 ────────────────────────────────────────────────────────────────

def _read_rows(path: str = SRC_PATH) -> list[tuple[date, str, int]]:
    """`npm_downloads_long.csv` → `[(날짜, 패키지, 다운로드수)]`. 깨진 행은 건너뛴다."""
    tbl = _io.read_flat_csv(path)
    _io.require(tbl, _MEMBER, _REQUIRED)
    ix = {c: i for i, c in enumerate(tbl.columns)}
    di, pi, vi = ix["date"], ix["package"], ix["downloads"]
    top = max(di, pi, vi)

    out: list[tuple[date, str, int]] = []
    for r in tbl.rows:
        if len(r) <= top:
            continue
        d = _io.to_date(r[di])
        v = _io.to_int(r[vi])
        p = (r[pi] or "").strip()
        if d is None or v is None or not p:
            continue
        out.append((d, p, v))
    return out


def build_npm_downloads(asof: date | None = None) -> dict:
    """CSV → 카드 payload 한 장. 결측·스키마 사유는 전부 200 + note 로 접는다."""
    src = _io.source_block("npm", SRC_PATH, "npm", asof)
    try:
        rows = _read_rows()
    except FileNotFoundError:
        out = build_payload([], asof, src)
        out["note"] = (
            f"아직 수집이 시작되지 않았습니다 — {SRC_PATH} 가 없습니다"
            " (ws3 수집기 배포 후 매일 10:00 KST 에 생깁니다)"
        )
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
    if not out["packages"]:
        out["note"] = f"유효한 데이터 행이 0건입니다(총 {len(rows)}행) — {SRC_PATH}"
    return out
