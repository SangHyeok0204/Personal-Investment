"""account_balances upsert (UNIQUE account_id + currency)."""
import uuid

from sqlalchemy import text


def upsert_balance(conn, account_id, balance, as_of, source_job_id):
    conn.execute(
        text(
            "INSERT INTO account_balances (id, account_id, currency, cash_balance, "
            "available_cash, total_purchase_amount_local, total_market_value_local, "
            "total_evaluation_amount_local, total_unrealized_pnl_local, exchange_rate, "
            "total_evaluation_amount_krw, as_of, source_job_id, created_at, updated_at) "
            "VALUES (:id, :account_id, :currency, :cash_balance, :available_cash, "
            ":total_purchase_amount_local, :total_market_value_local, "
            ":total_evaluation_amount_local, :total_unrealized_pnl_local, :exchange_rate, "
            ":total_evaluation_amount_krw, :as_of, :source_job_id, now(), now()) "
            "ON CONFLICT (account_id, currency) DO UPDATE SET "
            "cash_balance=EXCLUDED.cash_balance, available_cash=EXCLUDED.available_cash, "
            "total_purchase_amount_local=EXCLUDED.total_purchase_amount_local, "
            "total_market_value_local=EXCLUDED.total_market_value_local, "
            "total_evaluation_amount_local=EXCLUDED.total_evaluation_amount_local, "
            "total_unrealized_pnl_local=EXCLUDED.total_unrealized_pnl_local, "
            "exchange_rate=EXCLUDED.exchange_rate, "
            "total_evaluation_amount_krw=EXCLUDED.total_evaluation_amount_krw, "
            "as_of=EXCLUDED.as_of, source_job_id=EXCLUDED.source_job_id, updated_at=now()"
        ),
        {
            "id": uuid.uuid4(),
            "account_id": account_id,
            "currency": balance["currency"],
            "cash_balance": balance["cash_balance"],
            "available_cash": balance.get("available_cash"),
            "total_purchase_amount_local": balance.get("total_purchase_amount_local"),
            "total_market_value_local": balance.get("total_market_value_local"),
            "total_evaluation_amount_local": balance.get("total_evaluation_amount_local"),
            "total_unrealized_pnl_local": balance.get("total_unrealized_pnl_local"),
            "exchange_rate": balance.get("exchange_rate"),
            "total_evaluation_amount_krw": balance.get("total_evaluation_amount_krw"),
            "as_of": as_of,
            "source_job_id": source_job_id,
        },
    )
