import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Broker, BrokerageConnection, Job
from app.schemas import (
    BrokerageConnectionListOut,
    BrokerageConnectionOut,
    SyncTriggerOut,
)

router = APIRouter(prefix="/api/v1/brokerage-connections", tags=["brokerage"])

SYNC_JOB_TYPE = "SYNC_KIWOOM_PORTFOLIO"
_ACTIVE_STATUSES = ("PENDING", "RUNNING")


def _credentials_configured() -> bool:
    """Both Kiwoom keys present in the api settings (presence check only)."""
    return bool(settings.KIWOOM_APP_KEY and settings.KIWOOM_SECRET_KEY)


def _connection_out(conn: BrokerageConnection, broker_code: str) -> BrokerageConnectionOut:
    return BrokerageConnectionOut(
        id=conn.id,
        broker_code=broker_code,
        connection_name=conn.connection_name,
        environment=conn.environment,
        status=conn.status,
        last_connected_at=conn.last_connected_at,
        last_synced_at=conn.last_synced_at,
        last_error=conn.last_error,
        credentials_configured=_credentials_configured(),
    )


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise AppError(400, "VALIDATION_ERROR", "Malformed connection id.", {"id": value})


@router.get("", response_model=BrokerageConnectionListOut)
def list_connections(db: Session = Depends(get_db)) -> BrokerageConnectionListOut:
    rows = db.execute(
        select(BrokerageConnection, Broker.code)
        .join(Broker, BrokerageConnection.broker_id == Broker.id)
        .order_by(BrokerageConnection.created_at.asc())
    ).all()
    items = [_connection_out(conn, code) for conn, code in rows]
    return BrokerageConnectionListOut(items=items)


@router.get("/{connection_id}", response_model=BrokerageConnectionOut)
def get_connection(connection_id: str, db: Session = Depends(get_db)) -> BrokerageConnectionOut:
    parsed_id = _parse_uuid(connection_id)
    row = db.execute(
        select(BrokerageConnection, Broker.code)
        .join(Broker, BrokerageConnection.broker_id == Broker.id)
        .where(BrokerageConnection.id == parsed_id)
    ).first()
    if row is None:
        raise AppError(
            404, "CONNECTION_NOT_FOUND", "Connection not found.", {"id": connection_id}
        )
    conn, code = row
    return _connection_out(conn, code)


@router.post("/{connection_id}/sync", response_model=SyncTriggerOut)
def trigger_sync(
    connection_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> SyncTriggerOut:
    parsed_id = _parse_uuid(connection_id)

    conn = db.get(BrokerageConnection, parsed_id)
    if conn is None:
        raise AppError(
            404, "CONNECTION_NOT_FOUND", "Connection not found.", {"id": connection_id}
        )

    # Reuse an in-flight sync for the same connection rather than queueing a duplicate.
    existing = db.execute(
        select(Job)
        .where(
            Job.job_type == SYNC_JOB_TYPE,
            Job.status.in_(_ACTIVE_STATUSES),
            Job.payload["connection_id"].astext == str(parsed_id),
        )
        .order_by(Job.created_at.desc())
    ).scalars().first()
    if existing is not None:
        response.status_code = 200
        return SyncTriggerOut(job_id=existing.id, status=existing.status, reused=True)

    job = Job(
        job_type=SYNC_JOB_TYPE,
        status="PENDING",
        payload={"connection_id": str(parsed_id), "force_refresh": False},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    response.status_code = 202
    return SyncTriggerOut(job_id=job.id, status="PENDING", reused=False)
