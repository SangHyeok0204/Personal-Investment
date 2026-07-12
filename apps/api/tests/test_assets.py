import uuid

from app.models import Asset


def _make_asset(db, ticker="005930", asset_type="STOCK", country="KR", market="KRX"):
    asset = Asset(
        country=country,
        market=market,
        ticker=ticker,
        name=ticker,
        asset_type=asset_type,
        currency="KRW" if country == "KR" else "USD",
    )
    db.add(asset)
    db.commit()
    return asset


def test_patch_asset_type(client, db):
    asset = _make_asset(db, ticker="SGOV", country="US", market="US")

    response = client.patch(f"/api/v1/assets/{asset.id}", json={"asset_type": "BOND"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(asset.id)
    assert body["ticker"] == "SGOV"
    assert body["asset_type"] == "BOND"

    db.expire_all()
    assert db.get(Asset, asset.id).asset_type == "BOND"


def test_patch_asset_accepts_every_valid_class(client, db):
    asset = _make_asset(db, ticker="TSL", country="US", market="US")
    for asset_type in ("BOND", "DERIVATIVE", "OTHER", "STOCK"):
        response = client.patch(
            f"/api/v1/assets/{asset.id}", json={"asset_type": asset_type}
        )
        assert response.status_code == 200
        assert response.json()["asset_type"] == asset_type


def test_patch_asset_invalid_type(client, db):
    asset = _make_asset(db)
    response = client.patch(f"/api/v1/assets/{asset.id}", json={"asset_type": "CRYPTO"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_asset_rejects_cash(client, db):
    """CASH is a donut class sourced from account_balances, never a holding's class."""
    asset = _make_asset(db)
    response = client.patch(f"/api/v1/assets/{asset.id}", json={"asset_type": "CASH"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    db.expire_all()
    assert db.get(Asset, asset.id).asset_type == "STOCK"  # left untouched


def test_patch_asset_not_found(client):
    response = client.patch(
        f"/api/v1/assets/{uuid.uuid4()}", json={"asset_type": "BOND"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_patch_asset_malformed_uuid(client):
    response = client.patch("/api/v1/assets/not-a-uuid", json={"asset_type": "BOND"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
