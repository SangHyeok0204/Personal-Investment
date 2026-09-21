"""증권사 연동 — 키 등록 · 계좌 확인 · 동기화 실행.

★2026-09-21 사용자 요청: 화면의 "계좌 연동하기"에서 appkey/secretkey 를 넣으면
  바로 연동되고 대시보드에 반영되게.

[왜 API 가 직접 동기화를 돌리는가]
설계상 정석은 잡을 큐에 넣고 worker 가 집어 가는 것이다. 다만 이 시스템은
**혼자 쓰는 로컬 대시보드**라, 그러려면 worker 데몬을 항상 띄워 둬야 하고 "눌렀는데
아무 일도 안 난다"가 되기 쉽다. 실행 시간이 수 초(실측 ~10초)라 요청 안에서 끝내는
편이 사용자에게 정직하다. 대신 worker 의 코드를 **그대로** 재사용해 로직이 갈라지지
않게 한다(핸들러 하나만 유지보수한다).

⚠️보안: 이 엔드포인트들에는 인증이 없다. localhost 단독 사용 전제다.
  네트워크에 노출할 거라면 그 전에 인증을 붙여야 한다.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import credentials_store
from app.core.errors import AppError
from app.db.session import engine, get_db

router = APIRouter(prefix="/api/v1/brokerage", tags=["brokerage"])

# worker 의 어댑터/핸들러를 재사용한다 — 증권사 로직을 두 벌 두지 않기 위해서다.
_WORKER_DIR = Path(__file__).resolve().parents[4] / "apps" / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))


class CredentialsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_key: str = Field(min_length=10, max_length=200)
    secret_key: str = Field(min_length=10, max_length=200)
    environment: str = Field(default="REAL")
    # 조회할 시장. 안 보는 시장의 TR 을 부르면 유량제한만 축낸다.
    markets: list[str] = Field(default_factory=lambda: ["US"])


class AccountPreview(BaseModel):
    external_account_id: str
    account_number_masked: str | None
    account_name: str | None
    account_type: str | None


class CredentialsStatusOut(BaseModel):
    configured: bool
    #: 키움 허용목록에 등록해야 하는 이 서버의 공인 IP. 조회 실패 시 null.
    public_ip: str | None = None
    environment: str
    markets: list[str]
    # 키 자체는 절대 나가지 않는다 — 지문과 꼬리 4자리뿐이다.
    fingerprint: str | None
    app_key_tail: str | None
    connection_ok: bool | None = None
    connection_reason: str | None = None
    connection_message: str | None = None
    accounts: list[AccountPreview] = []


class QuickSyncResultOut(BaseModel):
    """가벼운 동기화 결과 — 잔고와 보유 종목만."""

    ok: bool
    positions: int = 0
    balances: int = 0
    as_of: str | None = None
    elapsed_ms: int = 0
    message: str | None = None


class SyncResultOut(BaseModel):
    ok: bool
    accounts_synced: int = 0
    positions: int = 0
    trades: int = 0
    daily_performance: int = 0
    realized_pnl: int = 0
    dividends: int = 0
    message: str | None = None


def _public_ip() -> str | None:
    """이 서버의 공인 IP. 키움 허용목록에 등록해야 하는 바로 그 주소다.

    ★2026-09-21: IP 미등록(8050) 으로 두 번 막혔고, 두 번째는 **네트워크가 바뀌어
      IP 자체가 달라진 것**이었다(165.132.5.132 → 121.131.150.214). 오류 메시지가
      "IP를 등록하세요"라고만 하면 사용자는 *어떤* IP 인지 찾아 헤맨다. 화면이
      그 값을 직접 보여준다.

    ⚠️외부 조회라 실패할 수 있다 — 실패하면 None 이고, 화면은 그 줄만 생략한다.
      IP 를 못 알아냈다고 연동 자체가 막히면 안 된다.
    """
    import httpx

    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            response = httpx.get(url, timeout=3.0)
            if response.status_code == 200:
                ip = response.text.strip()
                if ip and len(ip) <= 45:
                    return ip
        except Exception:
            continue
    return None


def _build_credentials(app_key: str, secret_key: str, environment: str):
    from brokers.credentials import BrokerCredentials

    return BrokerCredentials(
        broker_code="KIWOOM",
        app_key=app_key,
        secret_key=secret_key,
        environment=(environment or "REAL").upper(),
        label="주계좌",
    )


def _probe(credentials, markets: list[str]) -> tuple[dict, list[AccountPreview]]:
    """토큰 발급 + 계좌 목록. 실패해도 예외 대신 진단을 돌려준다."""
    from brokers.registry import get_adapter_class

    adapter_cls = get_adapter_class("KIWOOM")
    with adapter_cls(credentials, markets=tuple(markets) or ("US",)) as adapter:
        check = adapter.check_connection()
        if not check.get("ok"):
            return check, []
        accounts = [
            AccountPreview(
                external_account_id=a.external_account_id,
                account_number_masked=a.account_number_masked,
                account_name=a.account_name,
                account_type=a.account_type,
            )
            for a in adapter.fetch_accounts()
        ]
    return check, accounts


@router.get("/credentials", response_model=CredentialsStatusOut)
def get_credentials_status() -> CredentialsStatusOut:
    """현재 등록된 키의 **상태만**. 키는 나가지 않는다."""
    return CredentialsStatusOut(**credentials_store.read_settings())


@router.get("/accounts", response_model=CredentialsStatusOut)
def list_broker_accounts() -> CredentialsStatusOut:
    """등록된 키로 조회되는 계좌 목록 — "이 API 에 묶인 계좌" 선택 상자의 원천."""
    settings = credentials_store.read_settings()
    if not settings["configured"]:
        return CredentialsStatusOut(**settings, connection_ok=False,
                                    connection_reason="not_configured")

    app_key, secret_key, environment, markets = credentials_store.credentials()
    check, accounts = _probe(_build_credentials(app_key, secret_key, environment), markets)
    return CredentialsStatusOut(
        **settings,
        # IP 차단일 때만 외부 조회를 한다 — 정상일 때 매번 부를 이유가 없다.
        public_ip=_public_ip() if check.get("reason") == "ip_not_allowed" else None,
        connection_ok=bool(check.get("ok")),
        connection_reason=check.get("reason"),
        connection_message=check.get("message"),
        accounts=accounts,
    )


@router.post("/credentials", response_model=CredentialsStatusOut)
def register_credentials(body: CredentialsIn) -> CredentialsStatusOut:
    """키를 검증한 뒤 저장한다.

    ⚠️**검증 성공 후에만** 저장한다. 틀린 키를 저장해 두면 그 뒤 모든 동기화가
      조용히 실패하고, 화면에는 "왜 안 되지"만 남는다.
    """
    app_key = body.app_key.strip()
    secret_key = body.secret_key.strip()
    markets = [m.strip().upper() for m in body.markets if m.strip()] or ["US"]

    check, accounts = _probe(
        _build_credentials(app_key, secret_key, body.environment), markets
    )
    if not check.get("ok"):
        # 원인을 그대로 올린다 — IP 미등록을 자격증명 오류로 오해하면 멀쩡한 키를
        # 계속 재발급하게 된다.
        details = {"reason": check.get("reason")}
        if check.get("reason") == "ip_not_allowed":
            # "IP를 등록하세요"만으로는 *어떤* IP 인지 알 수 없다. 값을 같이 준다.
            details["public_ip"] = _public_ip()
        raise AppError(
            400,
            "BROKER_CONNECTION_FAILED",
            check.get("message") or "연결에 실패했습니다.",
            details,
        )

    credentials_store.save(app_key, secret_key, body.environment, markets)
    return CredentialsStatusOut(
        **credentials_store.read_settings(),
        connection_ok=True,
        connection_reason=None,
        connection_message="연결 확인 완료",
        accounts=accounts,
    )


@router.post("/sync", response_model=SyncResultOut)
def run_sync(db: Session = Depends(get_db)) -> SyncResultOut:
    """등록된 키로 전체 동기화를 한 번 돌린다(worker 핸들러 재사용)."""
    settings = credentials_store.read_settings()
    if not settings["configured"]:
        raise AppError(400, "NOT_CONFIGURED", "먼저 API 키를 등록하세요.")

    # 핸들러와 리졸버는 os.environ 을 본다 — 파일의 키를 프로세스로 올린다.
    if not credentials_store.load_into_environ():
        raise AppError(400, "NOT_CONFIGURED", "먼저 API 키를 등록하세요.")

    connection_id = _ensure_connection(db)
    job_id = _create_job(db)

    from handlers import sync_kiwoom_portfolio as handler

    logs: list[str] = []

    def log_job(_engine, _job_id, level, step, message, meta=None):
        logs.append(f"[{level}] {step}: {message}")

    try:
        result = handler.run(
            engine, job_id, {"connection_id": str(connection_id)}, "/tmp/pi-storage", log_job
        )
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 그대로 보여준다
        _finish_job(db, job_id, "FAILED", str(exc))
        raise AppError(502, "SYNC_FAILED", str(exc), {"logs": logs[-5:]}) from exc

    # ⚠️이력 동기화는 실패해도 예외를 던지지 않는다(잔고는 지키려고). 그대로 두면
    #   화면에 '성공'만 뜨고 체결·배당이 0 건인 이유를 알 수 없다 — 실측으로 겪었다.
    history_error = result.get("history_error")
    # ⚠️새 상태값("PARTIAL")을 만들지 않는다 — 프런트 JobStatus 는 PENDING/RUNNING/
    #   SUCCESS/FAILED 뿐이라, 모르는 값을 넣으면 화면이 조용히 깨진다.
    #   잔고는 실제로 저장됐으므로 SUCCESS 로 두고 **사유를 error 에 남긴다**.
    _finish_job(db, job_id, "SUCCESS", history_error)
    return SyncResultOut(
        ok=True,
        accounts_synced=result.get("accounts_synced", 0),
        positions=result.get("domestic_positions", 0) + result.get("us_positions", 0),
        trades=result.get("trades", 0),
        daily_performance=result.get("daily_performance", 0),
        realized_pnl=result.get("realized_pnl", 0),
        dividends=result.get("dividends", 0),
        message=(
            None
            if not history_error
            else f"잔고는 저장됐지만 이력 동기화가 실패했습니다: {history_error}"
        ),
    )


# ---- 연결/잡 보조 ------------------------------------------------------------

def _ensure_connection(db: Session) -> uuid.UUID:
    """brokerage_connections 행이 없으면 만든다 — 첫 연동에서 필요하다."""
    row = db.execute(
        text(
            "SELECT c.id FROM brokerage_connections c JOIN brokers b ON b.id = c.broker_id "
            "WHERE b.code = 'KIWOOM' ORDER BY c.created_at LIMIT 1"
        )
    ).first()
    if row is not None:
        return row[0]

    broker_id = db.execute(
        text("SELECT id FROM brokers WHERE code = 'KIWOOM'")
    ).scalar()
    if broker_id is None:
        broker_id = uuid.uuid4()
        db.execute(
            text("INSERT INTO brokers (id, code, name) VALUES (:i, 'KIWOOM', '키움증권')"),
            {"i": broker_id},
        )
    connection_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO brokerage_connections (id, broker_id, connection_name, environment) "
            "VALUES (:i, :b, '주계좌', :e)"
        ),
        {"i": connection_id, "b": broker_id, "e": credentials_store.read_settings()["environment"]},
    )
    db.commit()
    return connection_id


def _create_job(db: Session) -> uuid.UUID:
    job_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO jobs (id, job_type, status, started_at) "
            "VALUES (:i, 'SYNC_KIWOOM_PORTFOLIO', 'RUNNING', now())"
        ),
        {"i": job_id},
    )
    db.commit()
    return job_id


def _finish_job(db: Session, job_id: uuid.UUID, status: str, error: str | None) -> None:
    db.execute(
        text(
            "UPDATE jobs SET status = :s, error_message = :e, finished_at = now(), "
            "updated_at = now() WHERE id = :i"
        ),
        {"s": status, "e": error, "i": job_id},
    )
    db.commit()


@router.post("/sync/quick", response_model=QuickSyncResultOut)
def run_quick_sync(db: Session = Depends(get_db)) -> QuickSyncResultOut:
    """**가벼운** 동기화 — 잔고와 보유 종목만 갱신한다(실측 0.9초).

    전체 동기화(/sync)는 체결·일별성과·실현손익·배당까지 받아 2분 가까이 걸린다.
    화면을 자주 갱신하려고 그걸 돌리면 유량제한에 걸리고 노트북도 힘들다.
    "지금 얼마인가"만 알면 되는 주기적 갱신은 이 경로를 쓴다.

    이력(체결·배당 등)은 건드리지 않는다 — 몇 초마다 바뀌는 값이 아니다.
    """
    settings = credentials_store.read_settings()
    if not settings["configured"]:
        raise AppError(400, "NOT_CONFIGURED", "먼저 API 키를 등록하세요.")
    if not credentials_store.load_into_environ():
        raise AppError(400, "NOT_CONFIGURED", "먼저 API 키를 등록하세요.")

    import time
    import uuid as _uuid
    from datetime import datetime, timezone

    from brokers.registry import get_adapter_class
    from repositories import accounts as accounts_repo
    from repositories import assets as assets_repo
    from repositories import balances as balances_repo
    from repositories import positions as positions_repo
    from repositories import sectors as sectors_repo
    from brokers.kiwoom.adapter import normalize_account

    started = time.perf_counter()
    app_key, secret_key, environment, markets = credentials_store.credentials()
    credentials = _build_credentials(app_key, secret_key, environment)
    connection_id = _ensure_connection(db)
    broker_id = db.execute(
        text("SELECT broker_id FROM brokerage_connections WHERE id = :i"),
        {"i": connection_id},
    ).scalar()

    now = datetime.now(timezone.utc)
    total_positions = 0
    total_balances = 0

    try:
        adapter_cls = get_adapter_class("KIWOOM")
        with adapter_cls(credentials, markets=tuple(markets)) as adapter:
            for account_ref in adapter.fetch_accounts():
                portfolio = adapter.fetch_portfolio(account_ref)
                raw_account = {
                    "external_account_id": account_ref.external_account_id,
                    "account_name": account_ref.account_name,
                    "account_type": account_ref.account_type,
                }
                # 어댑터가 이미 정규화한 값을 다시 쓰지 않고, 기존 적재 경로와
                # 같은 모양을 만들기 위해 normalize 결과를 그대로 넘긴다 —
                # 전체 동기화와 저장 형식이 갈리면 화면의 숫자가 경로마다 달라진다.
                normalized = _normalized_from(adapter, account_ref, raw_account)
                with engine.begin() as conn:
                    account_id = accounts_repo.upsert_account(
                        conn, broker_id, connection_id, normalized
                    )
                    for balance in normalized["balances"]:
                        balances_repo.upsert_balance(conn, account_id, balance, now, None)
                        total_balances += 1
                    kept = []
                    for position in normalized["positions"]:
                        asset_id = assets_repo.upsert_asset(conn, position)
                        positions_repo.upsert_position(
                            conn, account_id, asset_id, position, now, None
                        )
                        kept.append(asset_id)
                        total_positions += 1
                    positions_repo.delete_absent_positions(conn, account_id, kept)
                    # 새로 산 종목이 미분류로 남지 않게 기본 섹터를 붙인다.
                    sectors_repo.apply_sector_seed(conn)
    except Exception as exc:  # noqa: BLE001 - 원인을 그대로 보여준다
        raise AppError(502, "SYNC_FAILED", str(exc)) from exc

    return QuickSyncResultOut(
        ok=True,
        positions=total_positions,
        balances=total_balances,
        as_of=now.isoformat(),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


def _normalized_from(adapter, account_ref, raw_account) -> dict:
    """전체 동기화와 **같은** 정규화 경로를 탄다(저장 형식이 갈리지 않게)."""
    from brokers.kiwoom import domestic, us_equities
    from brokers.kiwoom.adapter import normalize_account

    client = adapter.client
    markets = adapter.markets

    balance = domestic.parse_balance([{"acnt_evlt_remn_indv_tot": []}])
    deposit = domestic.parse_deposit([{}])
    us_balance = us_deposit = us_detail = None

    if "KR" in markets:
        balance = domestic.parse_balance(domestic.fetch_balance(client, raw_account))
        deposit = domestic.parse_deposit(domestic.fetch_deposit(client, raw_account))
    if "US" in markets:
        us_balance = us_equities.parse_positions(
            us_equities.fetch_positions(client, raw_account)
        )
        us_deposit = us_equities.parse_deposit(
            us_equities.fetch_deposit(client, raw_account)
        )
        us_detail = us_equities.parse_deposit_detail(
            us_equities.fetch_deposit_detail(client, raw_account)
        )

    normalized = normalize_account(
        raw_account, balance, deposit, us_balance, us_deposit, us_detail
    )
    if "KR" not in markets:
        # 국내를 안 불렀으면 원화 예수금은 '모름'이다 — 0 이라고 단언하지 않는다.
        normalized["balances"] = [
            b for b in normalized["balances"]
            if b.get("currency") != "KRW" or b.get("cash_balance")
        ]
    return normalized
