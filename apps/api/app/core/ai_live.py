"""AI Key Data v2 — 소스별 응답 조립 + 모듈 메모리 캐시 (계획 S5, §12-3).

  라이브(과거를 매번 다시 받을 수 있음): npm · ramp · openrouter · tool_calling · epoch
    → 6h 캐시. 실패하면 **마지막 정상값(last-good)** 을 status="stale" 로 돌려준다.
      캐시가 비어 있을 때의 실패는 10분 동안 다시 두드리지 않는다(OpenRouter 500/일 보호).
    → Epoch 은 6h 마다 ETag 로 확인만 한다(304 면 받지 않는다).
  스냅샷(DB): vscode · pypi → `ai_metric_snapshot`(ai_snapshot_sync 가 적는다).

응답 모양은 소스와 상관없이 하나(`AiSourceOut`): series[{key,label,group,points}] + tables.
원천 fetch/parse 는 `apps/worker/prices/ai_sources/*` — 여기는 캐시와 모양만 맡는다.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.core import ai_snapshot_sync
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AiMetricSnapshot, SourceStatus

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices.ai_sources import config as cfg  # noqa: E402
from prices.ai_sources import epoch, npm, openrouter, ramp, tool_calling  # noqa: E402

logger = logging.getLogger(__name__)

TTL_SECONDS = 6 * 3600.0
FAIL_BACKOFF_SECONDS = 10 * 60.0
OPENROUTER_TOP = 10
OPENROUTER_RANK_WINDOW = 30
EPOCH_TOP_DC = 20
EPOCH_TOP_LABS = 8

LIVE = ("npm", "ramp", "openrouter", "tool_calling", "epoch")
SNAPSHOT = ("vscode", "pypi")
SOURCES = LIVE + SNAPSHOT

SOURCE_URLS = {
    "npm": "https://api.npmjs.org/downloads",
    "ramp": cfg.RAMP_URL,
    "openrouter": "https://openrouter.ai/rankings",
    "tool_calling": "https://openrouter.ai/rankings",
    "epoch": "https://epoch.ai/data",
    "vscode": "https://marketplace.visualstudio.com",
    "pypi": "https://pypistats.org",
}
ATTRIBUTION = {
    "npm": "npm registry download counts (api.npmjs.org)",
    "ramp": "Ramp AI Index (ramp.com/data/ai-index)",
    "openrouter": cfg.OPENROUTER_ATTRIBUTION,
    "tool_calling": cfg.OPENROUTER_ATTRIBUTION,
    "epoch": cfg.EPOCH_ATTRIBUTION,
    "vscode": "Visual Studio Marketplace",
    "pypi": "pypistats.org",
}


class _Slot:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.at: float | None = None          # 마지막 성공 시각(monotonic)
        self.fail_at: float | None = None     # 마지막 실패 시각(monotonic)
        self.payload: dict | None = None      # 마지막 정상 응답
        self.last_ok: datetime | None = None
        self.error: str | None = None
        self.state: dict = {}                 # 소스별 원자료(OpenRouter 원행, Epoch ETag·멤버)


_slots: dict[str, _Slot] = {name: _Slot() for name in LIVE}


def _pts(points) -> list[tuple[str, float]]:
    return [(d.isoformat() if isinstance(d, date) else str(d), float(v)) for d, v in points]


def _record(source: str, *, ok: bool, detail: dict | None = None, exc: BaseException | None = None) -> None:
    """라이브 소스도 source_status(ai_<source>)에 남긴다 → /data-operations. 실패해도 응답엔 영향 없음."""
    try:
        with SessionLocal() as db:
            if ok:
                ai_snapshot_sync.record_ok(db, f"ai_{source}", detail)
            else:
                ai_snapshot_sync.record_error(db, f"ai_{source}", exc or RuntimeError("unknown"))
    except Exception:  # noqa: BLE001
        logger.debug("source_status write failed for %s", source, exc_info=True)


# ── 소스별 빌더: 원천 → {series, tables, latest_date, as_of, note, extra, status?} ──

def _build_npm(slot: _Slot) -> dict:
    groups = [("cli", pkg, label) for pkg, label in cfg.NPM_CLI_PACKAGES] + [
        ("sdk", pkg, label) for pkg, label in cfg.NPM_SDK_PACKAGES
    ]
    got = npm.fetch_roster([(pkg, label) for _, pkg, label in groups])
    series = [
        {"key": pkg, "label": label, "group": group, "unit": "downloads",
         "points": _pts(sorted(got["series"][pkg].items()))}
        for group, pkg, label in groups
        if pkg in got["series"]
    ]
    cutoff = got["cutoff"]
    return {
        "series": series,
        "latest_date": cutoff.isoformat() if cutoff else None,
        "note": f"실패 패키지: {', '.join(got['failed'])}" if got["failed"] else None,
        "extra": {"cutoff": cutoff.isoformat() if cutoff else None, "failed": got["failed"]},
    }


def _build_ramp(slot: _Slot) -> dict:
    got = ramp.fetch()
    series = [{"key": "all", "label": "전체 도입률", "group": "overall", "unit": "%", "points": _pts(got["overall"])}]
    series += [
        {"key": vendor, "label": vendor, "group": "vendor", "unit": "%", "points": _pts(points)}
        for vendor, points in sorted(got["vendors"].items())
    ]
    return {"series": series, "latest_date": got["latest"].isoformat()}


def openrouter_series(rows: list[tuple[date, str, int]], top: int = OPENROUTER_TOP) -> tuple[list[dict], date | None]:
    """원행 → total + 최근 30일 상위 top 모델 + rest(top-50 안 나머지) + other(top-50 밖).

    ⚠️모델 결측은 "그날 51위 밖"이지 0 이 아니다 — 모델 계열은 점을 채우지 않는다.
    """
    if not rows:
        return [], None
    last = max(d for d, _, _ in rows)
    lo = last - timedelta(days=OPENROUTER_RANK_WINDOW - 1)
    recent: dict[str, int] = {}
    for d, slug, v in rows:
        if d >= lo and slug != "other":
            recent[slug] = recent.get(slug, 0) + v
    top_models = [s for s, _ in sorted(recent.items(), key=lambda t: -t[1])[:top]]
    top_set = set(top_models)
    total: dict[date, int] = {}
    per: dict[str, dict[date, int]] = {s: {} for s in top_models}
    rest: dict[date, int] = {}
    other: dict[date, int] = {}
    for d, slug, v in rows:
        total[d] = total.get(d, 0) + v
        if slug in top_set:
            per[slug][d] = per[slug].get(d, 0) + v
        elif slug == "other":
            other[d] = other.get(d, 0) + v
        else:
            rest[d] = rest.get(d, 0) + v
    series = [{"key": "total", "label": "전체", "group": "total", "unit": "tokens", "points": _pts(sorted(total.items()))}]
    series += [
        {"key": s, "label": s, "group": "model", "unit": "tokens", "points": _pts(sorted(per[s].items()))}
        for s in top_models
    ]
    series.append({"key": "rest", "label": f"top-50 중 상위 {top} 밖", "group": "residual", "unit": "tokens",
                   "points": _pts(sorted(rest.items()))})
    series.append({"key": "other", "label": "other(top-50 밖)", "group": "residual", "unit": "tokens",
                   "points": _pts(sorted(other.items()))})
    return series, last


def _build_openrouter(slot: _Slot) -> dict:
    got = openrouter.fetch(settings.OPENROUTER_API_KEY)
    if got["status"] == "key_missing":
        return {"status": "key_missing", "note": "OPENROUTER_API_KEY 미설정 — .env.local 에 넣고 API 재시작"}
    slot.state["rows"] = got["rows"]
    slot.state["as_of"] = got["as_of"]
    series, last = openrouter_series(got["rows"])
    return {
        "series": series,
        "latest_date": last.isoformat() if last else None,
        "as_of": got["as_of"],
        "note": "상위 50 모델 + other 버킷 — 전수집계 아님. 모델 결측은 51위 밖(0 아님).",
        "extra": {"start": got["start"].isoformat(), "end": got["end"].isoformat(), "rows": len(got["rows"])},
    }


def _build_tool_calling(slot: _Slot) -> dict:
    if not settings.OPENROUTER_API_KEY:
        return {"status": "key_missing", "note": "OPENROUTER_API_KEY 미설정 — .env.local 에 넣고 API 재시작"}
    # 전체 쪽은 openrouter 캐시를 재사용한다(같은 요청을 두 번 하지 않는다 — 500/일 한도).
    get("openrouter")
    total_rows = _slots["openrouter"].state.get("rows")
    if not total_rows:
        raise RuntimeError("tool_calling: openrouter 전체 시계열 없음")
    tool = openrouter.fetch(settings.OPENROUTER_API_KEY, modality="tool_calling")
    merged = tool_calling.merge(total_rows, tool["rows"])
    last = merged[-1] if merged else None
    as_of = max(filter(None, [_slots["openrouter"].state.get("as_of"), tool.get("as_of")]), default=None)
    return {
        "series": [
            {"key": "total", "label": "전체 토큰", "group": "total", "unit": "tokens",
             "points": _pts((d, t) for d, t, _ in merged)},
            {"key": "tool", "label": "tool_calling 토큰", "group": "tool", "unit": "tokens",
             "points": _pts((d, c) for d, _, c in merged)},
        ],
        "latest_date": last[0].isoformat() if last else None,
        "as_of": as_of,
        "extra": {"share_pct": round(last[2] / last[1] * 100, 2) if last and last[1] else None},
    }


def _refresh_epoch(slot: _Slot) -> list[str]:
    """데이터셋마다 ETag 로 확인. 실패한 데이터셋은 이전 것을 유지하고 메모를 남긴다."""
    notes: list[str] = []
    datasets: dict = slot.state.setdefault("datasets", {})
    for name, (url, members) in cfg.EPOCH_DATASETS.items():
        prev = datasets.get(name)
        try:
            got = epoch.fetch_zip(url, prev["etag"] if prev and prev.get("members") else None)
            if got["status"] == 304:
                continue
            parsed = epoch.extract_members(got["content"], members)
            counts = {m: len(rows) for m, rows in parsed.items()}
            bad = epoch.shrunk(prev["counts"] if prev else {}, counts)
            if bad:
                raise ValueError(f"행수 50% 미만으로 감소: {bad}")
            # ★전량 교체 — 병합하지 않는다.
            datasets[name] = {"etag": got["etag"], "members": parsed, "counts": counts,
                              "fetched_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{name}: {exc}")
    if not any(d.get("members") for d in datasets.values()):
        raise RuntimeError("epoch: 데이터셋 전부 실패 — " + "; ".join(notes))
    return notes


def _build_epoch(slot: _Slot) -> dict:
    notes = _refresh_epoch(slot)
    ds = slot.state["datasets"]
    member = lambda name, m: (ds.get(name) or {}).get("members", {}).get(m) or []  # noqa: E731
    series: list[dict] = []
    tables: list[dict] = []
    latest: date | None = None

    chips = epoch.chip_h100e_cumulative(member("ai_chip_sales", "timelines_by_chip.csv"))
    if chips["quarters"]:
        q = chips["quarters"]
        series.append({"key": "chip_total", "label": "누적 H100e(전체)", "group": "chip_h100e", "unit": "H100e",
                       "points": _pts(zip(q, chips["total"]))})
        for maker, acc in sorted(chips["by_maker"].items(), key=lambda t: -t[1][-1]):
            series.append({"key": f"chip:{maker}", "label": maker, "group": "chip_h100e", "unit": "H100e",
                           "points": _pts(zip(q, acc))})

    labs = epoch.lab_revenue_steps(member("ai_companies", "ai_companies_revenue_reports.csv"))
    ranked = sorted(labs.items(), key=lambda t: -t[1][-1][1])
    for company, points in ranked[:EPOCH_TOP_LABS]:
        series.append({"key": f"arr:{company}", "label": company, "group": "lab_arr", "unit": "USD",
                       "points": _pts(points)})
        latest = max(latest or points[-1][0], points[-1][0])
    if ranked:
        tables.append({"key": "lab_revenue", "label": "AI 랩 연환산 매출(최신)",
                       "columns": ["company", "date", "arr_usd", "reports"],
                       "rows": [{"company": c, "date": p[-1][0].isoformat(), "arr_usd": p[-1][1], "reports": len(p)}
                                for c, p in ranked]})

    dcs = epoch.top_data_centers(member("data_centers", "data_centers.csv"), EPOCH_TOP_DC)
    if dcs:
        tables.append({"key": "data_centers", "label": f"데이터센터 전력 상위 {EPOCH_TOP_DC}",
                       "columns": ["name", "owner", "users", "country", "power_mw", "h100e", "capex_busd"],
                       "rows": dcs})
    rounds = epoch.funding_rounds(member("ai_companies", "ai_companies_funding_rounds.csv"))
    if rounds:
        tables.append({"key": "funding_rounds", "label": "AI 랩 투자 라운드(최근)",
                       "columns": ["company", "date", "status", "equity_usd", "debt_usd", "valuation_usd", "type"],
                       "rows": rounds})

    return {
        "series": series,
        "tables": tables,
        "latest_date": latest.isoformat() if latest else None,
        "note": "; ".join(notes) or None,
        "extra": {
            "incomplete_quarters": [d.isoformat() for d in chips["incomplete"]],
            "datasets": {n: {"etag": d.get("etag"), "counts": d.get("counts"), "fetched_at": d.get("fetched_at")}
                         for n, d in ds.items()},
        },
    }


_BUILDERS = {
    "npm": _build_npm,
    "ramp": _build_ramp,
    "openrouter": _build_openrouter,
    "tool_calling": _build_tool_calling,
    "epoch": _build_epoch,
}


def _envelope(source: str, body: dict, status: str) -> dict:
    return {
        "source": source,
        "status": status,
        "series": body.get("series") or [],
        "tables": body.get("tables") or [],
        "as_of": body.get("as_of"),
        "latest_date": body.get("latest_date"),
        "source_url": SOURCE_URLS[source],
        "attribution": ATTRIBUTION[source],
        "note": body.get("note"),
        "extra": body.get("extra"),
    }


def get(source: str, *, refresh: bool = False) -> dict:
    """라이브 소스 한 개. 캐시(6h) → 새로 받기 → 실패면 last-good(stale)."""
    slot = _slots[source]
    with slot.lock:
        now = time.monotonic()
        if not refresh and slot.payload is not None and slot.at is not None and now - slot.at < TTL_SECONDS:
            return slot.payload
        if (not refresh and slot.payload is None and slot.fail_at is not None
                and now - slot.fail_at < FAIL_BACKOFF_SECONDS):
            return {**_envelope(source, {}, "error"), "note": f"갱신 실패(재시도 대기): {slot.error}"}
        try:
            body = _BUILDERS[source](slot)
        except Exception as exc:  # noqa: BLE001 — 원천 하나의 실패가 화면 전체를 깨지 않게
            logger.warning("ai %s fetch failed: %s", source, exc)
            slot.fail_at = now
            slot.error = f"{type(exc).__name__}: {exc}"[:300]
            _record(source, ok=False, exc=exc)
            if slot.payload is not None:
                # last-good 유지. 15분 뒤 다시 시도하도록 캐시 시각을 당겨 둔다.
                slot.at = now - TTL_SECONDS + 15 * 60
                when = f"{slot.last_ok:%Y-%m-%d %H:%M} UTC" if slot.last_ok else "시각 미상"
                return {**slot.payload, "status": "stale",
                        "note": f"갱신 실패 — 마지막 정상값({when}) 표시: {slot.error}"}
            return {**_envelope(source, {}, "error"), "note": slot.error}
        status = body.pop("status", None) or ("ok" if body.get("series") or body.get("tables") else "empty")
        payload = _envelope(source, body, status)
        stamp = datetime.now(timezone.utc)
        payload["fetched_at"] = stamp
        if status == "ok":
            slot.last_ok = stamp
            _record(source, ok=True, detail={"latest_date": payload["latest_date"], "as_of": payload["as_of"],
                                             "series": len(payload["series"]), "tables": len(payload["tables"])})
        payload["last_ok"] = slot.last_ok
        slot.payload, slot.at, slot.error = payload, now, None
        return payload


# ── 스냅샷 소스(DB) ──────────────────────────────────────────────────────────

def snapshot_payload(db, source: str) -> dict:
    """ai_metric_snapshot → 응답. vscode: 누적 설치 + 스냅샷 간 증분(음수 그대로). pypi: last_day·last_month."""
    rows = ai_snapshot_sync.read(db, source)
    labels = dict(cfg.VSCODE_EXTENSIONS if source == "vscode" else cfg.PYPI_PACKAGES)
    by: dict[str, list[AiMetricSnapshot]] = {}
    for r in rows:
        by.setdefault(r.series, []).append(r)
    series: list[dict] = []
    for key, items in by.items():
        label = labels.get(key, key)
        if source == "vscode":
            series.append({"key": key, "label": label, "group": "install", "unit": "installs",
                           "points": _pts((r.date, r.value) for r in items)})
            # ★차분은 읽는 쪽 몫. 음수(마켓 정정)도 그대로 둔다. 빠진 날은 건너뛴 구간 전체의 증분이다.
            series.append({"key": f"{key}:delta", "label": f"{label} 증분", "group": "delta", "unit": "installs",
                           "points": _pts((b.date, b.value - a.value) for a, b in zip(items, items[1:]))})
        else:
            series.append({"key": key, "label": label, "group": "last_day", "unit": "downloads",
                           "points": _pts((r.date, r.value) for r in items)})
            month = [(r.date, (r.extra or {}).get("last_month")) for r in items]
            series.append({"key": f"{key}:month", "label": f"{label} 최근 30일", "group": "last_month",
                           "unit": "downloads", "points": _pts((d, v) for d, v in month if v is not None)})
    latest = max((r.date for r in rows), default=None)
    ss = db.get(SourceStatus, f"ai_{source}")
    note = None
    if ss is not None and ss.last_error_at and (not ss.last_ok_at or ss.last_error_at > ss.last_ok_at):
        note = f"마지막 스냅샷 실패({ss.last_error_kind}): {ss.last_error_message}"
    if not rows:
        note = note or "아직 스냅샷이 없습니다 — 수집 루프가 하루 한 번 적재합니다."
    return {
        **_envelope(source, {"series": series, "latest_date": latest.isoformat() if latest else None, "note": note},
                    "ok" if rows else "empty"),
        "last_ok": ss.last_ok_at if ss else None,
        "fetched_at": ss.last_ok_at if ss else None,
    }


def status(db) -> list[dict]:
    """소스별 상태. **원천을 부르지 않는다** — 캐시·DB 만 본다."""
    rows = {r.source: r for r in db.execute(
        select(SourceStatus).where(SourceStatus.source.in_([f"ai_{s}" for s in SOURCES]))
    ).scalars()}
    out: list[dict] = []
    key_missing = not settings.OPENROUTER_API_KEY
    for source in LIVE:
        slot = _slots[source]
        ss = rows.get(f"ai_{source}")
        payload = slot.payload
        st = payload["status"] if payload else ("key_missing" if key_missing and source in ("openrouter", "tool_calling") else "unknown")
        # 콜드 스타트: 첫 조회가 원천을 받는 중이면(락 보유) "미확인"이 아니라 "조회 중"이다.
        if st == "unknown" and not slot.error and slot.lock.locked():
            st = "fetching"
        if slot.error and payload is not None:
            st = "stale"
        elif slot.error:
            st = "error"
        out.append({
            "source": source,
            "status": st,
            "ok": st == "ok",
            "fetched": payload is not None,
            "last_ok": slot.last_ok or (ss.last_ok_at if ss else None),
            "latest_date": (payload or {}).get("latest_date") or ((ss.detail or {}).get("latest_date") if ss else None),
            "note": slot.error or (payload or {}).get("note"),
            "as_of": (payload or {}).get("as_of"),
            "key_missing": key_missing and source in ("openrouter", "tool_calling"),
        })
    latest = dict(db.execute(
        select(AiMetricSnapshot.source, func.max(AiMetricSnapshot.date))
        .where(AiMetricSnapshot.source.in_(SNAPSHOT)).group_by(AiMetricSnapshot.source)
    ).all())
    for source in SNAPSHOT:
        ss = rows.get(f"ai_{source}")
        failing = bool(ss and ss.last_error_at and (not ss.last_ok_at or ss.last_error_at > ss.last_ok_at))
        has = source in latest
        st = "error" if failing else ("ok" if has else "empty")
        out.append({
            "source": source,
            "status": st,
            "ok": st == "ok",
            "fetched": True,
            "last_ok": ss.last_ok_at if ss else None,
            "latest_date": latest[source].isoformat() if has else None,
            "note": (ss.last_error_message if failing else None),
            "as_of": None,
            "key_missing": False,
        })
    return out
