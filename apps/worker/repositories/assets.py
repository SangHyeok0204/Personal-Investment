"""assets upsert (UNIQUE country + market + ticker)."""
import uuid

from sqlalchemy import text


def upsert_asset(conn, position):
    """Insert/update the asset row; returns its id (existing on conflict)."""
    return conn.execute(
        text(
            "INSERT INTO assets (id, country, market, ticker, name, asset_type, "
            "currency, is_active, created_at, updated_at) "
            "VALUES (:id, :country, :market, :ticker, :name, :asset_type, :currency, "
            "TRUE, now(), now()) "
            "ON CONFLICT (country, market, ticker) DO UPDATE SET "
            "name=EXCLUDED.name, asset_type=EXCLUDED.asset_type, "
            "currency=EXCLUDED.currency, is_active=TRUE, updated_at=now() "
            "RETURNING id"
        ),
        {
            "id": uuid.uuid4(),
            "country": position["country"],
            "market": position["market"],
            "ticker": position["ticker"],
            "name": position.get("asset_name"),
            "asset_type": position.get("asset_type"),
            "currency": position["currency"],
        },
    ).scalar_one()
