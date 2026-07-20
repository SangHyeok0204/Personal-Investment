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
    pct: float
    remaining_pct: float | None = None


class AiUsageAccountOut(BaseModel):
    account_num: int
    email: str | None = None
    plan: str | None = None
    captured_at: str | None = None
    age_seconds: float | None = None
    stale: bool
    items: list[AiUsageMeterOut] = []


class AiUsageOut(BaseModel):
    monitor_base_url: str
    reachable: bool
    error: str | None = None
    fetched_at: str
    claude: list[AiUsageAccountOut] = []
    codex: list[AiUsageAccountOut] = []
