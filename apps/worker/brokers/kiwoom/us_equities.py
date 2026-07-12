"""US (해외주식) flow — CONFIRMED live 2026-07-12 (contract-kiwoom §10).

Supersedes the earlier NOT_SUPPORTED gate: /api/us/acnt answers with real data.
The endpoint takes NO request body and NO account number (the appkey is
account-bound, exactly like the domestic TRs).

Naming note: the contract pins the JOB STEP names `fetch_us_balance` (예수금) and
`fetch_us_positions` (잔고). Functions here are named after what they FETCH, so the
handler maps:
    step fetch_us_balance   -> fetch_deposit (ust21110) + fetch_deposit_detail (ust21160)
    step fetch_us_positions -> fetch_positions (ust21070)
"""
from .exceptions import KiwoomResponseShapeError
from .schemas.us_equities import (
    UsBalanceResponse,
    UsDepositDetailResponse,
    UsDepositResponse,
)

US_SUPPORTED = True

US_ACNT_PATH = "/api/us/acnt"
API_US_POSITIONS = "ust21070"  # 해외 잔고 (보유종목 + 요약)
API_US_DEPOSIT = "ust21110"  # 해외 예수금 (통화별)
API_US_DEPOSIT_DETAIL = "ust21160"  # 해외 예수금 상세 (usd_exch_rate + D+2 ladder)

# CONFIRMED: all three take an empty body.
US_REQUEST_BODY = {}


def _fetch(client, api_id):
    return client.request_tr(api_id, dict(US_REQUEST_BODY), path=US_ACNT_PATH)


# ---- ust21070 잔고 -------------------------------------------------------------

def fetch_positions(client, account):
    return _fetch(client, API_US_POSITIONS)


def parse_positions(pages):
    """Validate every page and merge result_list across pages."""
    if not pages:
        raise KiwoomResponseShapeError("empty ust21070 response")
    parsed_pages = [UsBalanceResponse(**page) for page in pages]
    merged = parsed_pages[0]
    holdings = []
    for parsed in parsed_pages:
        holdings.extend(parsed.result_list)
    merged.result_list = holdings
    return merged


# ---- ust21110 예수금 -----------------------------------------------------------

def fetch_deposit(client, account):
    return _fetch(client, API_US_DEPOSIT)


def parse_deposit(pages):
    if not pages:
        raise KiwoomResponseShapeError("empty ust21110 response")
    return UsDepositResponse(**pages[0])


# ---- ust21160 예수금 상세 ------------------------------------------------------

def fetch_deposit_detail(client, account):
    return _fetch(client, API_US_DEPOSIT_DETAIL)


def parse_deposit_detail(pages):
    if not pages:
        raise KiwoomResponseShapeError("empty ust21160 response")
    return UsDepositDetailResponse(**pages[0])
