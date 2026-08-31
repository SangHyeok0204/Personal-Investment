"""[정책금리] — FOMC 결정 판독 (2026-08-27).

[AI Key Data] 카드의 데이터원. AI Key Data 프로젝트가 이벤트 스터디 입력으로
두고 있는 ``macro_releases.csv`` 에서 ``event=RATE`` 행(= FOMC 금리 결정)만 뽑는다.

파일은 세 종류(CPI · PCE · RATE)를 한 장에 담고 있는데 **의미와 단위가 다르다**:
CPI·PCE 의 actual 은 전월비 %(변화율), RATE 의 actual 은 정책금리 **수준**(%)이다.
한 차트에 섞으면 안 되므로 여기서는 RATE 만 낸다(물가 발표가 필요하면 같은 파서에
event 를 바꿔 한 줄 더 내면 된다).

★정책금리는 회의와 회의 사이에 그대로 유지된다 — 점을 선으로 이으면 실제로는 없던
  중간값이 생기므로 화면은 **계단(step)** 으로 그린다. 그래서 payload 는 결정 시점만
  담고, 계단으로 펴는 일은 화면이 한다.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

SRC_PATH = os.environ.get(
    "POLICY_RATE_CSV", "/srv/legacy/gpu_compute/macro_releases.csv"
)
EVENT = "RATE"


def build_payload(rows: list[tuple[date, float]]) -> dict:
    """[(결정일, 금리%)] → 카드 payload. 날짜 오름차순 전제(호출부가 정렬)."""
    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "unit": "%",
        "note": None,
        "asof": None,
        "last": None,
        "last_date": None,
        "chg_bp": None,         # 직전 결정 대비 변화폭(bp)
        "last_change_date": None,  # 마지막으로 '움직인' 회의
        "holds": 0,             # 그 뒤로 동결한 횟수
        "points": [],
    }
    if not rows:
        return out

    out["points"] = [[d.isoformat(), v] for d, v in rows]
    last_d, last_v = rows[-1]
    out["asof"] = last_d.isoformat()
    out["last"] = last_v
    out["last_date"] = last_d.isoformat()
    if len(rows) > 1:
        # 금리는 %로 오므로 bp 는 ×100. 0.25%p 인하 → -25bp.
        out["chg_bp"] = round((last_v - rows[-2][1]) * 100, 1)

    # 마지막으로 값이 바뀐 회의 + 그 뒤 동결 횟수 — "N회 연속 동결"의 근거.
    for i in range(len(rows) - 1, 0, -1):
        if rows[i][1] != rows[i - 1][1]:
            out["last_change_date"] = rows[i][0].isoformat()
            out["holds"] = len(rows) - 1 - i
            break
    else:
        out["holds"] = len(rows) - 1
    return out


def _read_rows(path: str = SRC_PATH) -> list[tuple[date, float]]:
    """CSV → [(결정일, 금리%)] 오름차순.

    한 번에 다 읽어 파싱한다(수십 행짜리 파일이라 캐시가 필요 없다).
    날짜·값이 깨진 행은 건너뛴다 — 한 줄 때문에 카드를 비우지 않는다."""
    with open(path, "rb") as f:
        blob = f.read()
    text = blob.decode("utf-8-sig", errors="replace")

    rows: list[tuple[date, float]] = []
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("event") or "").strip().upper() != EVENT:
            continue
        try:
            d = datetime.strptime((r.get("date") or "").strip(), "%Y-%m-%d").date()
            v = float((r.get("actual") or "").strip())
        except (ValueError, TypeError):
            continue
        rows.append((d, v))
    rows.sort()
    return rows


def build_policy_rate() -> dict:
    """CSV → 카드 payload 한 장.

    원천이 없으면 503 이 아니라 빈 payload + note 로 돌려준다 — compute_index 와
    같은 이유다(파일 결측을 503 으로 내면 화면이 "collector 에 못 닿았습니다"를
    띄워 엉뚱한 층을 의심하게 만든다)."""
    try:
        rows = _read_rows()
    except FileNotFoundError:
        out = build_payload([])
        out["note"] = f"원천 파일이 없습니다 — {SRC_PATH}"
        return out
    return build_payload(rows)
