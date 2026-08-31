r"""[AI Key Data] OpenRouter tool-calling 토큰 판독 (2026-08-31).

원천은 수집기 `agent\fetchers\tool_calling.py` 가 굽는 `tool_calling_long.csv` —
`date,total_tokens,tool_calling_tokens` 3열 고정. 같은 rankings-daily 를 필터 없이 한 번,
`modality=tool_calling` 으로 한 번 쳐서 얻은 **원값 두 개**다.

★★차트에 **비중(tool/total)을 그리지 않는다.** 598일 내내 99.28~99.46% 라 사실상 상수다
  (원본 xlsx 실측, 2026-08-31 재확인). OpenRouter 의 `tool_calling` 은 "툴콜을 실제로 쓴
  요청"이 아니라 "툴콜을 지원하는 모델" 쪽에 가까워서, 비중을 그리면 평평한 99% 직선이
  나오고 아무것도 안 보인다. 움직이는 건 아래 둘이다:
    · ratio      = tool / non_tool   — 실측 137~185배 구간에서 실제로 변동
    · non_tool   = total - tool      — 71B~93B 구간에서 변동
  비중은 `stats.share_pct` 로 숫자 한 개만 남긴다(맥락용, 차트 아님).

⚠️non_tool 이 0 이면 ratio 를 만들 수 없다 — 그 날은 **점을 건너뛴다**(0 이나 inf 로
  채우지 않는다). 그래야 화면이 선을 끊는다.
"""
from __future__ import annotations

import os
from datetime import date

from collector import ai_key_data_io as _io

SRC_PATH = os.environ.get(
    "TOOL_CALLING_CSV", os.path.join(_io.RAW_DIR, "tool_calling_long.csv")
)
_REQ = ("date", "total_tokens", "tool_calling_tokens")


def build_payload(table, asof: date | None, src: dict) -> dict:
    out: dict = {
        "generated_at": _io.generated_at(),
        "asof": None,
        "unit": "tokens",
        "kind": "line",
        "source": src,
        "series": [],
        "stats": None,
    }
    if table is None:
        return out
    _io.require(table, os.path.basename(SRC_PATH), _REQ)
    idx = {c: i for i, c in enumerate(table.columns)}

    rows: list[tuple[str, int, int]] = []
    for r in table.rows:
        d = _io.to_date(r[idx["date"]])
        if d is None or (asof and d > asof):
            continue
        t = _io.to_int(r[idx["total_tokens"]])
        c = _io.to_int(r[idx["tool_calling_tokens"]])
        if t is None or c is None:
            continue
        rows.append((d.isoformat(), t, c))
    if not rows:
        return out
    rows.sort()

    ratio: list[list] = []
    non_tool: list[list] = []
    for d, t, c in rows:
        nt = t - c
        non_tool.append([d, nt])
        if nt > 0:                      # ⚠️0 이면 배수가 정의되지 않는다 - 점을 건너뛴다
            ratio.append([d, round(c / nt, 2)])

    last_d, last_t, last_c = rows[-1]
    last_nt = last_t - last_c
    out["asof"] = last_d
    out["series"] = [
        {"key": "ratio", "label": "tool / non-tool (배수)", "unit": "x", "points": ratio},
        {"key": "non_tool", "label": "non-tool 토큰", "unit": "tokens", "points": non_tool},
    ]
    out["stats"] = {
        "last_date": last_d,
        "total": last_t,
        "tool": last_c,
        "non_tool": last_nt,
        "ratio": round(last_c / last_nt, 2) if last_nt > 0 else None,
        # 맥락용 숫자 한 개. ★차트로 쓰지 말 것 - 사실상 상수다(위 §참조).
        "share_pct": round(last_c / last_t * 100, 2) if last_t else None,
        "n": len(rows),
    }
    return out


def build_tool_calling(asof: date | None = None) -> dict:
    asof = asof or _io.today_kst()
    src = _io.source_block("openrouter", SRC_PATH, "tool_calling", asof)
    try:
        table = _io.read_flat_csv(SRC_PATH)
    except FileNotFoundError:
        out = build_payload(None, asof, src)
        out["note"] = (f"아직 수집이 시작되지 않았습니다 - {SRC_PATH} 가 없습니다 "
                       f"(`ai_key_data.bat` 을 한 번 돌리면 생깁니다)")
        return out
    except OSError as exc:
        out = build_payload(None, asof, src)
        out["note"] = f"원천 파일을 읽지 못했습니다({exc.__class__.__name__}) - {SRC_PATH}"
        return out
    try:
        return build_payload(table, asof, src)
    except _io.SchemaError as exc:
        out = build_payload(None, asof, src)
        out["note"] = str(exc)
        return out
