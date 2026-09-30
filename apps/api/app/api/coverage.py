"""데이터 보유 현황판 API (계획 S8 · §6, §12-8 레인 C) — 4개 리서치 화면 공통 패널이 쓴다.

`app/core/coverage.py` 의 읽기 전용 집계를 그대로 감싼다. 계산은 하지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import coverage as cov
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/research/coverage", tags=["coverage"])

Kind = Literal["stocks", "guru", "earnings", "filings"]


class CoverageKpi(BaseModel):
    label: str
    value: str
    hint: str | None = None


class CoverageSource(BaseModel):
    source: str
    last_ok_at: datetime | None
    last_error_at: datetime | None
    last_error_kind: str | None
    stale: bool


class CoverageTableRow(BaseModel):
    key: str
    label: str
    link: str | None = None
    #: 히트맵/표 셀. 숫자(건수) · bool(제출 여부) · 문자열(상태) · None(대상 아님/모름) 이 섞인다.
    cells: list[str | int | float | bool | None]


class CoverageTable(BaseModel):
    columns: list[str]
    rows: list[CoverageTableRow]


class CoverageResponse(BaseModel):
    kind: Kind
    generated_at: datetime
    kpis: list[CoverageKpi]
    table: CoverageTable
    sources: list[CoverageSource]
    #: 알려진 데이터 이상치(§6) — 표시만, 고치지 않는다.
    anomalies: list[str] = []
    notes: list[str] = []


@router.get("/{kind}", response_model=CoverageResponse)
def get_coverage(kind: Kind, db: Session = Depends(get_db)) -> CoverageResponse:
    # kind 는 Literal 이라 FastAPI 가 유효하지 않은 값을 422 로 먼저 걸러 준다.
    data = cov.build(kind, db)
    return CoverageResponse(kind=kind, generated_at=datetime.now(timezone.utc), **data)
