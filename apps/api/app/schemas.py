import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TestJobRequest(BaseModel):
    payload: dict[str, Any] | None = None


class InternalJobRequest(BaseModel):
    job_type: str = Field(min_length=1)
    payload: dict[str, Any] | None = None


class CheckHogaEnvelope(BaseModel):
    """CHECK-agent 호가(orderbook) envelope v1. ``payload`` stays a loosely typed
    pass-through dict — the collector owns its shape, the api only validates the
    transport wrapper before forwarding."""

    schema_version: int
    source: str
    source_timestamp: str
    sent_at: str
    seq: int | None = None
    payload: dict[str, Any]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    status: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class JobLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    level: str
    step: str | None
    message: str
    # Field is emitted as "metadata" but read from the ORM ``meta`` attribute
    # (the physical column is "metadata"; SQLAlchemy reserves that attribute name).
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="meta")
    created_at: datetime


class JobDetailOut(JobOut):
    logs: list[JobLogOut] = []


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class JobStatsOut(BaseModel):
    total: int
    pending: int
    running: int
    success: int
    failed: int


class ImportCreateOut(BaseModel):
    job_id: uuid.UUID
    import_id: uuid.UUID
    original_filename: str


class AiUsageMeterOut(BaseModel):
    label: str
    subtitle: str | None = None
    # None = 소진율 판정 불가. 업스트림이 %를 산출하지 못하면 지어내지 않고 null 로
    # 보낸다 — 0% 로 그리면 조용히 틀린 값이 된다.
    pct: float | None = None
    remaining_pct: float | None = None


class AiUsageAccountOut(BaseModel):
    account_num: int
    email: str | None = None
    plan: str | None = None
    captured_at: str | None = None
    age_seconds: float | None = None
    stale: bool
    # '사용 크레딧'(초과분 과금) 토글. False 면 플랜 한도에서 그대로 멈춘다.
    # None = 판정 불가(스크래퍼가 스위치를 못 찾음 / codex 는 이 개념이 없음).
    extra_usage_enabled: bool | None = None
    items: list[AiUsageMeterOut] = []


class AiUsageOut(BaseModel):
    monitor_base_url: str
    reachable: bool
    error: str | None = None
    fetched_at: str
    claude: list[AiUsageAccountOut] = []
    codex: list[AiUsageAccountOut] = []


# ── LAN 대시보드 (lan-dashboard 이식) ────────────────────────────────────
# 필드명은 원본 프런트 계약(camelCase)을 그대로 유지한다.


class LanStatusOut(BaseModel):
    status: str  # online | offline | error | unknown
    responseTime: int | None = None
    error: str | None = None
    httpStatus: int | None = None
    lastChecked: str | None = None


class LanServerOut(BaseModel):
    id: str
    name: str
    host: str
    port: int
    protocol: str  # tcp | http | https | heartbeat
    description: str = ""
    group: str = ""
    key: str = ""  # heartbeat: 프로세스가 POST 하는 키
    maxAgeSec: int | None = None  # heartbeat: 이 초 넘게 수신 없으면 offline
    status: LanStatusOut


class LanServerIn(BaseModel):
    # host/port 는 heartbeat 타입엔 불필요해 기본값 허용 — 타입별 필수검증은 라우터가.
    name: str = Field(min_length=1)
    host: str = ""
    port: int = 0
    protocol: str = "tcp"
    description: str = ""
    group: str = ""
    key: str = ""
    maxAgeSec: int | None = None


class LanServerUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    protocol: str | None = None
    description: str | None = None
    group: str | None = None
    key: str | None = None
    maxAgeSec: int | None = None


class LanGroupIn(BaseModel):
    name: str


class LanSummaryOut(BaseModel):
    total: int
    online: int
    offline: int
    unknown: int
