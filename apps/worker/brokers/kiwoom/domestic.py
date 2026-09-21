"""Domestic (국내주식) account flow: ka00001 계좌목록 -> kt00001 예수금 / kt00018 잔고.

fetch_* call the client (raw pages, for saving); parse_* validate a schema
(pydantic ValidationError on bad shape -> the handler turns it into a
KiwoomResponseShapeError with the saved raw path).

Request enums and the ka00001 shape were pinned against the LIVE API on
2026-07-12 (see the CONFIRMED notes below). The one thing still unproven is
whether dmst_stex_tp must change for an account holding NXT-listed stock.
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

# Request enum values — CONFIRMED (live 2026-07-12): all three return return_code=0
# with complete data. For kt00018 the returned holdings sum exactly to tot_evlt_amt
# and poss_rt sums to 100.00%, i.e. nothing is being filtered out by these values.
BALANCE_QRY_TP = "1"  # kt00018 조회구분
# 국내거래소구분. "KRX" returns this account's holdings in full. Whether an account
# holding NXT-listed stock would need "NXT"/통합 is still unproven — no such holding
# exists here to test with. TO-VERIFY(NXT 보유 계좌로만 확인 가능).
BALANCE_DMST_STEX_TP = "KRX"
DEPOSIT_QRY_TP = "3"  # kt00001 조회구분

# ka00001 takes no request body. CONFIRMED (live 2026-07-12).
ACCOUNT_LIST_BODY = {}

# The appkey is bound to a single account, and kt00018/kt00001 both answer correctly
# with NO account number in the request. CONFIRMED (live 2026-07-12) — None = don't
# send one. If a multi-account key ever needs it, set this to the real field name.
ACCOUNT_NO_REQUEST_FIELD = None

# ka00001 carries no name/type, so these are display fallbacks — NOT API data.
DEFAULT_ACCOUNT_NAME = "위탁종합"
DEFAULT_ACCOUNT_TYPE = "위탁종합"

# ka00001 response is {"acctNo": "<10 digits>", "return_code": 0, "return_msg": ...}
# — a camelCase SCALAR, not an array. CONFIRMED (live 2026-07-12).
# Kiwoom is NOT consistent across TRs (ka00001 camelCase vs kt000xx snake_case), so
# key lookup below ignores case/underscores and the array form is kept as a fallback.
_ACCOUNT_LIST_KEYS = ("acnt_list", "accno_list", "acnt", "list", "output", "data")
_ACCOUNT_NO_KEYS = ("acctNo", "acnt_no", "accno", "acnt_num")
_ACCOUNT_NAME_KEYS = ("acctNm", "acnt_nm", "acnt_name")
_ACCOUNT_TYPE_KEYS = ("acctTp", "acnt_tp", "acnt_type", "prod_tp")


def _normalize_key(key):
    return str(key).replace("_", "").lower()


def _first_present(mapping, keys):
    """First candidate key present, matched ignoring case and underscores.

    Kiwoom mixes naming styles between TRs, so `acctNo` and `acnt_no` must both
    resolve. Candidate order is still honoured (first listed wins).
    """
    normalized = {}
    for key, value in mapping.items():
        normalized.setdefault(_normalize_key(key), value)
    for key in keys:
        value = normalized.get(_normalize_key(key))
        if value not in (None, ""):
            return value
    return None


def _apply_account_no(body, account):
    if not ACCOUNT_NO_REQUEST_FIELD:
        return body
    acct_no = account.get("external_account_id")
    if acct_no:
        body[ACCOUNT_NO_REQUEST_FIELD] = acct_no
    return body


# ---- ka00001 계좌목록 ----------------------------------------------------------

def fetch_account_list(client):
    return client.request_tr(API_ACCOUNT_LIST, dict(ACCOUNT_LIST_BODY))


def parse_account_list(pages):
    """Extract accounts from ka00001.

    Live shape (CONFIRMED 2026-07-12): the account number is a TOP-LEVEL scalar
    (`acctNo`) — one account per appkey, no array, no name/type. We still try an
    array form first in case a multi-account key answers differently.

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
    # Live path: single account returned as a top-level scalar.
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
                "account_name": str(name).strip() if name else DEFAULT_ACCOUNT_NAME,
                "account_type": str(acct_type).strip() if acct_type else DEFAULT_ACCOUNT_TYPE,
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
