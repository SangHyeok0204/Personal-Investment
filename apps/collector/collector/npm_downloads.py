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
        "totals": {"daily": [], "daily_ma7": []},
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
