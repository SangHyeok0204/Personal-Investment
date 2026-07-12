"""Domestic (국내주식) account flow: ka00001 계좌목록 -> kt00001 예수금 / kt00018 잔고.

fetch_* call the client (raw pages, for saving); parse_* validate a schema
(pydantic ValidationError on bad shape -> the handler turns it into a
KiwoomResponseShapeError with the saved raw path).

Several request fields/enums are marked TO-VERIFY: the reference (§4) confirmed
the response field NAMES from wrapper source code but could NOT confirm request
enum VALUES or the ka00001 request/response shape from official docs. These are
constants so a single real 모의투자 call can pin them.
"""
from .exceptions import KiwoomResponseShapeError
from .schemas.domestic import (
    DomesticBalanceResponse,
    DomesticDepositResponse,
)

# api-id codes (reference §4.1, source [Y]).
API_ACCOUNT_LIST = "ka00001"  # 계좌목록/계좌번호 조회
API_DEPOSIT = "kt00001"  # 예수금상세현황요청
API_BALANCE = "kt00018"  # 계좌평가잔고내역요청

# Request enum values — TO-VERIFY(모의투자 실호출로 확정), reference §4.2/§4.3 [TV].
BALANCE_QRY_TP = "1"  # kt00018 조회구분
BALANCE_DMST_STEX_TP = "KRX"  # kt00018 국내거래소구분 (KRX/NXT/통합)
DEPOSIT_QRY_TP = "3"  # kt00001 조회구분 (3=추정조회 추정)

# ka00001 request body — TO-VERIFY: request fields unconfirmed (reference §4.1 [TV]).
ACCOUNT_LIST_BODY = {}

# The reference lists NO account-number field on kt00018/kt00001 (§4.2/§4.3), yet
# the design queries per account. We pass the account number under this key so a
# multi-account token is handled correctly; if the real API names it differently
# or rejects it, change this ONE constant. TO-VERIFY(실호출로 확정).
ACCOUNT_NO_REQUEST_FIELD = "acnt_no"

# Candidate keys for the ka00001 response (all TO-VERIFY, reference §4.1 [TV]).
_ACCOUNT_LIST_KEYS = ("acnt_list", "accno_list", "acnt", "list", "output", "data")
_ACCOUNT_NO_KEYS = ("acnt_no", "accno", "acnt_num", "acntno")
_ACCOUNT_NAME_KEYS = ("acnt_nm", "acnt_name", "accno_nm")
_ACCOUNT_TYPE_KEYS = ("acnt_tp", "acnt_type", "prod_tp")


def _first_present(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _apply_account_no(body, account):
    acct_no = account.get("external_account_id")
    if acct_no:
        body[ACCOUNT_NO_REQUEST_FIELD] = acct_no
    return body


# ---- ka00001 계좌목록 ----------------------------------------------------------

def fetch_account_list(client):
    return client.request_tr(API_ACCOUNT_LIST, dict(ACCOUNT_LIST_BODY))


def parse_account_list(pages):
    """Extract accounts defensively (ka00001 fields are TO-VERIFY).

    Returns a de-duplicated list of {external_account_id, account_name,
    account_type}. Empty list means nothing recognizable was found.
    """
    items = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        array = _first_present(page, _ACCOUNT_LIST_KEYS)
        if isinstance(array, list):
            items.extend(array)
    # Fallback: a token bound to a single account may return it at the top level.
    if not items:
        for page in pages:
            if isinstance(page, dict) and _first_present(page, _ACCOUNT_NO_KEYS):
                items.append(page)

    accounts = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        acct_no = _first_present(item, _ACCOUNT_NO_KEYS)
        if not acct_no:
            continue
        external_id = str(acct_no).strip()
        if external_id in seen:
            continue
        seen.add(external_id)
        name = _first_present(item, _ACCOUNT_NAME_KEYS)
        acct_type = _first_present(item, _ACCOUNT_TYPE_KEYS)
        accounts.append(
            {
                "external_account_id": external_id,
                "account_name": str(name).strip() if name else None,
                "account_type": str(acct_type).strip() if acct_type else None,
            }
        )
    return accounts


# ---- kt00001 예수금 -----------------------------------------------------------

def fetch_deposit(client, account):
    body = _apply_account_no({"qry_tp": DEPOSIT_QRY_TP}, account)
    return client.request_tr(API_DEPOSIT, body)


def parse_deposit(pages):
    if not pages:
        raise KiwoomResponseShapeError("empty kt00001 response")
    return DomesticDepositResponse(**pages[0])


# ---- kt00018 잔고 -------------------------------------------------------------

def fetch_balance(client, account):
    body = _apply_account_no(
        {"qry_tp": BALANCE_QRY_TP, "dmst_stex_tp": BALANCE_DMST_STEX_TP}, account
    )
    return client.request_tr(API_BALANCE, body)


def parse_balance(pages):
    """Validate every page and merge the holdings arrays across pages."""
    if not pages:
        raise KiwoomResponseShapeError("empty kt00018 response")
    parsed_pages = [DomesticBalanceResponse(**page) for page in pages]
    merged = parsed_pages[0]
    holdings = []
    for parsed in parsed_pages:
        holdings.extend(parsed.acnt_evlt_remn_indv_tot)
    merged.acnt_evlt_remn_indv_tot = holdings
    return merged
