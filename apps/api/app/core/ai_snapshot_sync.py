"""AI Key Data 스냅샷 따라잡기 — VS Code·PyPI 를 하루 한 번 `ai_metric_snapshot` 에 (계획 S5, §12-3).

[따라잡기] `seasonality_sync` 와 같은 방식 — 정각 타이머가 아니라 "오늘(KST) 행이 없으면
지금 찍는다". 맥이 자고 있었어도 깨는 순간 찍는다.
  - 같은 날 재실행은 덮어쓴다(업서트).
  - 실패하면 1시간 뒤 다시(마켓·pypistats 를 30분마다 두드리지 않게).
  - 성공/실패는 `source_status`(ai_vscode·ai_pypi)에 → /data-operations.

⚠️VS Code 는 누적치만 준다 — 놓친 날은 **복구할 수 없다**. 이 루프의 안정성이 곧 이력이다.
⚠️원값만 적는다. 음수 델타(마켓 집계 정정)도 그대로 둔다 — 차분·clip 은 읽는 쪽 몫.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models import AiMetricSnapshot

_WORKER_DIR = Path(__file__).resolve().parents[3] / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

from prices.ai_sources import config as ai_config  # noqa: E402
from prices.ai_sources import pypi as pypi_source  # noqa: E402
from prices.ai_sources import vscode as vscode_source  # noqa: E402

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
CHECK_INTERVAL_SECONDS = 30 * 60
RETRY_AFTER_SECONDS = 60 * 60
STARTUP_DELAY_SECONDS = 60
SOURCES = ("vscode", "pypi")

_last_attempt: dict[str, float] = {}

_UPSERT_OK = text(
    "INSERT INTO source_status (source, kind, last_ok_at, detail, updated_at) "
    "VALUES (:source, 'source', now(), CAST(:detail AS JSONB), now()) "
    "ON CONFLICT (source) DO UPDATE SET last_ok_at = now(), "
    "detail = COALESCE(EXCLUDED.detail, source_status.detail), updated_at = now()"
)
_UPSERT_ERROR = text(
    "INSERT INTO source_status (source, kind, last_error_at, last_error_kind, last_error_message, updated_at) "
    "VALUES (:source, 'source', now(), :error_kind, :message, now()) "
    "ON CONFLICT (source) DO UPDATE SET last_error_at = now(), "
    "last_error_kind = EXCLUDED.last_error_kind, "
    "last_error_message = EXCLUDED.last_error_message, updated_at = now()"
)


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


def error_kind(exc: BaseException) -> str:
    """source_health.classify_error 와 같은 분류(403/429/timeout/other)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (403, 429):
        return str(status)
    if "timeout" in type(exc).__name__.lower():
        return "timeout"
    return "other"


def record_ok(db, source: str, detail: dict | None = None) -> None:
    db.execute(_UPSERT_OK, {"source": source, "detail": json.dumps(detail) if detail is not None else None})
    db.commit()


def record_error(db, source: str, exc: BaseException, message: str | None = None) -> None:
    """message 를 주면 str(exc) 대신 그걸 저장한다(키가 든 URL 을 가린 문구 등). 분류는 exc 로."""
    text = str(exc) if message is None else message
    db.execute(_UPSERT_ERROR, {"source": source, "error_kind": error_kind(exc), "message": text[:500]})
    db.commit()


def upsert(db, source: str, rows: list[tuple[str, date, Decimal | int | float, dict | None]]) -> int:
    """(series, date, value, extra) 들을 업서트. 같은 (source, series, date) 는 덮어쓴다."""
    if not rows:
        return 0
    values = [
        {"source": source, "series": s, "date": d, "value": Decimal(str(v)), "extra": e}
        for s, d, v, e in rows
    ]
    stmt = insert(AiMetricSnapshot).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "series", "date"],
        set_={"value": stmt.excluded.value, "extra": stmt.excluded.extra},
    )
    db.execute(stmt)
    db.commit()
    return len(values)


def vscode_rows(parsed: list[dict], day: date) -> list[tuple[str, date, int, dict]]:
    return [
        (r["extension"], day, r["install"], {k: v for k, v in r.items() if k not in ("extension", "install")})
        for r in parsed
    ]


def pypi_rows(parsed: dict[str, dict], day: date) -> list[tuple[str, date, int, dict]]:
    return [
        (pkg, day, r["last_day"], {"last_week": r.get("last_week"), "last_month": r.get("last_month")})
        for pkg, r in parsed.items()
    ]


def has_snapshot(db, source: str, day: date) -> bool:
    return bool(
        db.execute(
            select(func.count()).select_from(AiMetricSnapshot).where(
                AiMetricSnapshot.source == source, AiMetricSnapshot.date == day
            )
        ).scalar()
    )


def snapshot(db, source: str, day: date | None = None) -> int:
    """한 소스를 지금 찍어 적는다. 실패는 예외 그대로(호출 쪽이 기록)."""
    day = day or today_kst()
    if source == "vscode":
        rows = vscode_rows(vscode_source.fetch([e for e, _ in ai_config.VSCODE_EXTENSIONS]), day)
        detail: dict = {"extensions": len(rows)}
    elif source == "pypi":
        got = pypi_source.fetch([p for p, _ in ai_config.PYPI_PACKAGES])
        rows = pypi_rows(got["rows"], day)
        detail = {"packages": len(rows), "skipped": got["skipped"], "failed": got["failed"]}
    else:
        raise ValueError(source)
    n = upsert(db, source, rows)
    record_ok(db, f"ai_{source}", {**detail, "latest_date": day.isoformat()})
    return n


def run_once(now: datetime | None = None, *, force: bool = False) -> dict[str, int | str]:
    """오늘 행이 없는 소스만 찍는다. → {source: 적은 행수 | 'skip' | 'error'}."""
    day = today_kst(now)
    out: dict[str, int | str] = {}
    with SessionLocal() as db:
        for source in SOURCES:
            if not force and has_snapshot(db, source, day):
                out[source] = "skip"
                continue
            last = _last_attempt.get(source)
            if not force and last is not None and time.monotonic() - last < RETRY_AFTER_SECONDS:
                out[source] = "skip"
                continue
            _last_attempt[source] = time.monotonic()
            try:
                out[source] = snapshot(db, source, day)
            except Exception as exc:  # noqa: BLE001 — 원천 하나가 죽어도 다른 소스는 돈다
                db.rollback()
                logger.exception("ai snapshot %s failed", source)
                record_error(db, f"ai_{source}", exc)
                out[source] = "error"
    return out


async def ai_snapshot_sync_loop() -> None:
    # 기동 직후엔 쉰다 — --reload 재시작·테스트 TestClient 마다 외부 원천을 두드리지 않게.
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if any(v != "skip" for v in result.values()):
                logger.info("ai snapshot: %s", result)
        except Exception:
            logger.exception("ai snapshot sync check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def read(db, source: str) -> list[AiMetricSnapshot]:
    return list(
        db.execute(
            select(AiMetricSnapshot)
            .where(AiMetricSnapshot.source == source)
            .order_by(AiMetricSnapshot.series, AiMetricSnapshot.date)
        ).scalars()
    )
