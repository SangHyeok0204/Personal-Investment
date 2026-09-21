"""accounts upsert (UNIQUE brokerage_connection_id + external_account_id)."""
import uuid

from sqlalchemy import text


def upsert_account(conn, broker_id, connection_id, account):
    """Insert/update the account row; returns its id (existing on conflict)."""
    return conn.execute(
        text(
            "INSERT INTO accounts (id, broker_id, brokerage_connection_id, "
            "external_account_id, account_number_masked, account_name, account_type, "
            "base_currency, is_active, last_synced_at, created_at, updated_at) "
            "VALUES (:id, :broker_id, :connection_id, :external_account_id, :masked, "
            ":account_name, :account_type, :base_currency, TRUE, now(), now(), now()) "
            "ON CONFLICT (brokerage_connection_id, external_account_id) DO UPDATE SET "
            "account_number_masked=EXCLUDED.account_number_masked, "
            "account_name=EXCLUDED.account_name, account_type=EXCLUDED.account_type, "
            "base_currency=EXCLUDED.base_currency, is_active=TRUE, "
            "last_synced_at=now(), updated_at=now() "
            "RETURNING id"
        ),
        {
            "id": uuid.uuid4(),
            "broker_id": broker_id,
            "connection_id": connection_id,
            "external_account_id": account["external_account_id"],
            "masked": account.get("account_number_masked"),
            "account_name": account.get("account_name"),
            "account_type": account.get("account_type"),
            "base_currency": account.get("base_currency", "KRW"),
        },
    ).scalar_one()
