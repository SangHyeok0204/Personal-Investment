"""Tests for the SYNC_KIWOOM_PORTFOLIO handler.

httpx is mocked at the client boundary (a fake .post that dispatches by the
api-id header). Fixture payloads use the field names from kiwoom-api-reference.md
§2/§4. No live API calls. Requires a Postgres test DB (skips otherwise, like the
round-1 tests); `pytest --collect-only` works without a DB.
"""
import json
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

import main
import handlers.sync_kiwoom_portfolio as handler_mod
from brokers.kiwoom import auth, domestic
from brokers.kiwoom.adapter import to_decimal
from brokers.kiwoom.client import KiwoomClient


# --------------------------------------------------------------------------- #
# httpx fake (client boundary)
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    """Stands in for httpx.Client; dispatches TR calls by the api-id header.

    tr_responses maps api-id -> FakeResponse | list[FakeResponse] (paging) |
    callable(headers, body) -> FakeResponse.
    """

    def __init__(self, tr_responses, token_response=None):
        self._tr = tr_responses
        self._token_response = token_response or FakeResponse(
            {
                "token": "tok-secret-abc",
                "token_type": "bearer",
                # Far future so the module-level cache never expires mid-test.
                "expires_dt": "20991231235959",
                "return_code": 0,
                "return_msg": "정상적으로 처리되었습니다",
            }
        )
        self.token_calls = 0
        self.tr_calls = []
        self._page_cursor = {}

    def post(self, url, headers=None, json=None):
        headers = headers or {}
        if url.endswith("/oauth2/token"):
            self.token_calls += 1
            return self._token_response
        api_id = headers.get("api-id")
        self.tr_calls.append((api_id, headers.get("cont-yn"), headers.get("next-key")))
        entry = self._tr[api_id]
        if callable(entry):
            return entry(headers, json)
        if isinstance(entry, list):
            index = self._page_cursor.get(api_id, 0)
            self._page_cursor[api_id] = min(index + 1, len(entry) - 1)
            return entry[index]
        return entry

    def close(self):
        pass


# --------------------------------------------------------------------------- #
# response fixtures (kiwoom-api-reference field names)
# --------------------------------------------------------------------------- #

def _account_list_response():
    return FakeResponse(
        {
            "acnt_list": [
                {"acnt_no": "1234567890", "acnt_nm": "위탁종합", "acnt_tp": "01"},
            ],
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
        }
    )


def _deposit_response():
    return FakeResponse(
        {
            "entr": "1500000",
            "pymn_alow_amt": "1450000",
            "ord_alow_amt": "1450000",
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
        }
    )


def _holding(stk_cd, stk_nm, qty, pur, cur, evlt, pur_amt, pnl, rt):
    return {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "rmnd_qty": qty,
        "pur_pric": pur,
        "cur_prc": cur,
        "evlt_amt": evlt,
        "pur_amt": pur_amt,
        "evltv_prft": pnl,
        "prft_rt": rt,
    }


SAMSUNG = _holding("005930", "삼성전자", "100", "70000", "72000", "7200000", "7000000", "200000", "2.85")
HYNIX = _holding("000660", "SK하이닉스", "50", "120000", "130000", "6500000", "6000000", "500000", "8.33")


def _balance_response(holdings):
    return FakeResponse(
        {
            "tot_pur_amt": "13000000",
            "tot_evlt_amt": "13700000",
            "tot_evlt_pl": "700000",
            "tot_prft_rt": "5.38",
            "prsm_dpst_aset_amt": "15200000",
            "acnt_evlt_remn_indv_tot": holdings,
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
        }
    )


def _happy_responses(holdings):
    return {
        "ka00001": _account_list_response(),
        "kt00001": _deposit_response(),
        "kt00018": _balance_response(holdings),
    }


# --------------------------------------------------------------------------- #
# db / harness helpers
# --------------------------------------------------------------------------- #

def _seed_broker_and_connection(engine):
    broker_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO brokers (id, code, name, is_active, created_at, updated_at) "
                "VALUES (:id, 'KIWOOM', '키움증권', TRUE, now(), now())"
            ),
            {"id": broker_id},
        )
        conn.execute(
            text(
                "INSERT INTO brokerage_connections (id, broker_id, connection_name, "
                "environment, status, created_at, updated_at) "
                "VALUES (:id, :broker_id, '키움 기본 연결', 'REAL', 'CONFIGURED', now(), now())"
            ),
            {"id": connection_id, "broker_id": broker_id},
        )
    return broker_id, connection_id


def _insert_sync_job(engine, payload=None):
    job_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (id, job_type, status, payload, created_at, updated_at) "
                "VALUES (:id, 'SYNC_KIWOOM_PORTFOLIO', 'PENDING', CAST(:payload AS JSONB), "
                "now(), now())"
            ),
            {"id": job_id, "payload": json.dumps(payload or {})},
        )
    return job_id


def _get_job(engine, job_id):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM jobs WHERE id=:id"), {"id": job_id}).mappings().first()
    return dict(row)


def _get_job_logs(engine, job_id):
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text("SELECT * FROM job_logs WHERE job_id=:id ORDER BY created_at"),
                {"id": job_id},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def _get_connection(engine, connection_id):
    with engine.begin() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM brokerage_connections WHERE id=:id"),
                {"id": connection_id},
            )
            .mappings()
            .first()
        )
    return dict(row)


def _count(engine, table):
    with engine.begin() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def _query(engine, sql):
    with engine.begin() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _reset_env_and_cache(monkeypatch):
    auth.reset_token_cache()
    monkeypatch.setenv("KIWOOM_APP_KEY", "test-app-key")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("KIWOOM_API_BASE_URL", "https://mockapi.kiwoom.com")
    yield
    auth.reset_token_cache()


@pytest.fixture
def patch_client(monkeypatch):
    """Install a factory so the handler builds a KiwoomClient over the fake http."""

    def _install(fake_http):
        def factory(base_url, app_key, secret_key):
            return KiwoomClient(
                base_url, app_key, secret_key, http_client=fake_http, sleep=lambda _s: None
            )

        monkeypatch.setattr(handler_mod, "KiwoomClient", factory)

    return _install


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #

def test_missing_keys_fails_at_validate(db, tmp_path, monkeypatch):
    monkeypatch.setenv("KIWOOM_APP_KEY", "")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "")
    _broker_id, connection_id = _seed_broker_and_connection(db)
    job_id = _insert_sync_job(db, {"connection_id": str(connection_id)})

    assert main.run_one_cycle(db, str(tmp_path)) is True

    job = _get_job(db, job_id)
    assert job["status"] == "FAILED"
    assert "not configured" in job["error_message"]

    conn_row = _get_connection(db, connection_id)
    assert conn_row["status"] == "ERROR"
    assert "not configured" in (conn_row["last_error"] or "")

    steps = [log["step"] for log in _get_job_logs(db, job_id)]
    assert "validate_configuration" in steps


def test_domestic_happy_path(db, tmp_path, patch_client):
    _broker_id, connection_id = _seed_broker_and_connection(db)
    fake = FakeHttpClient(_happy_responses([SAMSUNG, HYNIX]))
    patch_client(fake)
    job_id = _insert_sync_job(db, {"connection_id": str(connection_id)})

    assert main.run_one_cycle(db, str(tmp_path)) is True

    job = _get_job(db, job_id)
    assert job["status"] == "SUCCESS", job.get("error_message")
    result = job["result"]
    assert result["accounts_synced"] == 1
    assert result["domestic_positions"] == 2
    assert result["us_positions"] == 0
    assert result["cash_balances"] == 1
    assert result["snapshots_created"] == 1
    assert result["us_supported"] is False
    assert "synced_at" in result

    assert _count(db, "accounts") == 1
    assert _count(db, "assets") == 2
    assert _count(db, "current_positions") == 2
    assert _count(db, "account_balances") == 1
    assert _count(db, "portfolio_snapshots") == 1
    assert _count(db, "position_snapshots") == 2

    account = _query(db, "SELECT * FROM accounts")[0]
    assert account["external_account_id"] == "1234567890"
    assert account["account_number_masked"] == "1234****90"

    positions = {
        row["ticker"]: row
        for row in _query(
            db,
            "SELECT a.ticker, cp.quantity, cp.market_value_krw, cp.exchange_rate, "
            "cp.unrealized_pnl_local FROM current_positions cp "
            "JOIN assets a ON a.id = cp.asset_id",
        )
    }
    assert positions["005930"]["quantity"] == Decimal("100")
    assert positions["005930"]["market_value_krw"] == Decimal("7200000")
    assert positions["005930"]["exchange_rate"] == Decimal("1.0")
    assert positions["000660"]["unrealized_pnl_local"] == Decimal("500000")

    balance = _query(db, "SELECT * FROM account_balances")[0]
    assert balance["currency"] == "KRW"
    assert balance["cash_balance"] == Decimal("1500000")
    assert balance["total_market_value_local"] == Decimal("13700000")

    # raw files written + registered, secrets never on disk
    raw_rows = _query(db, "SELECT * FROM broker_api_raw_responses")
    assert len(raw_rows) == 3
    for row in raw_rows:
        abs_path = os.path.join(str(tmp_path), row["response_file_path"])
        assert os.path.isfile(abs_path)
        assert row["response_hash"]
        with open(abs_path, encoding="utf-8") as handle:
            assert "tok-secret-abc" not in handle.read()

    # token-metadata.json holds ONLY issued_at/expires_at (never the token)
    raw_dir = os.path.dirname(os.path.join(str(tmp_path), raw_rows[0]["response_file_path"]))
    meta_path = os.path.join(raw_dir, "token-metadata.json")
    assert os.path.isfile(meta_path)
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    assert set(meta.keys()) == {"issued_at", "expires_at"}

    conn_row = _get_connection(db, connection_id)
    assert conn_row["status"] == "CONNECTED"
    assert conn_row["last_synced_at"] is not None
    assert conn_row["last_error"] is None

    steps = [log["step"] for log in _get_job_logs(db, job_id)]
    for expected in [
        "validate_configuration",
        "request_access_token",
        "fetch_accounts",
        "fetch_domestic_balance",
        "fetch_domestic_positions",
        "fetch_us_balance",
        "fetch_us_positions",
        "save_raw_responses",
        "normalize_assets",
        "upsert_accounts",
        "upsert_positions",
        "create_snapshots",
        "complete",
    ]:
        assert expected in steps


def test_sold_position_removed_on_next_sync(db, tmp_path, patch_client):
    _broker_id, connection_id = _seed_broker_and_connection(db)

    patch_client(FakeHttpClient(_happy_responses([SAMSUNG, HYNIX])))
    _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))
    assert _count(db, "current_positions") == 2
    assert _count(db, "portfolio_snapshots") == 1

    # Second sync: Hynix sold, only Samsung remains.
    patch_client(FakeHttpClient(_happy_responses([SAMSUNG])))
    job2 = _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))

    assert _get_job(db, job2)["status"] == "SUCCESS"
    remaining = _query(
        db, "SELECT a.ticker FROM current_positions cp JOIN assets a ON a.id = cp.asset_id"
    )
    assert {r["ticker"] for r in remaining} == {"005930"}
    # snapshots keep history; assets are not deleted
    assert _count(db, "portfolio_snapshots") == 2
    assert _count(db, "position_snapshots") == 3
    assert _count(db, "assets") == 2


def test_token_cached_across_syncs(db, tmp_path, patch_client):
    _broker_id, connection_id = _seed_broker_and_connection(db)
    fake = FakeHttpClient(_happy_responses([SAMSUNG]))
    patch_client(fake)  # same fake reused for both syncs

    _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))
    job2 = _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))

    assert _get_job(db, job2)["status"] == "SUCCESS"
    assert fake.token_calls == 1  # issued once, reused on the second sync


def test_api_error_fails_with_return_msg(db, tmp_path, patch_client):
    _broker_id, connection_id = _seed_broker_and_connection(db)
    fake = FakeHttpClient(
        {
            "ka00001": FakeResponse({"return_code": 3, "return_msg": "조회할 데이터가 없습니다"}),
            "kt00001": _deposit_response(),
            "kt00018": _balance_response([SAMSUNG]),
        }
    )
    patch_client(fake)
    job_id = _insert_sync_job(db, {"connection_id": str(connection_id)})

    main.run_one_cycle(db, str(tmp_path))

    job = _get_job(db, job_id)
    assert job["status"] == "FAILED"
    assert "조회할 데이터가 없습니다" in job["error_message"]

    conn_row = _get_connection(db, connection_id)
    assert conn_row["status"] == "ERROR"
    assert "조회할 데이터가 없습니다" in (conn_row["last_error"] or "")


def test_unexpected_shape_fails(db, tmp_path, patch_client):
    _broker_id, connection_id = _seed_broker_and_connection(db)
    fake = FakeHttpClient(
        {
            "ka00001": _account_list_response(),
            "kt00001": _deposit_response(),
            # holdings must be a list; a scalar triggers a pydantic ValidationError
            "kt00018": FakeResponse(
                {
                    "tot_evlt_amt": "1",
                    "acnt_evlt_remn_indv_tot": "not-a-list",
                    "return_code": 0,
                    "return_msg": "ok",
                }
            ),
        }
    )
    patch_client(fake)
    job_id = _insert_sync_job(db, {"connection_id": str(connection_id)})

    main.run_one_cycle(db, str(tmp_path))

    job = _get_job(db, job_id)
    assert job["status"] == "FAILED"
    assert "unexpected response shape" in job["error_message"]
    assert "raw saved" in job["error_message"]
    assert _get_connection(db, connection_id)["status"] == "ERROR"


def test_client_retries_on_rate_limit_then_succeeds():
    calls = {"n": 0}

    def kt00018(headers, body):
        calls["n"] += 1
        if calls["n"] < 3:  # rate-limited twice (return_code=5), then OK
            return FakeResponse({"return_code": 5, "return_msg": "요청 유량 초과"})
        return FakeResponse({"acnt_evlt_remn_indv_tot": [], "return_code": 0})

    client = KiwoomClient(
        "https://mockapi.kiwoom.com",
        "k",
        "s",
        http_client=FakeHttpClient({"kt00018": kt00018}),
        sleep=lambda _s: None,
    )
    pages = client.request_tr("kt00018", {"qry_tp": "1"})
    assert calls["n"] == 3
    assert pages[0]["return_code"] == 0


def test_client_paging_follows_header_cont_yn():
    page1 = FakeResponse(
        {"acnt_evlt_remn_indv_tot": [SAMSUNG], "return_code": 0},
        headers={"cont-yn": "Y", "next-key": "KEY1"},
    )
    page2 = FakeResponse(
        {"acnt_evlt_remn_indv_tot": [HYNIX], "return_code": 0},
        headers={"cont-yn": "N", "next-key": ""},
    )
    fake = FakeHttpClient({"kt00018": [page1, page2]})
    client = KiwoomClient(
        "https://mockapi.kiwoom.com", "k", "s", http_client=fake, sleep=lambda _s: None
    )
    pages = client.request_tr("kt00018", {"qry_tp": "1"})

    assert len(pages) == 2
    tr_calls = [c for c in fake.tr_calls if c[0] == "kt00018"]
    assert tr_calls[0][1] == "N"  # first page: cont-yn=N
    assert tr_calls[1][1] == "Y"  # second page: cont-yn=Y ...
    assert tr_calls[1][2] == "KEY1"  # ... carrying the next-key from page 1
    merged = domestic.parse_balance(pages)
    assert len(merged.acnt_evlt_remn_indv_tot) == 2


def test_to_decimal_edge_cases():
    assert to_decimal(None) is None
    assert to_decimal("") is None
    assert to_decimal("   ") is None
    assert to_decimal("+") is None
    assert to_decimal("-") is None
    assert to_decimal("abc") is None
    assert to_decimal(True) is None
    assert to_decimal("007") == Decimal("7")
    assert to_decimal("0070") == Decimal("70")
    assert to_decimal("1,234.56") == Decimal("1234.56")
    assert to_decimal("-5.00") == Decimal("-5")
    assert to_decimal("+3") == Decimal("3")
    assert to_decimal("  0012340  ") == Decimal("12340")
    assert to_decimal(100) == Decimal("100")
    assert to_decimal(Decimal("9.99")) == Decimal("9.99")
