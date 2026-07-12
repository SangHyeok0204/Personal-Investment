from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["system"])


@router.get("/system/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Report database connectivity. Always returns HTTP 200."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "error", "database": "disconnected"}
