import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.models import Asset
from app.schemas import AssetOut, AssetUpdateRequest

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])

# Settable classifications. CASH is a donut class sourced from account_balances, not
# an asset_type — it must never be assignable to a holding.
ALLOWED_ASSET_TYPES = {"STOCK", "BOND", "DERIVATIVE", "OTHER"}


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: str,
    body: AssetUpdateRequest,
    db: Session = Depends(get_db),
) -> Asset:
    """Manually set a holding's asset class.

    Kiwoom does not supply one, so the user maintains it here and the worker must
    preserve it across syncs (portfolio-detail-spec §2).
    """
    try:
        parsed_id = uuid.UUID(asset_id)
    except ValueError:
        raise AppError(400, "VALIDATION_ERROR", "Malformed asset id.", {"asset_id": asset_id})

    if body.asset_type not in ALLOWED_ASSET_TYPES:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "Invalid asset_type.",
            {"allowed": sorted(ALLOWED_ASSET_TYPES)},
        )

    asset = db.get(Asset, parsed_id)
    if asset is None:
        raise AppError(404, "ASSET_NOT_FOUND", "Asset not found.", {"asset_id": asset_id})

    asset.asset_type = body.asset_type
    db.commit()
    db.refresh(asset)
    return asset
