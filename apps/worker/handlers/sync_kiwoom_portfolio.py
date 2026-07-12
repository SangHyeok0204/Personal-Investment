"""SYNC_KIWOOM_PORTFOLIO handler.

Signature matches the other handlers: run(engine, job_id, payload, storage_dir,
log_job). Raising propagates to main.process_job, which marks the job FAILED with
str(exc); returning a dict marks it SUCCESS. On ANY failure we also flip the
brokerage_connection to ERROR + last_error before re-raising.

Step-log sequence is pinned by contract-kiwoom.md §4 (job_logs.step, in order):
    validate_configuration, request_access_token, fetch_accounts,
    fetch_domestic_balance, fetch_domestic_positions, fetch_us_balance,
    fetch_us_positions, save_raw_responses, normalize_assets, upsert_accounts,
    upsert_positions, create_snapshots, complete

Raw responses are written to disk during the fetch steps (so shape errors can
name the file), then registered in broker_api_raw_responses at save_raw_responses
— always BEFORE the portfolio DB writes. The token is never written; only
token-metadata.json (issued_at/expires_at) lands in the raw dir.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import text

from brokers.kiwoom import auth, domestic, us_equities
from brokers.kiwoom.adapter import normalize_domestic_account
from brokers.kiwoom.client import KiwoomClient
from brokers.kiwoom.exceptions import KiwoomConfigError, KiwoomResponseShapeError
from repositories import accounts as accounts_repo
from repositories import assets as assets_repo
from repositories import balances as balances_repo
from repositories import positions as positions_repo
from repositories import raw_responses as raw_repo
from repositories import snapshots as snapshots_repo

DEFAULT_BASE_URL = "https://api.kiwoom.com"
CONFIG_ERROR_MESSAGE = "KIWOOM_APP_KEY/KIWOOM_SECRET_KEY is not configured"
US_SKIP_MESSAGE = "SKIPPED: US REST support unconfirmed (see kiwoom-api-reference §5)"


# ---- connection helpers (no dedicated repo per contract §5 structure) ---------

def _resolve_connection(engine, payload):
    connection_id = payload.get("connection_id")
    with engine.begin() as conn:
        if connection_id:
            row = (
                conn.execute(
                    text(
                        "SELECT id, broker_id, status FROM brokerage_connections "
                        "WHERE id=:id"
                    ),
                    {"id": connection_id},
                )
                .mappings()
                .first()
            )
        else:
            row = (
                conn.execute(
                    text(
                        "SELECT id, broker_id, status FROM brokerage_connections "
                        "ORDER BY created_at LIMIT 1"
                    )
                )
                .mappings()
                .first()
            )
    if row is None:
        raise ValueError(
            f"Brokerage connection not found: {connection_id}"
            if connection_id
            else "No brokerage connection configured"
        )
    return dict(row)


def _update_connection_success(engine, connection_id):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE brokerage_connections SET status='CONNECTED', "
                "last_connected_at=now(), last_synced_at=now(), last_error=NULL, "
                "updated_at=now() WHERE id=:id"
            ),
            {"id": connection_id},
        )


def _update_connection_error(engine, connection_id, message):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE brokerage_connections SET status='ERROR', last_error=:err, "
                "updated_at=now() WHERE id=:id"
            ),
            {"id": connection_id, "err": (message or "")[:1000]},
        )


# ---- raw file helpers ---------------------------------------------------------

def _raw_dir(storage_dir, job_id, now):
    """Create raw/kiwoom/YYYY/MM/DD/<job_id>/; return (relative, absolute)."""
    rel_dir = "/".join(
        ["raw", "kiwoom", now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"), str(job_id)]
    )
    abs_dir = os.path.join(storage_dir, *rel_dir.split("/"))
    os.makedirs(abs_dir, exist_ok=True)
    return rel_dir, abs_dir


def _write_json(abs_dir, rel_dir, name, data):
    """Write one response file; return (path relative to STORAGE_DIR, sha256)."""
    filename = f"{name}.json"
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with open(os.path.join(abs_dir, filename), "w", encoding="utf-8") as handle:
        handle.write(payload)
    rel_path = f"{rel_dir}/{filename}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return rel_path, digest


def _save_pages(abs_dir, rel_dir, base_name, pages):
    """Write each response page as its own file; return list of (rel_path, hash)."""
    saved = []
    multi = len(pages) > 1
    for index, page in enumerate(pages):
        name = f"{base_name}_p{index}" if multi else base_name
        saved.append(_write_json(abs_dir, rel_dir, name, page))
    return saved


def _write_token_metadata(abs_dir):
    metadata = auth.get_token_metadata()  # issued_at/expires_at ONLY (never the token)
    with open(os.path.join(abs_dir, "token-metadata.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)


def _last_saved_path(registrations):
    return registrations[-1][2] if registrations else "unknown"


# ---- handler ------------------------------------------------------------------

def run(engine, job_id, payload, storage_dir, log_job):
    payload = payload or {}
    connection = None
    try:
        # 1. validate_configuration -------------------------------------------
        connection = _resolve_connection(engine, payload)
        connection_id = connection["id"]
        broker_id = connection["broker_id"]

        app_key = os.environ.get("KIWOOM_APP_KEY", "").strip()
        secret_key = os.environ.get("KIWOOM_SECRET_KEY", "").strip()
        base_url = os.environ.get("KIWOOM_API_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL

        if not app_key or not secret_key:
            log_job(engine, job_id, "ERROR", "validate_configuration", CONFIG_ERROR_MESSAGE)
            raise KiwoomConfigError(CONFIG_ERROR_MESSAGE)
        log_job(engine, job_id, "INFO", "validate_configuration",
                "Configuration valid; credentials present")

        now = datetime.now(timezone.utc)
        rel_dir, abs_dir = _raw_dir(storage_dir, job_id, now)
        # (api_category, endpoint_name, rel_path, sha256) to register after fetches.
        raw_registrations = []
        per_account = []

        with KiwoomClient(base_url, app_key, secret_key) as client:
            # 2. request_access_token -----------------------------------------
            client.ensure_token()
            _write_token_metadata(abs_dir)
            log_job(engine, job_id, "INFO", "request_access_token", "Access token acquired")

            # 3. fetch_accounts -----------------------------------------------
            account_pages = domestic.fetch_account_list(client)
            for rel_path, digest in _save_pages(abs_dir, rel_dir, "ka00001_accounts", account_pages):
                raw_registrations.append(("domestic", domestic.API_ACCOUNT_LIST, rel_path, digest))
            accounts_info = domestic.parse_account_list(account_pages)
            if not accounts_info:
                raise KiwoomResponseShapeError(
                    f"no accounts found in ka00001 response "
                    f"(raw saved: {_last_saved_path(raw_registrations)})"
                )
            log_job(engine, job_id, "INFO", "fetch_accounts",
                    f"Fetched {len(accounts_info)} account(s)")

            # 4. fetch_domestic_balance (kt00001 예수금) ----------------------
            for index, account in enumerate(accounts_info):
                deposit_pages = domestic.fetch_deposit(client, account)
                for rel_path, digest in _save_pages(
                    abs_dir, rel_dir, f"kt00001_deposit_{index}", deposit_pages
                ):
                    raw_registrations.append(("domestic", domestic.API_DEPOSIT, rel_path, digest))
                try:
                    deposit = domestic.parse_deposit(deposit_pages)
                except ValidationError as exc:
                    raise KiwoomResponseShapeError(
                        f"unexpected response shape "
                        f"(raw saved: {_last_saved_path(raw_registrations)})"
                    ) from exc
                per_account.append({"index": index, "account": account, "deposit": deposit})
            log_job(engine, job_id, "INFO", "fetch_domestic_balance",
                    f"Fetched deposits for {len(per_account)} account(s)")

            # 5. fetch_domestic_positions (kt00018 잔고) ----------------------
            for entry in per_account:
                balance_pages = domestic.fetch_balance(client, entry["account"])
                for rel_path, digest in _save_pages(
                    abs_dir, rel_dir, f"kt00018_balance_{entry['index']}", balance_pages
                ):
                    raw_registrations.append(("domestic", domestic.API_BALANCE, rel_path, digest))
                try:
                    entry["balance"] = domestic.parse_balance(balance_pages)
                except ValidationError as exc:
                    raise KiwoomResponseShapeError(
                        f"unexpected response shape "
                        f"(raw saved: {_last_saved_path(raw_registrations)})"
                    ) from exc
            total_holdings = sum(len(e["balance"].acnt_evlt_remn_indv_tot) for e in per_account)
            log_job(engine, job_id, "INFO", "fetch_domestic_positions",
                    f"Fetched {total_holdings} holding row(s)")

            # 6/7. fetch_us_balance / fetch_us_positions — SKIPPED ------------
            if us_equities.US_SUPPORTED:  # pragma: no cover - disabled this round
                raise KiwoomResponseShapeError("US path enabled but not implemented")
            log_job(engine, job_id, "INFO", "fetch_us_balance", US_SKIP_MESSAGE)
            log_job(engine, job_id, "INFO", "fetch_us_positions", US_SKIP_MESSAGE)

        # 8. save_raw_responses (register rows BEFORE portfolio DB writes) -----
        with engine.begin() as conn:
            for api_category, endpoint_name, rel_path, digest in raw_registrations:
                raw_repo.register_raw_response(
                    conn, broker_id, job_id, api_category, endpoint_name, rel_path, digest
                )
        log_job(engine, job_id, "INFO", "save_raw_responses",
                f"Registered {len(raw_registrations)} raw response file(s)")

        # 9. normalize_assets --------------------------------------------------
        normalized = [
            normalize_domestic_account(e["account"], e["balance"], e["deposit"])
            for e in per_account
        ]
        total_positions = sum(len(n["positions"]) for n in normalized)
        total_balances = sum(len(n["balances"]) for n in normalized)
        log_job(engine, job_id, "INFO", "normalize_assets",
                f"Normalized {total_positions} position(s), {total_balances} balance(s)")

        # 10/11/12. per-account transaction (all-or-nothing): accounts, balances,
        # assets, positions, delete sold rows, snapshots.
        log_job(engine, job_id, "INFO", "upsert_accounts",
                f"Upserting {len(normalized)} account(s)")
        snapshots_created = 0
        for account_data in normalized:
            with engine.begin() as conn:
                account_id = accounts_repo.upsert_account(
                    conn, broker_id, connection_id, account_data
                )
                for balance in account_data["balances"]:
                    balances_repo.upsert_balance(conn, account_id, balance, now, job_id)

                kept_asset_ids = []
                asset_positions = []
                for position in account_data["positions"]:
                    asset_id = assets_repo.upsert_asset(conn, position)
                    positions_repo.upsert_position(
                        conn, account_id, asset_id, position, now, job_id
                    )
                    kept_asset_ids.append(asset_id)
                    asset_positions.append((asset_id, position))
                positions_repo.delete_absent_positions(conn, account_id, kept_asset_ids)

                snapshot_id = snapshots_repo.insert_portfolio_snapshot(
                    conn, account_id, account_data["snapshot"], now, job_id
                )
                for asset_id, position in asset_positions:
                    snapshots_repo.insert_position_snapshot(
                        conn, snapshot_id, account_id, asset_id, position
                    )
                snapshots_created += 1
        log_job(engine, job_id, "INFO", "upsert_positions",
                f"Upserted {total_positions} position(s)")
        log_job(engine, job_id, "INFO", "create_snapshots",
                f"Created {snapshots_created} snapshot(s)")

        # 13. complete ---------------------------------------------------------
        _update_connection_success(engine, connection_id)
        result = {
            "accounts_synced": len(normalized),
            "domestic_positions": total_positions,
            "us_positions": 0,
            "cash_balances": total_balances,
            "snapshots_created": snapshots_created,
            "us_supported": us_equities.US_SUPPORTED,
            "synced_at": now.isoformat(),
        }
        log_job(engine, job_id, "INFO", "complete",
                f"Sync complete: {result['accounts_synced']} account(s), "
                f"{result['domestic_positions']} position(s)")
        return result

    except Exception as exc:
        if connection is not None:
            _update_connection_error(
                engine, connection["id"], str(exc) or exc.__class__.__name__
            )
        raise
