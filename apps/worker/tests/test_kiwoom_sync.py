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
from brokers.kiwoom.adapter import normalize_ticker, normalize_us_ticker, to_decimal, us_market
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
        self.tr_calls.append((api_id, headers.get("cont-yn"), headers.get("next-key"), url))
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
    """Real ka00001 shape (live-confirmed 2026-07-12): ONE camelCase scalar, no array.

    The account number here is a stand-in — never the real one.
    """
    return FakeResponse(
        {
            "acctNo": "1234567890",
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
        }
    )


def _deposit_response():
    """Real kt00001 shape (live-confirmed): zero-padded strings + 통화별 예수금 array.

    Mirrors the live situation where a same-day buy is still settling: `entr`
    (D+0) still holds the cash owed for it, while `d2_entra` is what actually
    survives settlement. Values scrubbed.
    """
    return FakeResponse(
        {
            "entr": "000000005000000",  # D+0 예수금 — 4.8M of it owed for an unsettled buy
            "d2_entra": "000000000200000",  # D+2 예수금 — the real free cash
            "pymn_alow_amt": "000000000150000",  # 출금가능금액 (D+1)
            "d2_pymn_alow_amt": "000000000120000",  # 출금가능금액 (D+2) — preferred
            "ord_alow_amt": "000000000150000",
            "profa_ch": "000000004800000",
            "stk_entr_prst": [
                {
                    "crnc_cd": "USD",
                    "fx_entr": "1000.50",
                    "pymn_alow_amt_entr": "",
                    "fc_krw_repl_evlta": "0.00",
                }
            ],
            "return_code": 0,
            "return_msg": "조회가 완료되었습니다",
        }
    )


def _holding(stk_cd, stk_nm, qty, able_qty, pur, cur, evlt, pur_amt, pnl, rt):
    return {
        "stk_cd": stk_cd,  # live form is "A"-prefixed
        "stk_nm": stk_nm,
        "rmnd_qty": qty,
        "trde_able_qty": able_qty,
        "pur_pric": pur,
        "cur_prc": cur,
        "evlt_amt": evlt,
        "pur_amt": pur_amt,
        "evltv_prft": pnl,
        "prft_rt": rt,
    }


SAMSUNG = _holding(
    "A005930", "삼성전자", "000000000000010", "000000000000010",
    "000000000070000", "000000072000", "000000000720000", "000000000700000",
    "000000000018000", "2.57",
)
HYNIX = _holding(
    "A000660", "SK하이닉스", "000000000000005", "000000000000005",
    "000000000200000", "000000190000", "000000000950000", "000000001000000",
    "-00000000052000", "-5.20",
)


def _balance_response(holdings):
    """Real kt00018 shape (live-confirmed): zero-padded/signed strings."""
    return FakeResponse(
        {
            "tot_pur_amt": "000000001700000",
            "tot_evlt_amt": "000000001670000",
            "tot_evlt_pl": "-00000000034000",
            "tot_prft_rt": "-2.00",
            "prsm_dpst_aset_amt": "000000001850000",  # 키움 자체 산출 총자산
            "acnt_evlt_remn_indv_tot": holdings,
            "return_code": 0,
            "return_msg": "조회가 완료되었습니다",
        }
    )


# ---- US (해외주식) — real ust21070/ust21110/ust21160 shapes, scrubbed values ----

def _us_holding(stk_cd, name, qty, poss_qty, sell_alowq, book_uv, book_amt,
                now_pric, evlt, pl, pl_rt, evlt_krw, pl_krw):
    return {
        "stk_cd": stk_cd,
        "frgn_stk_nm": name,
        "qty": qty,  # NOT the holding size — excludes unsettled buys
        "poss_qty": poss_qty,  # the real 보유수량
        "sell_alowq": sell_alowq,
        "frgn_stk_book_uv": book_uv,
        "frgn_stk_book_amt": book_amt,
        "now_pric": now_pric,
        "evlt_amt": evlt,
        "pl_amt": pl,
        "pl_rt": pl_rt,
        "evlt_amt_krw": evlt_krw,
        "pl_amt_krw": pl_krw,
        "exch_rate": "1500.00",
        "crnc_code": "USD",
        "natn_nm": "미국",
        "stex_nm": "미국",  # not NASDAQ/NYSE -> market falls back to "US"
    }


# evlt_amt_krw is deliberately 2,699,999 while evlt_amt x exch_rate == 2,700,000.
# If we ever start computing FX ourselves this assertion breaks — that is the point.
US_AAPL = _us_holding(
    "AAPL", "애플", "10", "10", "10", "150.00", "1500.00",
    "180.00", "1800.00", "300.00", "20.00", "000002699999", "000000450000",
)
# qty(1) != poss_qty(4): unsettled buys. Using qty would understate the holding.
US_MSFT = _us_holding(
    "MSFT", "마이크로소프트", "1", "4", "4", "200.00", "800.00",
    "250.00", "1000.00", "200.00", "25.00", "000001500000", "000000300000",
)
# qty == 0 while poss_qty == 2: using qty would DROP this holding entirely.
US_ZERO = _us_holding(
    "SKHYV", "SK하이닉스 ADR", "0", "2", "2", "50.00", "100.00",
    "60.00", "120.00", "20.00", "20.00", "000000180000", "000000030000",
)


def _us_balance_response(holdings):
    """ust21070 해외 잔고."""
    return FakeResponse(
        {
            "crnc_code": "USD",
            "tot_evlt_amt": "2920.0000",
            "tot_evlt_amt_krw": "000000004379999",
            "tot_prch_amt": "2400.0000",
            "tot_prch_amt_krw": "000000003600000",
            "tot_pl_amt": "520.0000",
            "tot_pl_amt_krw": "000000000780000",
            "tot_pl_rt": "21.67",
            "result_list": holdings,
            "return_code": 0,
            "return_msg": "계좌잔고내역이 조회되었습니다.",
        }
    )


def _us_deposit_response():
    """ust21110 해외 예수금. fc_entra is D+0 and still holds the USD owed for
    pending buys — the settled figure lives in ust21160."""
    return FakeResponse(
        {
            "krw_entra": "000000005000000",
            "result_list": [
                {
                    "crnc_code": "USD",
                    "crnc_nm": "미국달러",
                    "fc_entra": "1000.00",  # D+0
                    "fc_pymn_alowa": "600.00",  # 출금가능
                    "fc_ord_alowa": "600.00",
                    "fc_booka": "000000001500000",
                }
            ],
            "return_code": 0,
            "return_msg": "조회가 완료되었습니다",
        }
    )


def _us_deposit_detail_response():
    """ust21160 — the ONLY source of usd_exch_rate and the settled D+2 USD cash."""
    return FakeResponse(
        {
            "won_entr": "000000005000000",
            "usd_exch_rate": "1,400.50",  # comma-formatted; != the 1500.00 position rate
            "d0_usd_fx_entr": "1000.000",
            "d2_usd_fx_entr": "600.000",  # 400 USD owed for pending buys
            "return_code": 0,
            "return_msg": "해외증권 예수금 상세현황이 조회 되었습니다.",
        }
    )


US_HOLDINGS = [US_AAPL, US_MSFT, US_ZERO]


def _happy_responses(holdings, us_holdings=None):
    return {
        "ka00001": _account_list_response(),
        "kt00001": _deposit_response(),
        "kt00018": _balance_response(holdings),
        "ust21070": _us_balance_response(
            US_HOLDINGS if us_holdings is None else us_holdings
        ),
        "ust21110": _us_deposit_response(),
        "ust21160": _us_deposit_detail_response(),
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


def test_full_sync_happy_path(db, tmp_path, patch_client):
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
    assert result["us_positions"] == 3
    assert result["cash_balances"] == 2  # KRW + USD
    assert result["snapshots_created"] == 1
    assert result["us_supported"] is True
    assert "synced_at" in result

    assert _count(db, "accounts") == 1
    assert _count(db, "assets") == 5  # 2 KR + 3 US
    assert _count(db, "current_positions") == 5
    assert _count(db, "account_balances") == 2
    assert _count(db, "portfolio_snapshots") == 1
    assert _count(db, "position_snapshots") == 5

    account = _query(db, "SELECT * FROM accounts")[0]
    assert account["external_account_id"] == "1234567890"
    assert account["account_number_masked"] == "1234****90"
    # ka00001 carries no name/type -> documented display fallback, not API data
    assert account["account_name"] == "위탁종합"
    assert account["base_currency"] == "KRW"

    # the US TRs must go to /api/us/acnt, not the domestic account path
    us_urls = {c[3] for c in fake.tr_calls if c[0].startswith("ust")}
    assert us_urls == {"https://mockapi.kiwoom.com/api/us/acnt"}

    positions = {
        row["ticker"]: row
        for row in _query(
            db,
            "SELECT a.ticker, a.country, a.market, a.currency, cp.quantity, "
            "cp.available_quantity, cp.market_value_krw, cp.exchange_rate, "
            "cp.unrealized_pnl_local, cp.unrealized_pnl_krw, cp.purchase_amount_local "
            "FROM current_positions cp JOIN assets a ON a.id = cp.asset_id",
        )
    }
    assert set(positions) == {"005930", "000660", "AAPL", "MSFT", "SKHYV"}

    # --- domestic: "A005930" normalized to the canonical KRX ticker
    assert positions["005930"]["country"] == "KR"
    assert positions["005930"]["market"] == "KRX"
    assert positions["005930"]["quantity"] == Decimal("10")
    assert positions["005930"]["available_quantity"] == Decimal("10")  # trde_able_qty
    assert positions["005930"]["market_value_krw"] == Decimal("720000")
    assert positions["005930"]["exchange_rate"] == Decimal("1.0")
    assert positions["000660"]["unrealized_pnl_local"] == Decimal("-52000")

    # --- US
    aapl = positions["AAPL"]
    assert aapl["country"] == "US"
    assert aapl["market"] == "US"  # stex_nm "미국" is not NASDAQ/NYSE/AMEX
    assert aapl["currency"] == "USD"
    assert aapl["quantity"] == Decimal("10")
    assert aapl["exchange_rate"] == Decimal("1500.00")
    # KRW comes STRAIGHT from Kiwoom: evlt_amt_krw is 2,699,999, while computing
    # evlt_amt x exch_rate would give 2,700,000. If this ever reads 2700000 we have
    # started doing our own FX math, which the contract forbids.
    assert aapl["market_value_krw"] == Decimal("2699999")
    assert aapl["unrealized_pnl_krw"] == Decimal("450000")

    # poss_qty, not qty: MSFT reports qty=1 but really holds 4 (unsettled buys)
    assert positions["MSFT"]["quantity"] == Decimal("4")
    assert positions["MSFT"]["available_quantity"] == Decimal("4")  # sell_alowq
    # qty=0 while poss_qty=2 — using qty would have dropped this holding entirely
    assert positions["SKHYV"]["quantity"] == Decimal("2")

    balances = {row["currency"]: row for row in _query(db, "SELECT * FROM account_balances")}
    assert set(balances) == {"KRW", "USD"}
    krw = balances["KRW"]
    # cash is the SETTLED D+2 balance — not kt00001.entr (5,000,000) and not
    # ust21110.krw_entra (5,000,000); either would double-count an unsettled buy.
    assert krw["cash_balance"] == Decimal("200000")
    # D+2 출금가능 (120,000) wins over the D+1 pymn_alow_amt (150,000) so that
    # available_cash can never exceed the D+2 cash_balance
    assert krw["available_cash"] == Decimal("120000")
    assert krw["available_cash"] <= krw["cash_balance"]
    assert krw["exchange_rate"] == Decimal("1.0")
    assert krw["total_market_value_local"] == Decimal("1670000")
    # total_evaluation_amount_* is 키움 추정예탁자산 (계좌 전체 = 현금 + 주식) — a
    # reconciliation figure, NOT this row's cash. apps/api surfaces it as
    # estimated_total_assets_krw and never sums it as cash (§10 ⚠️).
    assert krw["total_evaluation_amount_krw"] == Decimal("1850000")

    usd = balances["USD"]
    # settled D+2 USD (600), NOT fc_entra D+0 (1000) and NOT kt00001's fx_entr (1000.50):
    # the 400 USD gap is owed for buys whose shares are already counted in poss_qty.
    assert usd["cash_balance"] == Decimal("600.00")
    assert usd["available_cash"] == Decimal("600.00")  # fc_pymn_alowa
    assert usd["exchange_rate"] == Decimal("1400.50")  # usd_exch_rate, comma-parsed
    # the API derives USD cash in KRW as cash_balance x exchange_rate; we must NOT
    # repurpose the 추정예탁자산 columns to carry it.
    assert usd["total_evaluation_amount_krw"] is None
    assert usd["total_evaluation_amount_local"] is None

    snapshot = _query(db, "SELECT * FROM portfolio_snapshots")[0]
    # 1,670,000 domestic + 4,379,999 US (Kiwoom's own KRW figures)
    assert snapshot["securities_value_krw"] == Decimal("6049999")
    assert snapshot["cash_value_krw"] == Decimal("1040300")  # 200,000 + 840,300
    assert snapshot["total_assets_krw"] == Decimal("7090299")
    # real purchase total, never `securities - pnl`
    assert snapshot["total_purchase_amount_krw"] == Decimal("5300000")
    assert snapshot["total_unrealized_pnl_krw"] == Decimal("746000")

    # raw files written + registered, secrets never on disk
    raw_rows = _query(db, "SELECT * FROM broker_api_raw_responses")
    assert len(raw_rows) == 6  # ka00001, kt00001, kt00018, ust21110, ust21160, ust21070
    assert {r["api_category"] for r in raw_rows} == {"domestic", "us"}
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
    """Sold-position cleanup must span BOTH markets (same account, different assets)."""
    _broker_id, connection_id = _seed_broker_and_connection(db)

    patch_client(FakeHttpClient(_happy_responses([SAMSUNG, HYNIX])))
    _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))
    assert _count(db, "current_positions") == 5  # 2 KR + 3 US
    assert _count(db, "portfolio_snapshots") == 1

    # Second sync: Hynix sold (domestic) AND MSFT sold (US).
    patch_client(
        FakeHttpClient(_happy_responses([SAMSUNG], us_holdings=[US_AAPL, US_ZERO]))
    )
    job2 = _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))

    assert _get_job(db, job2)["status"] == "SUCCESS"
    remaining = _query(
        db, "SELECT a.ticker FROM current_positions cp JOIN assets a ON a.id = cp.asset_id"
    )
    assert {r["ticker"] for r in remaining} == {"005930", "AAPL", "SKHYV"}
    # snapshots keep history; assets are not deleted
    assert _count(db, "portfolio_snapshots") == 2
    assert _count(db, "position_snapshots") == 8  # 5 + 3
    assert _count(db, "assets") == 5


def test_us_sync_does_not_overwrite_krw_cash_row(db, tmp_path, patch_client):
    """ust21110 also returns krw_entra (a D+0 figure, 5,000,000 in the fixture).

    account_balances is UNIQUE(account_id, currency), so upserting it as a KRW row
    would OVERWRITE the settled row from kt00001 (d2_entra = 200,000) and silently
    restore the double-count. Only foreign-currency rows may come from the US TR.
    """
    _broker_id, connection_id = _seed_broker_and_connection(db)
    patch_client(FakeHttpClient(_happy_responses([SAMSUNG, HYNIX])))
    _insert_sync_job(db, {"connection_id": str(connection_id)})
    main.run_one_cycle(db, str(tmp_path))

    balances = {r["currency"]: r for r in _query(db, "SELECT * FROM account_balances")}
    assert set(balances) == {"KRW", "USD"}  # the US TR adds USD only
    krw = balances["KRW"]
    assert krw["cash_balance"] == Decimal("200000")  # kt00001.d2_entra survives
    assert krw["available_cash"] == Decimal("120000")  # kt00001.d2_pymn_alow_amt
    assert krw["exchange_rate"] == Decimal("1.0")

    # and the snapshot's cash is Σ(cash x rate), never Σ(추정예탁자산)
    snapshot = _query(db, "SELECT * FROM portfolio_snapshots")[0]
    assert snapshot["cash_value_krw"] == Decimal("1040300")  # 200,000 + 600 x 1400.50


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


def test_normalize_ticker_strips_kiwoom_prefix():
    assert normalize_ticker("A005930") == "005930"  # live kiwoom form
    assert normalize_ticker("A000660") == "000660"
    assert normalize_ticker(" A388720 ") == "388720"
    assert normalize_ticker("005930") == "005930"  # already canonical
    assert normalize_ticker("AAPL") == "AAPL"  # not a 6-digit KRX code -> untouched
    assert normalize_ticker("") is None
    assert normalize_ticker(None) is None


def test_normalize_us_ticker_and_market():
    assert normalize_us_ticker("GOOGL") == "GOOGL"  # live form is already plain
    assert normalize_us_ticker(" schd ") == "SCHD"
    assert normalize_us_ticker("NAS:GOOGL") == "GOOGL"  # defensive prefix strip
    assert normalize_us_ticker("GOOGL.US") == "GOOGL"  # defensive suffix strip
    assert normalize_us_ticker("") is None
    assert normalize_us_ticker(None) is None

    # live stex_nm is "미국", which is not a clean exchange -> constant "US"
    assert us_market("미국") == "US"
    assert us_market(None) == "US"
    assert us_market("NASDAQ") == "NASDAQ"  # used only if it cleanly resolves
    assert us_market("nyse") == "NYSE"


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
    # real live wire formats: 15/12-digit zero padding, sign before the padding
    assert to_decimal("000000006540000") == Decimal("6540000")
    assert to_decimal("000002180000") == Decimal("2180000")
    assert to_decimal("-00000000379148") == Decimal("-379148")
    assert to_decimal("-5.27") == Decimal("-5.27")
