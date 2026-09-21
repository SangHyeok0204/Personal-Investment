"""assets upsert (UNIQUE country + market + ticker)."""
import uuid

from sqlalchemy import text

# 자산군(asset_type)은 사용자가 UI에서 직접 지정하는 값이다 (portfolio-detail-spec §2/§4).
# Kiwoom does not report it, so the worker only supplies the 'STOCK' default when a
# ticker is seen for the FIRST time. asset_type is deliberately ABSENT from the
# ON CONFLICT DO UPDATE list: including it would reset the user's classification
# (e.g. SGOV -> BOND) back to STOCK on the next sync and silently revert the 자산군 도넛.
#
# The other columns stay in DO UPDATE on purpose — Kiwoom remains the source of truth
# for name/currency, and keeping a real SET (rather than DO NOTHING) is also what makes
# `RETURNING id` yield the existing row on conflict.


def upsert_asset(conn, position):
    """Insert/update the asset row; returns its id (existing on conflict).

    NEVER overwrites asset_type — that column belongs to the user.
    """
    return conn.execute(
        text(
            "INSERT INTO assets (id, country, market, ticker, name, asset_type, "
            "currency, is_active, created_at, updated_at) "
            "VALUES (:id, :country, :market, :ticker, :name, :asset_type, :currency, "
            "TRUE, now(), now()) "
            "ON CONFLICT (country, market, ticker) DO UPDATE SET "
            "name=EXCLUDED.name, "
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
