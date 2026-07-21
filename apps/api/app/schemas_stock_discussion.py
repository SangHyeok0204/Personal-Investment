"""Pydantic 계약 for the 종토방(stock discussion) push-ingest + 읽기 서빙.

schemas.py 는 lan 작업으로 선수정된 파일이라 건드리지 않고 별도 모듈로 분리한다
(계획 §1.2 "prefer a NEW module file to avoid touching it").
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── 인제스트 입력 (개발 PC push worker → api) ─────────────────────────────
# 타임스탬프는 문자열로 받는다: naive 'YYYY-MM-DD HH:MM[:SS]' (KST 가정) 또는
# offset 포함 ISO. 라우터가 정규화(+09:00 부여, 파싱불가 post_date→raw 보존)한다.


class EtfIn(BaseModel):
    code: str
    name: str | None = None
    issuer: str | None = None
    category: str | None = None


class PostIn(BaseModel):
    src_id: int
    source: str
    post_id: str
    etf_code: str | None = None
    etf_name: str | None = None
    title: str | None = None
    content: str | None = None
    post_date: str | None = None
    post_date_raw: str | None = None
    author: str | None = None
    likes: int | None = None
    dislikes: int | None = None
    comments: int | None = None
    crawled_at: str
    sentiment: str | None = None
    sentiment_confidence: float | None = None
    sentiment_model: str | None = None
    sentiment_at: str | None = None


class SentimentUpdateIn(BaseModel):
    src_id: int
    source: str
    post_id: str
    etf_code: str | None = None
    sentiment: str
    sentiment_confidence: float | None = None
    sentiment_model: str | None = None
    sentiment_at: str | None = None


class SpyLabelIn(BaseModel):
    source: str
    author: str
    label: str | None = None
    reason: str | None = None
    stats: dict[str, Any] | None = None
    updated_at: str | None = None


class HealthIn(BaseModel):
    naver_last_ok: str | None = None
    naver_last_error: str | None = None
    naver_consec_errors: int | None = None
    toss_last_ok: str | None = None
    toss_last_error: str | None = None
    toss_consec_errors: int | None = None
    sentiment_labeled_total: int | None = None
    sentiment_cost_usd_total: float | None = None
    spy_labels_total: int | None = None


class IngestPayload(BaseModel):
    batch_id: str
    etfs: list[EtfIn] | None = None
    posts: list[PostIn] = Field(default_factory=list)
    sentiment_updates: list[SentimentUpdateIn] = Field(default_factory=list)
    spy_labels_full: list[SpyLabelIn] = Field(default_factory=list)
    health: HealthIn | None = None


# ── 인제스트 응답 ─────────────────────────────────────────────────────────


class IngestApplied(BaseModel):
    posts_upserted: int
    sentiment_upserted: int
    sentiment_unmatched: int
    spies_replaced: int
    spies_skipped: int


class IngestResponse(BaseModel):
    ok: bool
    applied: IngestApplied
    server_time: str


# ── 읽기 출력 (Postgres 서빙 → 프론트) ─────────────────────────────────────


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_id: int
    source: str | None
    post_id: str | None
    etf_code: str | None
    etf_name: str | None
    title: str | None
    content: str | None
    post_date: datetime | None
    post_date_raw: str | None
    author: str | None
    likes: int | None
    dislikes: int | None
    comments: int | None
    crawled_at: datetime | None
    sentiment: str | None
    sentiment_confidence: float | None
    sentiment_model: str | None
    sentiment_at: datetime | None
    ingested_at: datetime | None


class RecentOut(BaseModel):
    items: list[PostOut]
    total: int
    limit: int
    offset: int


class SpyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str | None
    author: str | None
    label: str | None
    reason: str | None
    stats: dict[str, Any] | None
    updated_at: datetime | None


class EtfOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str | None
    issuer: str | None
    category: str | None
    updated_at: datetime | None
