"""원천(SEC·Nasdaq·Yahoo…)과 worker 의 마지막 성공/실패를 `source_status` 에 적는다.

★실패를 **종류**로 나눈다(docs/plans/…integration…md §D-2):
  - "403"     SEC 는 UA 가 없거나 초당 10회를 넘으면 403 + IP 일시 차단
  - "429"     Yahoo·OpenFIGI 요청 제한
  - "timeout" ⚠️Nasdaq 은 막을 때 403 이 아니라 **응답 없이 붙잡는다** — 종류를
               안 나누면 "그냥 느렸다"로 읽혀 차단을 모르고 계속 두드린다
  - "other"   그 밖
화면(/data-operations)은 이 종류를 그대로 보여 준다.
"""
from __future__ import annotations

import json

from sqlalchemy import text

_UPSERT_OK = text(
    "INSERT INTO source_status (source, kind, last_ok_at, detail, updated_at) "
    "VALUES (:source, :kind, now(), CAST(:detail AS JSONB), now()) "
    "ON CONFLICT (source) DO UPDATE SET last_ok_at = now(), "
    "detail = COALESCE(EXCLUDED.detail, source_status.detail), updated_at = now()"
)
_UPSERT_ERROR = text(
    "INSERT INTO source_status (source, kind, last_error_at, last_error_kind, "
    "last_error_message, updated_at) "
    "VALUES (:source, :kind, now(), :error_kind, :message, now()) "
    "ON CONFLICT (source) DO UPDATE SET last_error_at = now(), "
    "last_error_kind = EXCLUDED.last_error_kind, "
    "last_error_message = EXCLUDED.last_error_message, updated_at = now()"
)


def classify_error(exc: BaseException | None = None, status_code: int | None = None) -> str:
    """예외나 HTTP 상태를 차단 신호 종류로. 모르면 "other"."""
    if status_code is None and exc is not None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code == 403:
        return "403"
    if status_code == 429:
        return "429"
    if exc is not None and "timeout" in type(exc).__name__.lower():
        return "timeout"
    return "other"


def record_ok(engine, source: str, kind: str = "source", detail: dict | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            _UPSERT_OK,
            {
                "source": source,
                "kind": kind,
                "detail": json.dumps(detail) if detail is not None else None,
            },
        )


def record_error(
    engine, source: str, error_kind: str, message: str, kind: str = "source"
) -> None:
    with engine.begin() as conn:
        conn.execute(
            _UPSERT_ERROR,
            {
                "source": source,
                "kind": kind,
                "error_kind": error_kind,
                # 원문 전체는 로그에 있다. 화면에는 앞부분만.
                "message": (message or "")[:500],
            },
        )


def mark_ok_if_tracked(engine, source: str) -> None:
    """이미 행이 있는 원천만 '성공'으로 갱신한다 — 행을 새로 만들지 않는다.

    ★2026-10-06: `job:{종류}` 행은 벽시계 상한에 걸릴 때만 생긴다. 다음 회차가 성공해도 아무도 지우지 않아
      수집 상태에 'timeout_wallclock' 경고가 계속 남았다(EARNINGS_REVENUE 10-06 07:21 성공 뒤에도).
    """
    with engine.begin() as conn:
        conn.execute(text("UPDATE source_status SET last_ok_at = now(), updated_at = now() WHERE source = :s"),
                     {"s": source})
