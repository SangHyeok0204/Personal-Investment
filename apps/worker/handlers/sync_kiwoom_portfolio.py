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
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import text

from brokers.credentials import EnvCredentialResolver
from brokers.registry import get_adapter_class
from brokers.kiwoom import auth, domestic, us_equities
from brokers.kiwoom.adapter import normalize_account
from brokers.kiwoom.client import KiwoomClient
from brokers.kiwoom.exceptions import KiwoomConfigError, KiwoomResponseShapeError
from repositories import accounts as accounts_repo
from repositories import assets as assets_repo
from repositories import balances as balances_repo
from repositories import positions as positions_repo
from repositories import raw_responses as raw_repo
from repositories import history as history_repo
from repositories import snapshots as snapshots_repo

DEFAULT_BASE_URL = "https://api.kiwoom.com"
CONFIG_ERROR_MESSAGE = "KIWOOM_APP_KEY/KIWOOM_SECRET_KEY is not configured"

# 자격증명 출처. 테스트나 다른 배포 형태에서 갈아끼울 수 있게 모듈 수준에 둔다.
_CREDENTIAL_RESOLVER = EnvCredentialResolver()

# 이력(체결·일별성과·실현손익)을 얼마나 거슬러 받을지. 증권사 상한(체결 1년,
# 실현손익 6개월)은 어댑터가 창을 나눠 처리하므로 여기서는 원하는 기간만 정한다.
# 730일: 2년치면 "작년 이맘때"를 비교할 수 있고, 조회 비용도 감당된다.
HISTORY_DAYS = int(os.environ.get("KIWOOM_HISTORY_DAYS", "730"))


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


def _account_ref(raw_account):
    """어댑터 계약(AccountRef)으로 바꾼다. 이력 조회는 계좌번호를 요청에 넣지 않지만,
    계약상 계좌를 받게 돼 있어 형태를 맞춘다."""
    from brokers.base import AccountRef

    return AccountRef(
        external_account_id=raw_account.get("external_account_id", ""),
        account_name=raw_account.get("account_name"),
        account_type=raw_account.get("account_type"),
    )


# ---- handler ------------------------------------------------------------------

def run(engine, job_id, payload, storage_dir, log_job):
    payload = payload or {}
    connection = None
    try:
        # 1. validate_configuration -------------------------------------------
        connection = _resolve_connection(engine, payload)
        connection_id = connection["id"]
        broker_id = connection["broker_id"]

        # ★2026-09-21: 전역 환경변수를 직접 읽던 것을 자격증명 리졸버로 바꿨다.
        #   연결(brokerage_connections)마다 다른 키를 줄 수 있어야 "키만 바꾸면
        #   다른 사람 계좌"가 성립한다. 리졸버가 연결 이름으로 먼저 찾고, 없으면
        #   KIWOOM_APP_KEY 로 떨어지므로 혼자 쓸 때는 설정이 그대로다.
        try:
            credentials = _CREDENTIAL_RESOLVER.resolve(
                broker_code="KIWOOM", connection=connection
            )
        except KiwoomConfigError as exc:
            log_job(engine, job_id, "ERROR", "validate_configuration", str(exc))
            raise
        app_key = credentials.app_key
        secret_key = credentials.secret_key
        base_url = credentials.base_url
        # 조회할 시장. 안 보는 시장의 TR 을 매번 부르면 유량제한만 축낸다.
        markets = tuple(
            m.strip().upper()
            for m in os.environ.get("KIWOOM_MARKETS", "KR,US").split(",")
            if m.strip()
        ) or ("KR", "US")

        # 지문만 남긴다 — 어느 자격증명으로 돌았는지는 알 수 있고 키는 안 샌다.
        log_job(
            engine, job_id, "INFO", "validate_configuration",
            "Configuration valid; credentials present "
            f"(fingerprint={credentials.fingerprint}, env={credentials.environment})",
        )

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
            # ★2026-09-21: 시장 선택(KIWOOM_MARKETS)을 잔고 조회에도 적용한다.
            #   KR 을 끄면 kt00001/kt00018 을 **아예 부르지 않는다** — 안 보는 시장의
            #   TR 을 매번 부르면 유량제한만 축낸다.
            #   ⚠️국내를 끄면 원화 예수금(kt00001 의 D+2)을 모르게 된다. 어댑터와
            #     달리 여기서는 빈 응답을 넣는데, _krw_cash_row 가 0 을 만들어 내므로
            #     아래 normalize 뒤에 그 행을 걷어낸다(0 원과 '모름'은 다르다).
            for index, account in enumerate(accounts_info):
                if "KR" not in markets:
                    per_account.append(
                        {
                            "index": index,
                            "account": account,
                            "deposit": domestic.parse_deposit([{}]),
                        }
                    )
                    continue
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
                if "KR" not in markets:
                    entry["balance"] = domestic.parse_balance(
                        [{"acnt_evlt_remn_indv_tot": []}]
                    )
                    continue
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

            # 6. fetch_us_balance (ust21110 예수금 + ust21160 예수금상세) -------
            # US 를 끄면 해외 TR 을 건너뛴다.
            # ust21160 is required, not optional: it is the ONLY source of
            # usd_exch_rate AND of the settled D+2 USD balance.
            for entry in per_account:
                account = entry["account"]
                index = entry["index"]

                us_deposit_pages = us_equities.fetch_deposit(client, account)
                for rel_path, digest in _save_pages(
                    abs_dir, rel_dir, f"ust21110_us_deposit_{index}", us_deposit_pages
                ):
                    raw_registrations.append(("us", us_equities.API_US_DEPOSIT, rel_path, digest))

                us_detail_pages = us_equities.fetch_deposit_detail(client, account)
                for rel_path, digest in _save_pages(
                    abs_dir, rel_dir, f"ust21160_us_deposit_detail_{index}", us_detail_pages
                ):
                    raw_registrations.append(
                        ("us", us_equities.API_US_DEPOSIT_DETAIL, rel_path, digest)
                    )

                try:
                    entry["us_deposit"] = us_equities.parse_deposit(us_deposit_pages)
                    entry["us_detail"] = us_equities.parse_deposit_detail(us_detail_pages)
                except ValidationError as exc:
                    raise KiwoomResponseShapeError(
                        f"unexpected response shape "
                        f"(raw saved: {_last_saved_path(raw_registrations)})"
                    ) from exc
            log_job(engine, job_id, "INFO", "fetch_us_balance",
                    f"Fetched US deposits for {len(per_account)} account(s)")

            # 7. fetch_us_positions (ust21070 해외 잔고) -----------------------
            for entry in per_account:
                us_balance_pages = us_equities.fetch_positions(client, entry["account"])
                for rel_path, digest in _save_pages(
                    abs_dir, rel_dir, f"ust21070_us_balance_{entry['index']}", us_balance_pages
                ):
                    raw_registrations.append(("us", us_equities.API_US_POSITIONS, rel_path, digest))
                try:
                    entry["us_balance"] = us_equities.parse_positions(us_balance_pages)
                except ValidationError as exc:
                    raise KiwoomResponseShapeError(
                        f"unexpected response shape "
                        f"(raw saved: {_last_saved_path(raw_registrations)})"
                    ) from exc
            total_us_holdings = sum(len(e["us_balance"].result_list) for e in per_account)
            log_job(engine, job_id, "INFO", "fetch_us_positions",
                    f"Fetched {total_us_holdings} US holding row(s)")

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
            normalize_account(
                e["account"],
                e["balance"],
                e["deposit"],
                us_balance=e.get("us_balance"),
                us_deposit=e.get("us_deposit"),
                us_detail=e.get("us_detail"),
            )
            for e in per_account
        ]
        all_positions = [p for n in normalized for p in n["positions"]]
        total_positions = len(all_positions)
        total_balances = sum(len(n["balances"]) for n in normalized)
        domestic_positions = sum(1 for p in all_positions if p["country"] == "KR")
        # 국내를 안 불렀으면 원화 예수금은 **모르는 값**이다 — 0 이라고 단언하지 않는다.
        # (해외 응답이 won_entr 로 원화 예수금을 주지만, kt00001 의 D+2 정산 반영분과
        #  달라서 같은 자리에 섞지 않는다. 모르면 행을 없앤다.)
        if "KR" not in markets:
            for account_data in normalized:
                account_data["balances"] = [
                    b for b in account_data["balances"]
                    if b.get("currency") != "KRW" or b.get("cash_balance")
                ]
            total_balances = sum(len(n["balances"]) for n in normalized)

        us_positions = sum(1 for p in all_positions if p["country"] == "US")
        log_job(engine, job_id, "INFO", "normalize_assets",
                f"Normalized {domestic_positions} domestic + {us_positions} US position(s), "
                f"{total_balances} balance(s)")

        # 10/11/12. per-account transaction (all-or-nothing): accounts, balances,
        # assets, positions, delete sold rows, snapshots.
        log_job(engine, job_id, "INFO", "upsert_accounts",
                f"Upserting {len(normalized)} account(s)")
        snapshots_created = 0
        # 이력 동기화(13단계)가 계좌별로 돌아야 해서 여기서 id 를 챙겨 둔다.
        account_id_by_index = {}
        for account_index, account_data in enumerate(normalized):
            with engine.begin() as conn:
                account_id = accounts_repo.upsert_account(
                    conn, broker_id, connection_id, account_data
                )
                account_id_by_index[account_index] = account_id
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

        # 13. sync_history (체결 · 일별성과 · 실현손익) --------------------------
        # ★2026-09-21 추가: 현재 보유(current_positions)만 동기화하던 것을 이력까지
        #   넓혔다. 이력이 없으면 매매내역·자산추이·실현손익 화면이 영영 비어 있다.
        #   전부 upsert 라 같은 기간을 다시 돌려도 행이 늘지 않는다.
        #   ⚠️여기서 실패해도 **잔고 동기화는 이미 커밋돼 있다.** 이력은 보조 정보라
        #     실패를 이유로 잔고까지 되돌리지 않는다 — 대신 경고로 남긴다.
        history_counts = {"trades": 0, "daily_performance": 0, "realized_pnl": 0}
        try:
            history_start = now.date() - timedelta(days=HISTORY_DAYS)
            adapter_cls = get_adapter_class("KIWOOM")
            with adapter_cls(credentials, markets=markets) as adapter:
                for account_index, entry in enumerate(per_account):
                    account_id = account_id_by_index.get(account_index)
                    if account_id is None:
                        continue
                    account_ref = _account_ref(entry["account"])
                    trades = adapter.fetch_trades(account_ref, history_start, now.date())
                    perf = adapter.fetch_daily_performance(
                        account_ref, history_start, now.date()
                    )
                    realized = adapter.fetch_realized_pnl(
                        account_ref, history_start, now.date()
                    )
                    with engine.begin() as conn:
                        history_counts["trades"] += history_repo.upsert_trades(
                            conn, account_id, trades, job_id
                        )
                        history_counts["daily_performance"] += (
                            history_repo.upsert_daily_performance(
                                conn, account_id, perf, job_id
                            )
                        )
                        history_counts["realized_pnl"] += history_repo.upsert_realized_pnl(
                            conn, account_id, realized, job_id
                        )
            log_job(
                engine, job_id, "INFO", "sync_history",
                f"Synced {history_counts['trades']} trade(s), "
                f"{history_counts['daily_performance']} daily perf row(s), "
                f"{history_counts['realized_pnl']} realized row(s)",
            )
        except Exception as exc:  # noqa: BLE001 - 잔고는 지키고 경고만 남긴다
            log_job(
                engine, job_id, "WARNING", "sync_history",
                f"History sync failed (balances are already saved): {exc}",
            )

        # 14. complete ---------------------------------------------------------
        _update_connection_success(engine, connection_id)
        result = {
            "accounts_synced": len(normalized),
            "domestic_positions": domestic_positions,
            "us_positions": us_positions,
            "cash_balances": total_balances,
            "snapshots_created": snapshots_created,
            "us_supported": us_equities.US_SUPPORTED,
            "markets": list(markets),
            **history_counts,
            "synced_at": now.isoformat(),
        }
        log_job(engine, job_id, "INFO", "complete",
                f"Sync complete: {result['accounts_synced']} account(s), "
                f"{domestic_positions} domestic + {us_positions} US position(s)")
        return result

    except Exception as exc:
        if connection is not None:
            _update_connection_error(
                engine, connection["id"], str(exc) or exc.__class__.__name__
            )
        raise
