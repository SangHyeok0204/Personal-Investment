"""[AI Key Data] VS Code 확장 설치수 판독 (2026-08-28).

`anthropic.claude-code` · `GitHub.copilot-chat` 등 AI 코딩 확장의 마켓플레이스 설치수.
원천은 ws3 수집기가 매일 10:10 KST 에 append 하는 `vscode_installs_long.csv`
(`snapshot_date,snapshot_utc,extension,install,update_count,download_count,version,
last_updated,avg_rating,rating_count`).

★★**이 파이프라인에서 유일하게 누락일을 영구 복구할 수 없는 소스다.**
  `install` 은 그 시점의 **누적 스톡**이고 마켓플레이스에 과거 조회 API 가 없다.
  데몬이 꺼져 있던 날은 나중에 어떤 방법으로도 채울 수 없다 — npm·OpenRouter 처럼
  "나중에 백필하면 되지"가 성립하지 않는다. 그래서 이 모듈은 값을 내는 것만큼이나
  **수집이 멈춘 것을 보이게 하는 일**을 한다:
    · `source.irrecoverable = true` (다른 소스는 false) → 화면이 다른 색으로 경고
    · `snapshots[]` 에 스냅샷마다 `snapshot_utc` → 데몬 심박
    · `gaps[]` 에 스냅샷이 빠진 날짜 → **그 날들은 영영 비어 있다**

⚠️**스톡이지 플로우가 아니다.** npm·토큰 카드의 `points` 와 뜻이 다르다 —
  저긴 "그 날 몇 번"이고 여긴 "그 날까지 총 몇 개"다. 그래서 계열을 둘로 나눈다:
    `stock` = 원값 누적곡선 (스냅샷 1개부터 그려진다)
    `delta` = 연속 스냅샷 차분 (**스냅샷 2개부터** 생긴다 — 1일치면 빈 배열 + note)

⚠️**음수 델타를 clip 하지 않는다.** MS 가 집계를 소급 정정해 누적값이 전일보다 줄어드는
  날이 생긴다. 0으로 자르면 되돌릴 수 없는 손실이고, 애초에 "MS 가 소급 정정했다"는
  사실 자체가 관측 대상이다. 원값을 그대로 내리고 `delta_marks[i].negative` 와
  `revisions[]` 로 표시만 한다. (수집기도 같은 원칙으로 원값만 적는다.)

⚠️스냅샷 사이에 구멍이 있으면 그 델타는 하루치가 아니다 → `delta_marks[i].span_days`.
  1 이 아닌 값은 "일 증분"으로 읽으면 안 된다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from collector import ai_key_data_io as _io

SRC_PATH = os.environ.get(
    "VSCODE_INSTALLS_CSV", os.path.join(_io.RAW_DIR, "vscode_installs_long.csv")
)
_MEMBER = os.path.basename(SRC_PATH)
# snapshot_utc·version·rating 류는 있으면 싣고 없으면 null — 필수는 셋뿐이다.
_REQUIRED = ("snapshot_date", "extension", "install")

# ── 집계 파라미터 (사람이 고치는 곳) ────────────────────────────────────────
# 확장 목록은 여기에 적지 않는다 — 무엇을 받을지는 ws3 `agent\config.toml` 이 정본이라
# 두 곳에 적으면 조용히 어긋난다. 사람이 config 에 확장을 추가하면 다음 스냅샷부터
# 카드에 저절로 나타난다(npm 모듈과 같은 판단).
MAX_EXTENSIONS = 0        # 0 = 전부. 목록이 길어지면 여기서 자른다
UNIT = "installs"


# ── 순수 계산부 (파일 IO 없음 — 테스트는 여기를 겨눈다) ──────────────────────

def _short(ext: str) -> str:
    """`anthropic.claude-code` → `claude-code`. 발행자를 뗀 짧은 이름.

    ★표시 이름을 지어내지 않는다 — `name` 은 원본 ID 그대로 두고 짧은 쪽을 같이 준다.
      어느 걸 쓸지는 화면이 고른다.
    """
    return ext.split(".", 1)[1] if "." in ext else ext


def build_payload(
    rows: list[dict],
    asof: date | None = None,
    source: dict | None = None,
) -> dict:
    """스냅샷 행 → 카드 payload.

    `asof` 는 인자다 — 계산부 안에서 `today()` 를 부르지 않는다(고정 날짜 테스트).
    """
    out: dict = {
        "generated_at": _io.generated_at(),
        "asof": None,
        "note": None,
        "source": source,
        "unit": UNIT,
        "kind": "line",
        # ★payload 가 스스로 "이건 스톡이다" 라고 말한다 — 화면이 npm 카드와 같은 축으로
        #   그리지 않게. 두 값을 나란히 놓으면 단위가 다른 걸 겹치게 된다.
        "measure": "stock",
        "snapshots": [],
        "n_snapshots": 0,
        "gaps": [],
        "extensions": [],
        "revisions": [],
        "totals": {"install": None, "snapshot_date": None, "delta": [], "n_extensions": 0},
    }
    if asof is not None:
        rows = [r for r in rows if r["date"] <= asof]
    if not rows:
        return out

    # (날짜, 확장) 중복은 나중 행 채택 — 수집기가 같은 날 재실행하면 그 날 행을
    # 덮어쓰므로(멱등) 정상 경로에선 안 생기지만, 생겨도 조용히 두 배가 되지 않게 한다.
    cell: dict[tuple[date, str], dict] = {}
    utc: dict[date, str | None] = {}
    for r in rows:
        cell[(r["date"], r["extension"])] = r
        utc[r["date"]] = r.get("snapshot_utc") or utc.get(r["date"])

    days = sorted({d for d, _ in cell})
    last = days[-1]
    out["asof"] = last.isoformat()
    out["n_snapshots"] = len(days)
    out["snapshots"] = [
        {
            "date": d.isoformat(),
            # ⚠️데몬 심박. 파일 mtime 이 아니라 **수집 시점**이라 이게 진짜다.
            "utc": utc.get(d),
            "n_extensions": sum(1 for (dd, _) in cell if dd == d),
        }
        for d in days
    ]
    # ★영구 손실 구간. 이 날짜들은 나중에 어떤 방법으로도 채울 수 없다.
    present = set(days)
    out["gaps"] = [
        (days[0] + timedelta(days=i)).isoformat()
        for i in range((last - days[0]).days + 1)
        if (days[0] + timedelta(days=i)) not in present
    ]

    exts = sorted(
        {e for _, e in cell},
        key=lambda e: -(cell.get((last, e), {}).get("install") or 0),
    )
    if MAX_EXTENSIONS:
        exts = exts[:MAX_EXTENSIONS]

    total_stock: dict[date, int] = {}
    for e in exts:
        seen = [(d, cell[(d, e)]) for d in days if (d, e) in cell]
        stock = [[d.isoformat(), r["install"]] for d, r in seen]
        for d, r in seen:
            total_stock[d] = total_stock.get(d, 0) + r["install"]

        # ⚠️연속 스냅샷 차분. 스냅샷이 하나뿐이면 **빈 배열**이다 — 0을 만들어 내면
        #   "그 날 증가 0" 이라는 없는 관측이 생긴다.
        delta, marks, neg = [], [], 0
        for (d0, r0), (d1, r1) in zip(seen, seen[1:]):
            v = r1["install"] - r0["install"]
            span = (d1 - d0).days
            delta.append([d1.isoformat(), v])
            marks.append({"negative": v < 0, "span_days": span, "from": d0.isoformat()})
            if v < 0:
                neg += 1
                out["revisions"].append({
                    "extension": e, "date": d1.isoformat(), "delta": v,
                    "from": r0["install"], "to": r1["install"],
                })

        cur = seen[-1][1]
        out["extensions"].append({
            "key": _io.slug(e),
            "id": e,
            "name": e,              # ★원본 ID — 표시 이름을 지어내지 않는다
            "short": _short(e),
            "kind": "line",
            "install": cur["install"],
            "snapshot_date": seen[-1][0].isoformat(),
            "snapshot_utc": cur.get("snapshot_utc"),
            "version": cur.get("version"),
            "last_updated": cur.get("last_updated"),
            "update_count": cur.get("update_count"),
            "download_count": cur.get("download_count"),
            "avg_rating": cur.get("avg_rating"),
            "rating_count": cur.get("rating_count"),
            "stock": stock,
            "delta": delta,
            "delta_marks": marks,   # delta 와 1:1 (ARR 카드의 marks 와 같은 규약)
            "stats": {
                "last": cur["install"],
                "last_date": seen[-1][0].isoformat(),
                "n": len(seen),
                "delta_last": delta[-1][1] if delta else None,
                "delta_last_date": delta[-1][0] if delta else None,
                "negative_days": neg,
                "stale_days": (last - seen[-1][0]).days,
            },
        })

    tdays = sorted(total_stock)
    out["totals"] = {
        "install": total_stock[tdays[-1]],
        "snapshot_date": tdays[-1].isoformat(),
        "n_extensions": len(exts),
        "delta": [
            [d1.isoformat(), total_stock[d1] - total_stock[d0]]
            for d0, d1 in zip(tdays, tdays[1:])
        ],
    }

    if len(days) < 2:
        # ⚠️결함이 아니라 "아직 2일차가 아니다" 다. 화면은 이 문구를 그대로 띄우면 된다.
        out["note"] = (
            f"스냅샷이 {len(days)}일치뿐이라 증분(delta)을 아직 낼 수 없습니다 — "
            "설치수는 누적값이라 차분에 스냅샷 2개가 필요합니다. "
            "내일 수집분부터 자동으로 생깁니다."
        )
    return out


# ── CSV 판독 ────────────────────────────────────────────────────────────────

def _read_rows(path: str = SRC_PATH) -> list[dict]:
    """`vscode_installs_long.csv` → 스냅샷 행. 깨진 행은 건너뛴다.

    필수는 `snapshot_date`·`extension`·`install` 셋뿐이다 — 나머지 7열은 있으면 싣고
    없으면 null 이다. 마켓플레이스가 통계 필드를 바꿔도 카드가 죽지 않게.
    """
    tbl = _io.read_flat_csv(path)
    _io.require(tbl, _MEMBER, _REQUIRED)
    ix = {c: i for i, c in enumerate(tbl.columns)}

    def cell(r: list, name: str) -> str:
        i = ix.get(name)
        return r[i].strip() if i is not None and i < len(r) else ""

    out: list[dict] = []
    for r in tbl.rows:
        d = _io.to_date(cell(r, "snapshot_date"))
        v = _io.to_int(cell(r, "install"))
        ext = cell(r, "extension")
        if d is None or v is None or not ext:
            continue
        out.append({
            "date": d,
            "extension": ext,
            "install": v,
            "snapshot_utc": cell(r, "snapshot_utc") or None,
            "update_count": _io.to_int(cell(r, "update_count")),
            "download_count": _io.to_int(cell(r, "download_count")),
            "version": cell(r, "version") or None,
            "last_updated": cell(r, "last_updated") or None,
            "avg_rating": _io.to_num(cell(r, "avg_rating")),
            "rating_count": _io.to_int(cell(r, "rating_count")),
        })
    out.sort(key=lambda r: (r["date"], r["extension"]))
    return out


def build_vscode_installs(asof: date | None = None) -> dict:
    """CSV → 카드 payload 한 장. 결측·스키마 사유는 전부 200 + note 로 접는다."""
    src = _io.source_block("vscode", SRC_PATH, "vscode", asof)
    try:
        rows = _read_rows()
    except FileNotFoundError:
        out = build_payload([], asof, src)
        out["note"] = (
            f"아직 수집이 시작되지 않았습니다 — {SRC_PATH} 가 없습니다."
            " ★설치수는 누적 스톡이라 수집이 늦어진 날은 영구 복구할 수 없습니다."
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
    if not out["extensions"]:
        out["note"] = f"유효한 데이터 행이 0건입니다(총 {len(rows)}행) — {SRC_PATH}"
    return out
