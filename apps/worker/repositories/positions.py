"""current_positions upsert (UNIQUE account_id + asset_id) + sold-row cleanup."""
import uuid

from sqlalchemy import text


def upsert_position(conn, account_id, asset_id, position, as_of, source_job_id):
    conn.execute(
        text(
            "INSERT INTO current_positions (id, account_id, asset_id, quantity, "
            "available_quantity, average_purchase_price, purchase_amount_local, "
            "current_price, market_value_local, unrealized_pnl_local, unrealized_return, "
            "exchange_rate, market_value_krw, unrealized_pnl_krw, as_of, source_job_id, "
            "created_at, updated_at) "
            "VALUES (:id, :account_id, :asset_id, :quantity, :available_quantity, "
            ":average_purchase_price, :purchase_amount_local, :current_price, "
            ":market_value_local, :unrealized_pnl_local, :unrealized_return, "
            ":exchange_rate, :market_value_krw, :unrealized_pnl_krw, :as_of, "
            ":source_job_id, now(), now()) "
            "ON CONFLICT (account_id, asset_id) DO UPDATE SET "
            "quantity=EXCLUDED.quantity, available_quantity=EXCLUDED.available_quantity, "
            "average_purchase_price=EXCLUDED.average_purchase_price, "
            "purchase_amount_local=EXCLUDED.purchase_amount_local, "
            "current_price=EXCLUDED.current_price, "
            "market_value_local=EXCLUDED.market_value_local, "
            "unrealized_pnl_local=EXCLUDED.unrealized_pnl_local, "
            "unrealized_return=EXCLUDED.unrealized_return, "
            "exchange_rate=EXCLUDED.exchange_rate, "
            "market_value_krw=EXCLUDED.market_value_krw, "
            "unrealized_pnl_krw=EXCLUDED.unrealized_pnl_krw, "
            "as_of=EXCLUDED.as_of, source_job_id=EXCLUDED.source_job_id, updated_at=now()"
        ),
        {
            "id": uuid.uuid4(),
            "account_id": account_id,
            "asset_id": asset_id,
            "quantity": position["quantity"],
            "available_quantity": position.get("available_quantity"),
            "average_purchase_price": position.get("average_purchase_price"),
            "purchase_amount_local": position.get("purchase_amount_local"),
            "current_price": position.get("current_price"),
            "market_value_local": position.get("market_value_local"),
            "unrealized_pnl_local": position.get("unrealized_pnl_local"),
            "unrealized_return": position.get("unrealized_return"),
            "exchange_rate": position.get("exchange_rate"),
            "market_value_krw": position.get("market_value_krw"),
            "unrealized_pnl_krw": position.get("unrealized_pnl_krw"),
            "as_of": as_of,
            "source_job_id": source_job_id,
        },
    )


def delete_absent_positions(conn, account_id, kept_asset_ids):
    """Delete current_positions for this account not seen in this sync (sold out)."""
    if kept_asset_ids:
        conn.execute(
            text(
                "DELETE FROM current_positions WHERE account_id=:account_id "
                "AND asset_id <> ALL(CAST(:kept AS uuid[]))"
            ),
            {"account_id": account_id, "kept": [str(a) for a in kept_asset_ids]},
        )
    else:
        conn.execute(
            text("DELETE FROM current_positions WHERE account_id=:account_id"),
            {"account_id": account_id},
        )
