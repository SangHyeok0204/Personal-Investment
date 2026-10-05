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
from decimal import Decimal

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
from repositories import sectors as sectors_repo
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

def _step(name: str, errors: list[str], fn):
    """이력 조회 한 단계. 죽으면 **이름과 함께 적고** None 을 돌려준다.

    ⚠️예전에는 다섯 조회가 한 try 안에 있었다. 체결 하나가 죽으면 나머지 넷은
      시도조차 안 됐고, 남는 것은 "History sync failed: ..." 한 줄이라 어디까지
      됐는지 알 수 없었다 — 화면에는 전부 0건으로 보인다.

    ⚠️돌려주는 None 은 **못 받은 것**이지 0건이 아니다. 호출부가 그 둘을 섞지
      않도록 빈 목록 대신 None 을 쓴다.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — 한 단계 실패로 나머지를 버리지 않는다
        errors.append(f"{name}({type(exc).__name__}: {exc})")
        return None


def _unread_currencies(balances, positions) -> list[str]:
    """**총평가금액은 0이 아닌데 보유가 한 줄도 안 온** 통화들.

    그런 통화가 있으면 우리가 응답을 못 읽은 것이다 — 다 판 것이 아니다.

    ⚠️총평가금액을 자산 합계로 쓰지 말 것. 통화가 섞여 있고 예수금 포함 여부도
      필드마다 다르다. 여기서는 **0인지 아닌지**만 본다.
    """
    held = {(p.get("currency") or "").upper() for p in positions or []}
    unread = []
    for balance in balances or []:
        currency = (balance.get("currency") or "").upper()
        value = balance.get("total_market_value_local")
        if not currency or not value:
            continue
        if Decimal(str(value)) != 0 and currency not in held:
            unread.append(currency)
    return sorted(set(unread))


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
        # ⚠️여기서 선언한다. 예전에는 이력 동기화 직전(아래)에서야 만들었는데,
        #   잔고 저장 단계에서도 알릴 일이 생긴다(보유 0건 방어). 선언보다 먼저
        #   쓰면 NameError 가 나는데 그 경로는 평소에 안 타서 안 보인다.
        history_notes: list[str] = []
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
                # ⚠️**"팔아서 0"과 "못 읽어서 0"을 가른다.**
                #   이 함수는 이번 동기화에 안 보인 보유를 **지운다**. 다 팔았으면
                #   그게 맞다. 그런데 증권사가 잔고 응답의 배열 키 이름을 바꾸면
                #   파서가 조용히 빈 목록을 내놓는다(pydantic 모델이
                #   `default_factory=list` 라 에러도 안 난다). 그때 포트폴리오가
                #   날아가고 동기화는 **성공**으로 끝난다.
                #
                #   증권사는 같은 응답에 통화별 **총평가금액**을 함께 준다.
                #   어떤 통화의 총평가금액이 0이 아닌데 그 통화 보유가 하나도
                #   없으면 우리가 못 읽은 것이다 — 그때는 아무것도 지우지 않는다.
                #
                #   ⚠️통화별로 본다. 계좌 전체가 0건일 때만 막으면, **한쪽 시장만**
                #     못 읽은 흔한 경우를 놓친다(실측 시험: 국내를 못 읽었는데
                #     미국 3종목이 와서 방어가 안 걸리고 국내 2종목이 지워졌다).
                unread = _unread_currencies(
                    account_data["balances"], account_data["positions"]
                )
                if unread:
                    history_notes.append(
                        f"{', '.join(unread)} 보유가 0건으로 왔는데 증권사가 말한"
                        f" 총평가금액은 0이 아닙니다 — **읽지 못한 것으로 보고 기존"
                        f" 보유를 지우지 않았습니다.** 응답 형식이 바뀌었을 수 있습니다."
                    )
                else:
                    positions_repo.delete_absent_positions(
                        conn, account_id, kept_asset_ids
                    )

                snapshot_id = snapshots_repo.insert_portfolio_snapshot(
                    conn, account_id, account_data["snapshot"], now, job_id
                )
                for asset_id, position in asset_positions:
                    snapshots_repo.insert_position_snapshot(
                        conn, snapshot_id, account_id, asset_id, position
                    )
                snapshots_created += 1
        # ★2026-09-21: 종목 마스터를 만든 직후 기본 섹터를 붙인다. 증권사가 섹터를
        #   주지 않아 그대로 두면 새로 산 종목이 영영 미분류로 남는다(동기화할 때마다
        #   섹터 비중이 100% 미분류로 떨어지던 원인). 화면에서 지정한 MANUAL 값은
        #   건드리지 않는다.
        with engine.begin() as conn:
            seeded = sectors_repo.apply_sector_seed(conn)
            unclassified = sectors_repo.unclassified_held_count(conn)
            # AI/Tech 밸류체인 3단계 분류(전통 섹터와 다른 축).
            tech = sectors_repo.apply_tech_classification(conn)
            tech_missing = sectors_repo.unclassified_tech_held(conn)
        log_job(
            engine, job_id, "INFO", "classify_assets",
            f"Sector seed {seeded}"
            + (f" ({unclassified} held unclassified)" if unclassified else "")
            + f"; tech ETF {tech['etf']} / seed {tech['seed']}"
            + (f" ({len(tech_missing)} held unclassified: "
               f"{', '.join(tech_missing[:8])})" if tech_missing else ""),
        )

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
        history_counts = {
            "trades": 0, "daily_performance": 0, "realized_pnl": 0, "dividends": 0,
            "orders": 0,
        }
        history_error: str | None = None
        #: 단계별 실패. 한 단계가 죽어도 나머지는 받고, 무엇이 죽었는지 남긴다.
        stage_errors: list[str] = []
        # ⚠️에러가 아니라 **조용히 0건**인 경우를 잡는다. 실측(2026-09-22 07:00 KST):
        #   usa21670 이 "정상적으로 처리되었습니다 / result_list 빈 배열" 을 돌려줬다.
        #   증권사 일일 배치 시간대로 보인다(같은 조회가 23시에는 530행이었다).
        #   에러가 아니니 예외도 안 나고 history_error 도 안 찍힌다 — 새 DB 로
        #   그 시간에 동기화하면 이력이 **빈 채로 굳는다**. 실제로 그렇게 됐다.
        try:
            history_start = now.date() - timedelta(days=HISTORY_DAYS)
            adapter_cls = get_adapter_class("KIWOOM")
            with adapter_cls(credentials, markets=markets) as adapter:
                for account_index, entry in enumerate(per_account):
                    account_id = account_id_by_index.get(account_index)
                    if account_id is None:
                        continue
                    account_ref = _account_ref(entry["account"])
                    # ⚠️**단계마다 따로 감싼다.** 예전에는 다섯 조회가 한 try 안에
                    #   있어서, 체결 조회 하나가 죽으면 일별성과·실현손익·주문·배당이
                    #   **아예 시도조차 안 됐다.** 그리고 남는 메시지는
                    #   "History sync failed: ..." 한 줄이라 어디까지 됐는지 알 수
                    #   없었다 — 화면은 전부 0건으로 보인다.
                    #   한 단계가 죽어도 나머지는 받고, 무엇이 죽었는지 이름으로 적는다.
                    trades = _step(
                        "체결", stage_errors,
                        lambda: adapter.fetch_trades(
                            account_ref, history_start, now.date()
                        ),
                    )
                    perf = _step(
                        "일별성과", stage_errors,
                        lambda: adapter.fetch_daily_performance(
                            account_ref, history_start, now.date()
                        ),
                    )
                    realized = _step(
                        "실현손익", stage_errors,
                        lambda: adapter.fetch_realized_pnl(
                            account_ref, history_start, now.date()
                        ),
                    )
                    # 주문 내역 — 체결에 없는 것(미체결·취소·슬리피지)을 담는다.
                    orders = _step(
                        "주문", stage_errors,
                        lambda: adapter.fetch_orders(
                            account_ref, history_start, now.date()
                        ),
                    )
                    # ★체결을 **먼저** 저장한다. 배당 조회 대상(현재 보유 + 과거 체결
                    #   종목)을 DB 에서 뽑는데, 체결을 나중에 쓰면 첫 동기화에서
                    #   이미 판 종목이 통째로 빠진다 — 실측에서 SGOV 등이 빠져
                    #   배당이 20건 중 10건만 들어왔다(예외 없음).
                    # ⚠️None 은 **못 받은 것**이다 — 빈 목록(0건)과 다르다.
                    #   못 받은 단계를 upsert 에 넘기지 않는다.
                    with engine.begin() as conn:
                        if trades is not None:
                            history_counts["trades"] += history_repo.upsert_trades(
                                conn, account_id, trades, job_id
                            )
                        if perf is not None:
                            history_counts["daily_performance"] += (
                                history_repo.upsert_daily_performance(
                                    conn, account_id, perf, job_id
                                )
                            )
                        if realized is not None:
                            history_counts["realized_pnl"] += (
                                history_repo.upsert_realized_pnl(
                                    conn, account_id, realized, job_id
                                )
                            )
                        if orders is not None:
                            history_counts["orders"] += history_repo.upsert_orders(
                                conn, account_id, orders, job_id
                            )
                        # ★2026-10-05 체결 원장 날짜는 결제일이다 — 주문 원장과 짝지어
                        #   체결일로 고친다. DB 의 주문을 쓰므로 주문 조회가 실패해도 돈다.
                        resolved = history_repo.resolve_us_trade_dates(conn, account_id)
                        # ⚠️못 짝지은 체결을 조용히 넘기지 않는다 — 날짜가 결제일이다.
                        if resolved["settlement"]:
                            history_notes.append(
                                f"해외 체결 {resolved['settlement']}건은 주문 내역과 짝을 못 지어 "
                                "체결일 대신 결제일로 표시됩니다."
                            )

                    # 배당은 종목별 조회라(usa21730 이 stk_cd 필수) 대상을 먼저 정한다.
                    # 이미 판 종목도 그 해에 배당을 받았을 수 있으므로 체결까지 본다.
                    with engine.begin() as conn:
                        dividend_targets = history_repo.tickers_for_dividends(
                            conn, account_id
                        )
                    fetched = _step(
                        "배당", stage_errors,
                        lambda: adapter.fetch_dividends(
                            account_ref, dividend_targets, history_start, now.date()
                        ),
                    )
                    if fetched is None:
                        continue
                    dividend_skipped = fetched.skipped
                    with engine.begin() as conn:
                        history_counts["dividends"] += history_repo.upsert_dividends(
                            conn, account_id, fetched.rows, job_id
                        )
                        # 찾아낸 거래소 코드를 남겨 다음 동기화의 탐색을 줄인다.
                        history_repo.remember_exchange_codes(conn, fetched.rows)
                        # ⚠️**배당이 0건이어도 코드는 남긴다.** 배당 행에서만
                        #   거두면 배당을 안 주는 종목은 매번 다시 더듬는다.
                        history_repo.remember_probed_codes(
                            conn, fetched.exchange_codes
                        )
                    # ⚠️**못 물어본 종목을 조용히 넘기지 않는다.** 배당 조회는
                    #   종목마다 거래소 코드가 있어야 하는데, 못 찾으면 그 종목은
                    #   조회 자체를 못 한다. 그걸 안 알리면 화면에서 '배당 0원'과
                    #   '안 물어봤다'가 똑같이 보인다.
                    if dividend_skipped:
                        history_notes.append(
                            f"배당 조회에서 {len(dividend_skipped)}종목을 건너뛰었습니다"
                            f"(거래소를 못 찾음): {', '.join(dividend_skipped)}."
                            " 이 종목들은 '배당 0원'이 아니라 **확인 못 한 것**입니다."
                        )
            # 체결은 들어왔는데 일별성과·배당이 0이면 조회 자체가 빈 응답이었다는 뜻이다.
            if history_counts["trades"] > 0:
                if history_counts["daily_performance"] == 0:
                    history_notes.append(
                        "일별 계좌성과가 0건입니다 — 증권사가 에러 없이 빈 응답을 "
                        "주는 시간대일 수 있습니다(이른 아침 배치). 나중에 다시 동기화하세요."
                    )
                if history_counts["dividends"] == 0:
                    history_notes.append(
                        "배당이 0건입니다 — 같은 이유일 수 있으니 나중에 다시 동기화하세요."
                    )
            # ⚠️**응답 모양이 바뀌면 0건이 조용히 돌아온다.** 모든 파서가
            #   `result_list` 를 기대하는데, 증권사가 키 이름을 바꾸면 동기화는
            #   성공으로 끝나고 화면은 "거래 없음"이라고 말한다. 가정이 아니라
            #   이미 겪은 일이다 — 주문 조회는 명세 예시가 `result_lsit`(오타)라
            #   두 키를 모두 받아 주고 있다. 어댑터가 모아 둔 것을 여기서 알린다.
            history_notes.extend(getattr(adapter, "shape_warnings", []))

            # ⚠️단계 실패를 **0건과 섞지 않는다.** 어느 단계가 죽었는지 이름으로
            #   적어야 "거래가 없는 것"과 "못 받은 것"을 구분할 수 있다.
            if stage_errors:
                history_notes.append(
                    f"{len(stage_errors)}개 단계를 받지 못했습니다 — "
                    + "; ".join(stage_errors)
                    + ". 그 화면들은 **0건이 아니라 미수집** 상태입니다."
                )

            for note in history_notes:
                log_job(engine, job_id, "WARNING", "sync_history", note)

            log_job(
                engine, job_id, "INFO", "sync_history",
                f"Synced {history_counts['trades']} trade(s), "
                f"{history_counts['daily_performance']} daily perf row(s), "
                f"{history_counts['realized_pnl']} realized row(s), "
                f"{history_counts['dividends']} dividend(s), "
                f"{history_counts['orders']} order(s)",
            )
        except Exception as exc:  # noqa: BLE001 - 잔고는 지키고 경고만 남긴다
            # ⚠️여기서 삼킨 예외가 **화면에는 '성공'으로 보인다.** 실제로 주문 조회의
            #   571758 하나가 체결·실현손익·배당까지 0 건으로 만들었는데 동기화는
            #   ok=true 를 돌려줬다. 결과에 실어 호출부가 알 수 있게 한다.
            history_error = str(exc)
            log_job(
                engine, job_id, "WARNING", "sync_history",
                f"History sync failed (balances are already saved): {exc}",
            )

        # 14. complete ---------------------------------------------------------
        _update_connection_success(engine, connection_id)
        result = {
            "history_error": history_error,
            "history_notes": history_notes,
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
