"""portfolio_snapshots + position_snapshots inserts (append-only history)."""
import uuid

from sqlalchemy import text


def insert_portfolio_snapshot(conn, account_id, snapshot, snapshot_at, source_job_id):
    snapshot_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO portfolio_snapshots (id, account_id, snapshot_at, base_currency, "
            "cash_value_krw, securities_value_krw, total_assets_krw, "
            "total_purchase_amount_krw, total_unrealized_pnl_krw, source_job_id, created_at) "
            "VALUES (:id, :account_id, :snapshot_at, :base_currency, :cash_value_krw, "
            ":securities_value_krw, :total_assets_krw, :total_purchase_amount_krw, "
            ":total_unrealized_pnl_krw, :source_job_id, now())"
        ),
        {
            "id": snapshot_id,
            "account_id": account_id,
            "snapshot_at": snapshot_at,
            "base_currency": snapshot.get("base_currency", "KRW"),
            "cash_value_krw": snapshot.get("cash_value_krw"),
            "securities_value_krw": snapshot.get("securities_value_krw"),
            "total_assets_krw": snapshot.get("total_assets_krw"),
            "total_purchase_amount_krw": snapshot.get("total_purchase_amount_krw"),
            "total_unrealized_pnl_krw": snapshot.get("total_unrealized_pnl_krw"),
            "source_job_id": source_job_id,
        },
    )
    return snapshot_id


def insert_position_snapshot(conn, snapshot_id, account_id, asset_id, position):
    conn.execute(
        text(
            "INSERT INTO position_snapshots (id, portfolio_snapshot_id, account_id, "
            "asset_id, currency, quantity, average_purchase_price, current_price, "
            "market_value_local, market_value_krw, unrealized_pnl_local, "
            "unrealized_pnl_krw, exchange_rate, created_at) "
            "VALUES (:id, :snapshot_id, :account_id, :asset_id, :currency, :quantity, "
            ":average_purchase_price, :current_price, :market_value_local, "
            ":market_value_krw, :unrealized_pnl_local, :unrealized_pnl_krw, "
            ":exchange_rate, now())"
        ),
        {
            "id": uuid.uuid4(),
            "snapshot_id": snapshot_id,
            "account_id": account_id,
            "asset_id": asset_id,
            "currency": position["currency"],
            "quantity": position["quantity"],
            "average_purchase_price": position.get("average_purchase_price"),
            "current_price": position.get("current_price"),
            "market_value_local": position.get("market_value_local"),
            "market_value_krw": position.get("market_value_krw"),
            "unrealized_pnl_local": position.get("unrealized_pnl_local"),
            "unrealized_pnl_krw": position.get("unrealized_pnl_krw"),
            "exchange_rate": position.get("exchange_rate"),
        },
    )
