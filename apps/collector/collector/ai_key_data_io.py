"""[AI Key Data] 판독 공용층 — 마운트에서 표 파일을 읽는다 (2026-08-28).

`compute_index.py` 가 세운 관례(env override 가능한 `SRC_PATH` · mtime+size 서명 캐시 ·
순수계산/IO 분리 · 판독 실패를 503 이 아니라 `note` 로)를 카드 넉 장이 공유하도록 뺀 층이다.
**카드 payload 는 여기서 만들지 않는다** — 여기까지가 "파일 IO" 다.

원천은 AI Key Data 프로젝트의 `input/raw` (`/srv/legacy/gpu_compute` :ro).

★Epoch zip 은 풀지 않는다. 마운트가 `:ro` 라 제자리 해제가 애초에 불가능하고, /tmp 로 풀면
  "원본 4장 + 사본 20장" 이라는 두 번째 진실의 원천이 생긴다. 비용도 문제가 안 된다 —
  실측으로 카드 셋이 실제로 읽는 CSV 4장 합계가 ~69ms(캐시 미스일 때만)다.

⚠️`utf-8-sig` + `newline=""` 는 방어가 아니라 **필수**다. 둘 다 실측 근거가 있다:
  - OpenRouter/npm CSV 는 BOM + CRLF 로 쓰인다(상류가 `encoding="utf-8-sig"`).
    BOM 을 놓치면 첫 열 이름이 `﻿date` 가 되어 조용히 깨진다.
  - Epoch CSV 의 `Notes`/`Selected Sources` 필드에 **임베디드 개행이 실재**한다
    (revenue_reports 65행 중 37행, data_centers 는 85행 전부). `newline=""` 없이 읽으면
    행이 조용히 늘어난다.

★스키마 드리프트 정책: **필수 컬럼 결측은 시끄럽게 실패(`SchemaError`), 새 컬럼은 무시.**
  Epoch 은 컬럼을 지우지 않고 접두어를 붙여 남기거나 파일마다 다른 이름을 쓴다
  (`(DEPRECATED) Training dataset size (datapoints)` 가 같은 zip 안의 증거). 그래서 소비 열만
  명시적으로 뽑고 whitelist 는 강제하지 않는다 — 강제하면 신규 열이 에러가 된다.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

_KST = timezone(timedelta(hours=9))

RAW_DIR = os.environ.get("AI_KEY_DATA_RAW", "/srv/legacy/gpu_compute")

# ws3 수집기가 쓰는 상태 파일. ★소프트 의존 — 배포 전에는 이 파일이 아예 없고,
#   없는 것이 정상 경로이지 오류가 아니다(§3.6). 카드는 이것 없이도 완전히 렌더된다.
STATUS_PATH = os.environ.get(
    "AI_KEY_DATA_FETCH_STATUS", os.path.join(RAW_DIR, "_fetch_status.json")
)


class SchemaError(RuntimeError):
    """필수 컬럼이 사라졌다 — 카드를 비우고 어떤 컬럼인지 note 로 사람에게 말한다."""


class Table(NamedTuple):
    """CSV 한 장. `columns` 는 행이 0건이어도 남는다(스키마 검사를 위해)."""

    columns: list[str]
    rows: list[dict]


# ── 출처·귀속 (사람이 고치는 곳) ─────────────────────────────────────────────
# Epoch zip 안의 README.md 에 라이선스와 인용문이 들어 있으나 **파싱하지 않는다**(형식이 바뀐다).
# 안정된 3요소만 상수로 두고 url 은 README 에서 실측한 값을 쓴다.
# ⚠️OpenRouter/npm 은 CC-BY 가 아니다. 라이선스가 파일에 동봉돼 있지 않으므로 `license` 는
#   **null 로 두고 출처만 싣는다** — 약관을 지어내지 않는다(대외 게재 전 확인은 사람 몫).
SOURCES: dict[str, dict] = {
    "ai_companies": {
        "name": "Epoch AI",
        "dataset": "Data on AI Companies",
        "url": "https://epoch.ai/data/ai-companies",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "citation": "Epoch AI, 'Data on AI Companies'. Published online at epoch.ai.",
    },
    "ai_chip_sales": {
        "name": "Epoch AI",
        "dataset": "Data on AI Chip Sales",
        "url": "https://epoch.ai/data/ai-chip-sales",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "citation": "Epoch AI, 'Data on AI Chip Sales'. Published online at epoch.ai.",
    },
    "data_centers": {
        "name": "Epoch AI",
        "dataset": "AI Data Centers",
        "url": "https://epoch.ai/data/ai-data-centers",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "citation": "Epoch AI, 'AI Data Centers'. Published online at epoch.ai.",
    },
    "openrouter": {
        "name": "OpenRouter",
        "dataset": "Rankings (daily token usage)",
        "url": "https://openrouter.ai/rankings",
        "license": None,      # ⚠️파일에 동봉돼 있지 않다. 지어내지 않는다.
        "license_url": None,
        "citation": "OpenRouter, daily model rankings.",
    },
    "npm": {
        "name": "npm registry",
        "dataset": "Package download counts",
        "url": "https://api.npmjs.org/downloads",
        "license": None,      # ⚠️위와 같은 이유
        "license_url": None,
        "citation": "npm registry download counts API.",
    },
    "vscode": {
        "name": "Visual Studio Marketplace",
        "dataset": "Extension install counts",
        "url": "https://marketplace.visualstudio.com/",
        "license": None,      # ⚠️위와 같은 이유
        "license_url": None,
        "citation": "Visual Studio Marketplace extension statistics.",
        # ★이 소스만 참이다. 설치수는 **시점 누적 스톡**이고 과거 조회 API 가 없어서
        #   수집이 멈춘 날은 **영영 채울 수 없다**. 다른 소스의 지연은 나중에 백필하면
        #   되지만 여기는 그게 성립하지 않는다 — 화면이 다른 색으로 구분해야 사용자가
        #   데몬을 즉시 되살린다.
        "irrecoverable": True,
    },
}


# ── 시각 ────────────────────────────────────────────────────────────────────

def now_kst() -> datetime:
    return datetime.now(_KST)


def today_kst() -> date:
    return datetime.now(_KST).date()


def generated_at() -> str:
    """payload 최상위 `generated_at` — compute_index 와 같은 포맷."""
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")


# ── 값 변환 ─────────────────────────────────────────────────────────────────

def to_date(value) -> date | None:
    """`%Y-%m-%d` 만 받는다. 실패하면 None — 호출부가 그 행을 건너뛴다.

    Epoch 의 감사 메타(`Created` 의 ISO8601Z, `Last Modified` 의 offset 표기)는
    소비하지 않으므로 여기서 다룰 필요가 없다.
    """
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def to_num(value) -> float | None:
    """숫자 또는 None. 빈칸·`N/A`·콤마 구분자를 흡수한다."""
    s = str(value or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def to_int(value) -> int | None:
    v = to_num(value)
    return None if v is None else int(v)


def is_true(value) -> bool:
    """Epoch 의 불리언 열은 `True` 또는 빈칸이다."""
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def strip_tag(value) -> tuple[str | None, str | None]:
    """`"Google #confident"` → `("Google", "confident")`.

    ⚠️data_centers 의 Owner/Users 는 99% 가 `#` 신뢰도 태그를 달고 온다. 이름으로 집계하려면
      떼야 하지만, 태그 자체가 정보이므로 **버리지 않고 분리해 보존**한다.
    """
    s = str(value or "").strip()
    if not s:
        return None, None
    name, _, tag = s.partition("#")
    return (name.strip() or None), (tag.strip() or None)


def slug(value) -> str:
    """표시 이름 → payload 키. 화면이 색·순서를 고정하는 데 쓴다."""
    out = "".join(c if c.isalnum() else "-" for c in str(value or "").strip().lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def moving_average(values: list, window: int) -> list:
    """단순 이동평균. **앞 (window-1) 개는 창이 안 차므로 None** — 잘라내지 않는다.

    ★하우스 선례: ADP 카드가 서버가 준 `ma12` 를 그대로 그린다. 평활은 데이터 소유자
      (collector) 쪽 판단이고, TS 로 옮기면 카드마다 복붙하게 된다.
    창 안에 None 이 하나라도 있으면 그 자리도 None 이다(없는 값을 0으로 세지 않는다).
    """
    out: list = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        win = values[i + 1 - window: i + 1]
        if any(v is None for v in win):
            out.append(None)
            continue
        out.append(sum(win) / window)
    return out


def quarter_ends(start: date, end: date) -> list[date]:
    """`start` 가 속한 분기말부터 `end` 이하 분기말까지."""
    out: list[date] = []
    y, q = start.year, (start.month - 1) // 3
    while True:
        m = q * 3 + 3
        d = date(y, m, 1) + timedelta(days=31)
        d = date(d.year, d.month, 1) - timedelta(days=1)
        if d > end:
            break
        out.append(d)
        q += 1
        if q == 4:
            q, y = 0, y + 1
    return out


def week_end(d: date) -> date:
    """그 날이 속한 주의 **일요일**(W-SUN 버킷 라벨)."""
    return d + timedelta(days=6 - d.weekday())


# ── 판독 (mtime+size 서명 캐시) ──────────────────────────────────────────────
# 키는 **파일 하나** 단위. zip 은 통째로 교체되므로 그게 자연스러운 경계이고, 한 zip 을
# 열면 그 zip 이 쓰는 멤버를 한 번에 다 읽는다(멤버별로 열면 중앙 디렉터리를 두 번 판다).
# ⚠️S: 는 SMB 라 mtime 해상도가 낮을 수 있어 size 를 같이 묶는다 — Epoch 재다운로드는
#   내용이 바뀌면 크기도 바뀐다(zip 4장 실측 크기 25KB~3.3MB, 전부 상이).
_CACHE: dict[str, dict] = {}


def _sig(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def read_zip_tables(path: str, members: tuple[str, ...]) -> dict[str, Table]:
    """zip 안의 CSV 들을 압축 상태 그대로 읽는다. `{멤버이름: Table}`.

    바이트를 통째로 읽어 `BytesIO` 로 여는 건 `compute_index.py:133-134` 와 같은 이유 —
    사람이 S: 쪽에서 파일을 덮어쓰는 순간과 겹칠 수 있다.
    열기·파싱에 실패하면 **직전 캐시를 그대로 낸다**(같은 idiom). 캐시도 없으면 올린다.

    멤버가 없으면 `KeyError` — Epoch 내보내기 구성이 바뀐 것이라 조용히 넘기면 안 된다.
    """
    import zipfile  # 지연 import — 순수 계산부 테스트가 이 층 없이 돌도록

    ent = _CACHE.get(path)
    sig = _sig(path)  # FileNotFoundError 는 호출부(build_xxx)가 note 로 접는다
    if ent and ent.get("sig") == sig and set(members) <= set(ent.get("tables", {})):
        return ent["tables"]

    with open(path, "rb") as f:
        blob = f.read()
    try:
        tables: dict[str, Table] = {}
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = set(zf.namelist())
            for m in members:
                if m not in names:
                    have = sorted(n for n in names if n.endswith(".csv"))
                    raise KeyError(f"{m!r} (zip 안 CSV 목록: {have})")
                with zf.open(m) as fh:
                    rd = csv.DictReader(
                        io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
                    )
                    rows = list(rd)
                    tables[m] = Table(list(rd.fieldnames or []), rows)
    except (zipfile.BadZipFile, OSError):
        if ent and ent.get("tables"):
            return ent["tables"]
        raise

    _CACHE[path] = {"sig": sig, "tables": tables}
    return tables


def read_flat_csv(path: str) -> Table:
    """평문 CSV 한 장. 열 수가 적고 행이 많은 파일(토큰 30,702행)을 겨눈 경로다.

    ⚠️`csv.DictReader` 로 3만 행을 dict 로 물화하면 214ms, 위치 인덱스로 훑으면 96ms(2.2배).
      그래서 `rows` 는 dict 가 아니라 **문자열 리스트**다 — `columns` 로 인덱스를 만들어 쓴다.
    """
    ent = _CACHE.get(path)
    sig = _sig(path)
    if ent and ent.get("sig") == sig and "flat" in ent:
        return ent["flat"]

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            columns = next(rd, [])
            rows = [r for r in rd if r]
    except OSError:
        if ent and "flat" in ent:
            return ent["flat"]
        raise

    tbl = Table([c.strip() for c in columns], rows)
    _CACHE[path] = {"sig": sig, "flat": tbl}
    return tbl


def read_flat_csv_dicts(path: str) -> Table:
    """평문 CSV 한 장 — `rows` 가 **dict** 다.

    ★`read_flat_csv` 와 일부러 갈라 둔다. 저쪽은 토큰 CSV(3만 행 x 3열)를 겨눠 행을
      리스트로 두고 위치 인덱스로 훑는다(실측 2.2배). 반면 Epoch 판독부는 열 **이름**으로
      접근하도록 쓰여 있어(`row["Current power (MW)"]`) dict 가 필요하다 —
      `read_zip_tables` 가 `csv.DictReader` 를 쓴 것과 같은 계약이고, 원천이 zip 에서
      평문 CSV 로 바뀌어도 판독부가 한 줄도 안 바뀌게 하려면 여기서 모양을 맞춰야 한다.
      Epoch 은 가장 큰 파일이 495행이라 dict 물화 비용이 문제가 되지 않는다.
    """
    ent = _CACHE.get(path)
    sig = _sig(path)          # FileNotFoundError 는 호출부(_load)가 note 로 접는다
    if ent and ent.get("sig") == sig and "dicts" in ent:
        return ent["dicts"]

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            rows = list(rd)
            tbl = Table([c.strip() for c in (rd.fieldnames or [])], rows)
    except OSError:
        if ent and "dicts" in ent:
            return ent["dicts"]
        raise

    _CACHE[path] = {"sig": sig, "dicts": tbl}
    return tbl


def require(table: Table, member: str, required: tuple[str, ...]) -> None:
    """필수 컬럼이 하나라도 없으면 크게 실패. 모르는 컬럼이 늘어난 건 신경 쓰지 않는다.

    조용히 0을 그리는 것보다 낫다 — 컬럼명이 note 에 그대로 찍히므로 고치는 사람이 바로 안다.
    """
    have = set(table.columns)
    missing = [c for c in required if c not in have]
    if missing:
        raise SchemaError(
            f"{member}: 필수 컬럼 결측 {missing} — 원천 스키마가 바뀌었습니다. "
            f"현재 컬럼 {len(have)}개 중 앞부분: {sorted(have)[:8]}"
        )


# ── 수집 상태 · 출처 블록 ───────────────────────────────────────────────────

def fetch_status(source_key: str) -> dict | None:
    """ws3 수집기의 `_fetch_status.json` 중 한 소스. **절대 예외를 올리지 않는다.**

    ★파일 부재·JSON 파싱 실패·키 누락 어느 경우도 None 이고, 그때 카드는 정상 렌더된다.
      이 파일이 카드의 필수 입력이 되면 안 된다(ws3 배포 전에는 존재하지 않는다).
    스키마는 `{"sources": {"npm": {...}}}` 이지만 최상위 평면 형태도 흡수한다.
    """
    try:
        with open(STATUS_PATH, "rb") as f:
            doc = json.loads(f.read().decode("utf-8-sig"))
        if not isinstance(doc, dict):
            return None
        src = doc.get("sources")
        if not isinstance(src, dict):
            src = doc
        ent = src.get(source_key)
        return ent if isinstance(ent, dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def source_block(
    source_key: str,
    path: str,
    status_key: str | None = None,
    asof: date | None = None,
) -> dict:
    """payload 의 `source` 블록. **null 이 될 수 없는 필드** — 데이터가 비어도 귀속은 남는다.

    ★`retrieved`(파일 mtime)와 `stale_days` 는 `_fetch_status.json` 과 **무관하게 항상** 채운다.
      파일시스템만 보면 구할 수 있는 값이라 ws3 가 없어도 staleness 표시가 죽지 않는다.
      (수집기는 "마지막 성공 시각"을 알고 mtime 은 "마지막으로 내용이 바뀐 시각"만 아는데,
       304 Not Modified 로 내용이 안 바뀌면 둘이 갈리므로 있으면 확실히 낫다.)
    """
    out = dict(SOURCES.get(source_key, {}))
    # ★항상 실어 보낸다(기본 False) — 화면이 `irrecoverable === true` 를 볼 때 "필드가
    #   없는 것"과 "복구 가능한 것"을 구분하려고 뒤지지 않게. 참인 소스는 vscode 뿐이다.
    out.setdefault("irrecoverable", False)
    out["retrieved"] = None
    out["stale_days"] = None
    try:
        mt = datetime.fromtimestamp(os.stat(path).st_mtime, _KST)
        out["retrieved"] = mt.strftime("%Y-%m-%d %H:%M:%S")
        out["stale_days"] = ((asof or today_kst()) - mt.date()).days
    except OSError:
        pass  # 파일이 없으면 note 가 이미 그 얘기를 한다 — 여기서 또 소리내지 않는다

    st = fetch_status(status_key) if status_key else None
    out["fetched_at"] = (st or {}).get("last_success_utc")
    out["fetch_ok"] = (st or {}).get("ok")
    out["latest_date"] = (st or {}).get("latest_date")
    return out
