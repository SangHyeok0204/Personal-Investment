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

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import credentials_store, daily_sync
from app.models import (
    AccountBalance,
    AccountDailyPerformance,
    CurrentPosition,
    Dividend,
    Job,
    Order,
    RealizedPnl,
    Trade,
)
from app.schemas import FreshnessOut, LedgerFreshnessOut
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


@router.get("/price-sources")
def get_price_sources() -> dict:
    """시세 소스 상태 — 연동/설정 화면용. ★2026-10-04: 화면 배지가 상태와 무관하게 '미등록'으로
    박혀 있었다(토스 키는 .env 에 있고 실제로 시세가 온다). 키는 내보내지 않는다 — 있는지만.

    ⚠️여기서 토스 토큰을 새로 받지 않는다(클라이언트당 유효 토큰 1개 — 페이지를 열 때마다
      발급하면 같은 키를 쓰는 다른 수집기를 끊는다). 순서는 `quote_cache._build_source` 와 같다.
    """
    from app.core import quote_cache

    toss_ok = bool(credentials_store.read_env_value("TOSS_CLIENT_ID")
                   and credentials_store.read_env_value("TOSS_CLIENT_SECRET"))
    us_open = quote_cache.us_regular_session_open()
    kiwoom_ok = bool(credentials_store.read_settings().get("configured"))
    toss_rank = (1 if us_open else 2) if toss_ok else None
    return {
        "us_regular_session_open": us_open,
        "sources": [
            {"id": "toss", "configured": toss_ok, "rank": toss_rank},
            {"id": "yahoo", "configured": True, "rank": 2 if (toss_ok and us_open) else 1},
            {"id": "kiwoom-quote", "configured": kiwoom_ok, "rank": None},
        ],
    }


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


#: pg_advisory_xact_lock 키 — 동기화 시작을 한 줄로 세운다(임의의 고정값).
_SYNC_LOCK_KEY = 720261005


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
    # ★2026-10-05 동기화는 한 번에 하나만. 한 회차가 ~2분인데, 그동안 브라우저 이력 타이머·
    #   16:30 따라잡기·수동 버튼이 겹쳐 두 번째 POST 를 보낼 수 있다 — 같은 원장을 두 번 쓰고
    #   키움 TR 도 두 배로 부른다. 확인과 RUNNING 행 생성을 advisory lock 으로 묶는다
    #   (lock 은 `_create_job` 의 commit 에서 풀린다).
    #   ⚠️`RUNNING_STALE_AFTER`(15분)보다 오래된 RUNNING 은 죽은 것으로 보고 막지 않는다.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SYNC_LOCK_KEY})
    if daily_sync.sync_running(db):
        db.rollback()
        raise AppError(
            409, "SYNC_IN_PROGRESS", "이미 동기화가 진행 중입니다. 끝난 뒤 다시 시도하세요."
        )
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
    # 에러는 아니지만 알려야 하는 것들(조용히 0건인 조회 등).
    history_notes = result.get("history_notes") or []
    # ⚠️새 상태값("PARTIAL")을 만들지 않는다 — 프런트 JobStatus 는 PENDING/RUNNING/
    #   SUCCESS/FAILED 뿐이라, 모르는 값을 넣으면 화면이 조용히 깨진다.
    #   잔고는 실제로 저장됐으므로 SUCCESS 로 두고 **사유를 error 에 남긴다**.
    _finish_job(db, job_id, "SUCCESS", history_error, result=result)
    return SyncResultOut(
        ok=True,
        accounts_synced=result.get("accounts_synced", 0),
        positions=result.get("domestic_positions", 0) + result.get("us_positions", 0),
        trades=result.get("trades", 0),
        daily_performance=result.get("daily_performance", 0),
        realized_pnl=result.get("realized_pnl", 0),
        dividends=result.get("dividends", 0),
        message=(
            f"잔고는 저장됐지만 이력 동기화가 실패했습니다: {history_error}"
            if history_error
            else (" ".join(history_notes) or None)
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


def fail_orphaned_syncs(db: Session) -> int:
    """API 가 막 떴을 때 남아 있는 **오래된** RUNNING 동기화는 죽은 것이다 — FAILED 로 닫는다.

    동기화는 워커가 아니라 **이 프로세스 안**(스레드)에서 돈다. 그래서 `--reload` 재시작·종료가
    도중에 끊으면 행이 RUNNING 으로 영영 남고, 리퍼(워커 심장박동용)도 손대지 않는다
    (실측 2026-10-04 15:10 회차). 그대로 두면 수집 상태가 '진행 중'에 멈춘다.

    ★2026-10-05 `RUNNING_STALE_AFTER`(15분)보다 오래된 행만 닫는다 — 다른 프로세스(테스트의
      TestClient 도 lifespan 을 돈다)가 막 시작한 회차를 죽은 것으로 덮지 않게.
      ⚠️API 프로세스는 하나라고 가정한다. 15분 안쪽의 끊긴 행은 여기서 못 닫지만, 그 시간이
      지나면 `sync_running` 이 무시하고 다음 재시작이 닫는다.
    ★2026-10-05 `result={"orphaned": true}` 로 표시한다 — 키움이 거절한 FAILED 와 달리
      재시도 간격을 걸지 않아, 켜자마자 따라잡기가 다시 돈다(`daily_sync.last_bad_attempt_at`).
    """
    n = db.execute(
        text(
            "UPDATE jobs SET status = 'FAILED', finished_at = now(), updated_at = now(), "
            "error_message = 'API 재시작으로 중단됨 — 다시 동기화하세요', "
            "result = CAST(:r AS JSONB) "
            "WHERE job_type = 'SYNC_KIWOOM_PORTFOLIO' AND status = 'RUNNING' "
            "AND COALESCE(started_at, created_at) < now() - make_interval(secs => :s)"
        ),
        {
            "r": json.dumps(daily_sync.ORPHANED_RESULT),
            "s": daily_sync.RUNNING_STALE_AFTER.total_seconds(),
        },
    ).rowcount
    db.commit()
    return n


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


def _finish_job(
    db: Session,
    job_id: uuid.UUID,
    status: str,
    error: str | None,
    result: dict | None = None,
) -> None:
    """작업을 끝내며 **결과도 남긴다.**

    ⚠️예전에는 상태와 에러만 적었다. 그래서 `jobs.result` 가 전 행 NULL 이었고,
      "배당 3종목을 건너뛰었다" 같은 경고가 **동기화 직후 한 번 뜨고 사라졌다**
      — 수집 상태 화면의 '최근 작업'은 그걸 알 길이 없었다. 경고를 만들어 놓고
      보여 주지 않으면 안 만든 것과 같다.

    ⚠️`error_message` 에 경고를 쑤셔 넣지 않는다. 그 칸은 **실패 사유**이고,
      화면이 그렇게 읽는다. 경고는 result 에 둔다.
    """
    db.execute(
        text(
            "UPDATE jobs SET status = :s, error_message = :e, result = CAST(:r AS JSONB), "
            "finished_at = now(), updated_at = now() WHERE id = :i"
        ),
        {
            "s": status,
            "e": error,
            "r": json.dumps(result, ensure_ascii=False, default=str) if result else None,
            "i": job_id,
        },
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
                # ⚠️예전에는 여기서 `adapter.fetch_portfolio()` 를 부르고 결과를 버렸다.
                #   아래 `_normalized_from` 이 같은 TR(ust21070·ust21110·ust21160)을
                #   **또** 부르므로 5초마다 TR 이 두 배로 나갔다(유량제한의 주범).
                #   결과를 쓰지 않는 호출이라 지워도 저장값은 그대로다.
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


# ── 수집 신선도 ──────────────────────────────────────────────────────────────

_FRESHNESS_NOTES = [
    "**잔고·보유 종목은 5초마다 자동**으로 갱신됩니다. 하지만 체결·배당·주문·"
    "일별성과는 **이력 동기화를 돌려야만** 들어옵니다 — 그 둘을 한 숫자로"
    " 뭉뚱그리면 '방금 동기화됨'이라고 적어 놓고 체결은 사흘 전 것을 보여 주게"
    " 됩니다.",
    "**원장 날짜가 며칠 전이어도 뒤처진 것이 아닐 수 있습니다.** 배당은 지급일에만"
    " 생기고 매매는 거래한 날에만 생깁니다. 뒤처짐의 기준은 원장 날짜가 아니라"
    " **마지막 이력 동기화 시각**입니다.",
    "마지막 동기화 이후 **미국 정규장이 닫힌 적이 있으면** 새 체결이 있을 수"
    " 있다고 봅니다. 실제로 거래가 없었다면 동기화해도 바뀌는 것이 없습니다.",
    "⚠️증권사 배치 시간(KST 05~07시)에는 이력이 비어서 올 수 있습니다 — 그때는"
    " 동기화를 피하세요.",
    "**영업일 16:30(KST)** 이후로 제대로 받아 온 적이 없으면 서버가 스스로 받아 둡니다"
    " (국내장 마감 직후). 그 시각에 서버가 꺼져 있었으면 다음에 켤 때 따라잡습니다"
    " — 브라우저를 열어 두지 않아도 됩니다.",
    "'제대로 받아 온' 회차는 **성공했고 일별성과가 0건이 아닌** 회차입니다. 진행 중·실패·"
    "0건(증권사 빈 응답) 회차는 최신으로 세지 않습니다. 실패·0건이면 **2시간 뒤** 다시"
    " 시도합니다(재시작으로 끊긴 회차는 바로). 동기화가 진행 중이면 새로 시작하지 않습니다.",
]

_LEDGERS: list[tuple[str, str, bool]] = [
    ("positions", "보유 종목", True),
    ("balances", "예수금·잔고", True),
    ("trades", "체결", False),
    ("orders", "주문", False),
    ("dividends", "배당", False),
    ("realized", "실현손익", False),
    ("daily_performance", "일별 성과", False),
]


def _last_us_close(now: datetime | None = None) -> datetime:
    """가장 최근에 지나간 미국 정규장 마감(평일 16:00 ET).

    ⚠️공휴일은 보지 않는다 — 휴장일이면 동기화해도 바뀌는 게 없으므로
      "받아 보라"고 한 번 더 말하는 쪽이 안전하다.
    """
    et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    candidate = et.replace(hour=16, minute=0, second=0, microsecond=0)
    if candidate > et:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


@router.get("/freshness", response_model=FreshnessOut)
def get_freshness(db: Session = Depends(get_db)) -> FreshnessOut:
    """이력을 마지막으로 언제 받았나 — 그리고 그 사이 장이 닫혔나."""
    job = db.execute(
        select(Job)
        .where(Job.job_type == "SYNC_KIWOOM_PORTFOLIO")
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_at = job.finished_at or job.created_at if job else None
    # ★'최신' 판정은 **제대로 받아 온** 마지막 회차로 한다 — 진행 중·실패·일별성과 0건(증권사
    #   빈 응답) 회차까지 세면, 받은 게 없는데도 '최신'으로 뜬다(실측 2026-10-03 토 09:12 회차).
    #   ★2026-10-05 그 정의는 16:30 따라잡기와 공유한다(`daily_sync.last_good_sync_at`).
    good_at = daily_sync.last_good_sync_at(db)
    now = datetime.now(timezone.utc)
    last_close = _last_us_close(now)
    hours = (
        Decimal((now - last_at).total_seconds() / 3600).quantize(Decimal("0.1"))
        if last_at
        else None
    )

    counts: list[LedgerFreshnessOut] = []
    for key, label, auto in _LEDGERS:
        model, column = {
            "positions": (CurrentPosition, CurrentPosition.as_of),
            "balances": (AccountBalance, AccountBalance.as_of),
            "trades": (Trade, Trade.trade_date),
            "orders": (Order, Order.order_date),
            "dividends": (Dividend, Dividend.pay_date),
            "realized": (RealizedPnl, RealizedPnl.sell_date),
            "daily_performance": (
                AccountDailyPerformance,
                AccountDailyPerformance.base_date,
            ),
        }[key]
        last, total = db.execute(
            select(func.max(column), func.count()).select_from(model)
        ).one()
        counts.append(
            LedgerFreshnessOut(
                key=key, label=label,
                last_date=last.date() if isinstance(last, datetime) else last,
                row_count=total or 0, auto=auto,
            )
        )

    return FreshnessOut(
        last_history_sync_at=last_at,
        last_history_sync_status=job.status if job else None,
        hours_since=hours,
        # ⚠️"몇 시간 지났나"로 판정하지 않는다. 주말에는 사흘이 지나도 받을 게
        #   없고, 장 마감 직후에는 한 시간만 지나도 받을 게 있다.
        stale=bool(good_at is None or good_at < last_close),
        # ★2026-10-05 진행 중이면 브라우저가 두 번째 동기화를 보내지 않게 알린다.
        syncing=daily_sync.sync_running(db, now),
        last_market_close_at=last_close,
        ledgers=counts,
        notes=_FRESHNESS_NOTES,
    )
