"""Map validated Kiwoom schemas -> internal position/balance/snapshot models.

Central numeric parsing lives in to_decimal: Kiwoom returns amounts/quantities/
rates as zero-padded, sometimes signed, sometimes comma-grouped strings
("000000006540000", "-00000000379148", "-5.27", "1,484.10"). Everything numeric
goes through it. There is no hidden scale factor — verified 2026-07-12 by
reconciling cur_prc x rmnd_qty == evlt_amt exactly.

Four live findings drive the non-obvious mappings here (all CONFIRMED 2026-07-12):

1. KRX TICKER PREFIX. kt00018 returns 종목코드 as "A000660"; the canonical ticker
   is "000660". normalize_ticker strips that leading letter.

2. US QUANTITY IS poss_qty, NOT qty. ust21070 `qty` excludes unsettled buys, so it
   understates or even zeroes a real holding (live: GLW qty=1/poss_qty=4,
   SKHYV qty=0/poss_qty=2). evlt_amt / now_pric equals poss_qty on every row.

3. CASH IS D+2, NOT D+0 — in BOTH currencies. `entr`/`fc_entra` still hold cash
   committed to unsettled buys, and those bought shares are ALREADY in the holdings,
   so counting D+0 cash double-counts the purchase against the position.
     KRW: entr 6,891,525 vs d2_entra 2,495 — and Kiwoom's own 추정예탁자산 confirms
          the D+2 basis: 6,597,287 == 2,495 + 6,609,000 - 14,208 (매도수수료·세금).
     USD: fc_entra 4,905.44 vs d2_usd_fx_entr 3,976.74 — the 928.70 gap is exactly
          d1+d2_usd_buy_excta, i.e. the pending buys for shares already in poss_qty
          (1,378,284 KRW that would otherwise be counted twice).

4. KRW CONVERSION COMES FROM KIWOOM for positions (evlt_amt_krw / pl_amt_krw /
   exch_rate). We never multiply anything out ourselves — see _us_positions.
   Cash is the one place a rate is applied, using Kiwoom's own usd_exch_rate.

BALANCE-ROW SEMANTICS (contract §10 ⚠️ — get this wrong and 총자산 doubles):
- A cash row's KRW value is ALWAYS cash_balance x exchange_rate (KRW rate = 1.0; a
  foreign row with no rate contributes nothing — FX is never guessed). apps/api
  computes it exactly this way (_cash_krw_value).
- `total_evaluation_amount_local/_krw` is Kiwoom's 추정예탁자산 — an ACCOUNT-level
  total (cash + securities), NOT the row's cash. It is stored ONLY as a
  reconciliation figure (apps/api surfaces it as `estimated_total_assets_krw`) and
  must NEVER be summed as cash. Live proof: KRW row cash 2,495 vs 추정예탁자산
  6,597,287. Only the KRW row carries it (kt00018.prsm_dpst_aset_amt); foreign rows
  leave it NULL.
- The KRW row comes ONLY from kt00001 (d2_entra / d2_pymn_alow_amt). ust21110 also
  returns `krw_entra` (a D+0 figure) — writing it would overwrite the settled KRW
  row via UNIQUE(account_id, currency) and silently restore the double-count, so we
  take ONLY foreign-currency rows from the US TR.
"""
import re
from decimal import Decimal, InvalidOperation

_ZERO = Decimal("0")
DOMESTIC_EXCHANGE_RATE = Decimal("1.0")

# "A000660" -> "000660". Only strips when the remainder is exactly a 6-digit KRX
# code, so anything unexpected is passed through untouched.
_PREFIXED_TICKER = re.compile(r"^[A-Za-z](\d{6})$")

US_MARKET_DEFAULT = "US"
_US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")


def to_decimal(value):
    """Parse a Kiwoom numeric field to Decimal; None for empty/unparseable input.

    Handles None, "", "+"/"-" (sign only), commas, leading zeros, and non-numeric
    junk (-> None). bool is treated as non-numeric (guards against True/False
    slipping in as 1/0).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "")
    if text in ("", "+", "-", "."):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _dec_or_zero(value):
    return value if value is not None else _ZERO


def _sum(values):
    total = _ZERO
    for value in values:
        if value is not None:
            total += value
    return total


def normalize_ticker(stk_cd):
    """Kiwoom 국내 종목코드 "A000660" -> canonical KRX ticker "000660"."""
    if not stk_cd:
        return None
    text = str(stk_cd).strip()
    match = _PREFIXED_TICKER.match(text)
    return match.group(1) if match else text


def normalize_us_ticker(stk_cd):
    """Plain US symbol. Live codes are already plain (GOOGL); strip any exchange
    prefix/suffix defensively ("NAS:GOOGL", "GOOGL.US")."""
    if not stk_cd:
        return None
    text = str(stk_cd).strip().upper()
    if ":" in text:
        text = text.rpartition(":")[2]
    if "." in text:
        head = text.rpartition(".")[0]
        if head:
            text = head
    return text or None


def us_market(stex_nm):
    """contract §10: use stex_nm only if it cleanly yields NASDAQ/NYSE/AMEX, else "US".

    Live responses return "미국" for every row, so this is "US" in practice.
    """
    if stex_nm:
        candidate = str(stex_nm).strip().upper()
        if candidate in _US_EXCHANGES:
            return candidate
    return US_MARKET_DEFAULT


def mask_account_number(external_account_id):
    """앞4 + **** + 뒤2 (contract masking rule for logs & the masked DB column)."""
    if not external_account_id:
        return None
    text = str(external_account_id)
    if len(text) <= 2:
        return "****"
    if len(text) <= 6:
        return text[:2] + "****"
    return text[:4] + "****" + text[-2:]


# ---- positions ----------------------------------------------------------------

def _domestic_positions(balance):
    positions = []
    for holding in balance.acnt_evlt_remn_indv_tot:
        ticker = normalize_ticker(holding.stk_cd)
        if not ticker:
            continue
        market_value_local = to_decimal(holding.evlt_amt)
        unrealized_pnl_local = to_decimal(holding.evltv_prft)
        positions.append(
            {
                "country": "KR",
                "market": "KRX",
                "currency": "KRW",
                "ticker": ticker,
                "asset_name": (holding.stk_nm or None),
                "asset_type": "STOCK",
                "quantity": _dec_or_zero(to_decimal(holding.rmnd_qty)),
                "available_quantity": to_decimal(holding.trde_able_qty),
                "average_purchase_price": to_decimal(holding.pur_pric),
                "purchase_amount_local": to_decimal(holding.pur_amt),
                "current_price": to_decimal(holding.cur_prc),
                "market_value_local": market_value_local,
                "unrealized_pnl_local": unrealized_pnl_local,
                "unrealized_return": to_decimal(holding.prft_rt),
                "exchange_rate": DOMESTIC_EXCHANGE_RATE,
                "market_value_krw": market_value_local,
                "unrealized_pnl_krw": unrealized_pnl_local,
            }
        )
    return positions


def _us_positions(us_balance):
    """US holdings. KRW figures are taken STRAIGHT from Kiwoom (evlt_amt_krw /
    pl_amt_krw) — we never multiply by exch_rate ourselves."""
    if us_balance is None:
        return []
    positions = []
    for holding in us_balance.result_list:
        ticker = normalize_us_ticker(holding.stk_cd)
        if not ticker:
            continue
        positions.append(
            {
                "country": "US",
                "market": us_market(holding.stex_nm),
                "currency": "USD",
                "ticker": ticker,
                "asset_name": (holding.frgn_stk_nm or None),
                "asset_type": "STOCK",
                # poss_qty, NOT qty — qty omits unsettled buys (see module docstring)
                "quantity": _dec_or_zero(to_decimal(holding.poss_qty)),
                "available_quantity": to_decimal(holding.sell_alowq),
                "average_purchase_price": to_decimal(holding.frgn_stk_book_uv),
                "purchase_amount_local": to_decimal(holding.frgn_stk_book_amt),
                "current_price": to_decimal(holding.now_pric),
                "market_value_local": to_decimal(holding.evlt_amt),
                "unrealized_pnl_local": to_decimal(holding.pl_amt),
                "unrealized_return": to_decimal(holding.pl_rt),
                "exchange_rate": to_decimal(holding.exch_rate),
                "market_value_krw": to_decimal(holding.evlt_amt_krw),
                "unrealized_pnl_krw": to_decimal(holding.pl_amt_krw),
            }
        )
    return positions


# ---- cash balances ------------------------------------------------------------

def _settled_krw_cash(deposit):
    """D+2 예수금 (cash left after pending settlements); falls back to 예수금.

    Explicit None check, NOT `or` — a legitimate D+2 balance of 0 (or a negative
    one, which happens after an FX conversion) is falsy.
    """
    cash = to_decimal(deposit.d2_entra)
    if cash is None:
        cash = to_decimal(deposit.entr)
    return _dec_or_zero(cash)


def _settled_available_cash(deposit):
    """출금가능금액 on the SAME D+2 horizon as _settled_krw_cash.

    pymn_alow_amt is a D+1 figure and can exceed the D+2 cash, which would render
    as "available > balance". d2_pymn_alow_amt keeps the pair coherent.
    """
    available = to_decimal(deposit.d2_pymn_alow_amt)
    if available is None:
        available = to_decimal(deposit.pymn_alow_amt)
    return available


def _cash_in_krw(row):
    """KRW value of ONE cash row: cash_balance x rate (KRW defaults to 1.0).

    None when the rate is unknown — FX is never guessed. Mirrors apps/api
    _cash_krw_value exactly, so the snapshot and the API summary agree.
    """
    rate = row.get("exchange_rate")
    if rate is None and row.get("currency") == "KRW":
        rate = DOMESTIC_EXCHANGE_RATE
    cash = row.get("cash_balance")
    if cash is None or rate is None:
        return None
    return cash * rate


def _krw_cash_row(deposit, balance):
    """KRW cash — ALWAYS from kt00001 (settled D+2). Never from ust21110.krw_entra."""
    return {
        "currency": "KRW",
        "cash_balance": _settled_krw_cash(deposit),
        "available_cash": _settled_available_cash(deposit),
        # per-currency securities totals (informational)
        "total_purchase_amount_local": to_decimal(balance.tot_pur_amt),
        "total_market_value_local": to_decimal(balance.tot_evlt_amt),
        "total_unrealized_pnl_local": to_decimal(balance.tot_evlt_pl),
        # 키움 추정예탁자산 (계좌 전체 = 현금 + 주식). Reconciliation figure ONLY —
        # never summed as cash (contract §10 ⚠️).
        "total_evaluation_amount_local": to_decimal(balance.prsm_dpst_aset_amt),
        "total_evaluation_amount_krw": to_decimal(balance.prsm_dpst_aset_amt),
        "exchange_rate": DOMESTIC_EXCHANGE_RATE,
    }


def _kt00001_foreign_rows(deposit):
    """Foreign cash from kt00001 stk_entr_prst. Fallback only: it carries no FX rate
    and only the D+0 balance, so the ust21110/ust21160 row supersedes it when US data
    is present."""
    rows = []
    for item in deposit.stk_entr_prst:
        currency = (item.crnc_cd or "").strip().upper()
        if not currency or currency == "KRW":
            continue
        cash = to_decimal(item.fx_entr)
        if cash is None:
            continue
        rows.append(
            {
                "currency": currency,
                "cash_balance": cash,
                "available_cash": to_decimal(item.pymn_alow_amt_entr),
                "total_purchase_amount_local": None,
                "total_market_value_local": None,
                # 추정예탁자산 is account-level and KRW-only; foreign rows leave it NULL
                "total_evaluation_amount_local": None,
                "total_unrealized_pnl_local": None,
                "exchange_rate": None,  # kt00001 has no FX rate -> row contributes 0
                "total_evaluation_amount_krw": None,
            }
        )
    return rows


def _usd_cash_row(us_deposit, us_detail):
    """USD cash from ust21110 + ust21160.

    Uses the SETTLED (D+2) balance for the same reason KRW does: fc_entra (D+0)
    still holds the USD owed for pending buys, and those shares are already counted
    in poss_qty. exchange_rate is Kiwoom's own usd_exch_rate; the KRW value is the
    only place we apply a rate at all.
    """
    if us_deposit is None and us_detail is None:
        return None

    usd_item = None
    if us_deposit is not None:
        for item in us_deposit.result_list:
            if (item.crnc_code or "").strip().upper() == "USD":
                usd_item = item
                break

    cash = to_decimal(us_detail.d2_usd_fx_entr) if us_detail is not None else None
    if cash is None and usd_item is not None:
        cash = to_decimal(usd_item.fc_entra)
    if cash is None:
        return None

    return {
        "currency": "USD",
        "cash_balance": cash,
        "available_cash": to_decimal(usd_item.fc_pymn_alowa) if usd_item else None,
        "total_purchase_amount_local": None,
        "total_market_value_local": None,
        # 추정예탁자산 is account-level (cash + securities) and KRW-only. Do NOT put a
        # "USD cash in KRW" figure here — apps/api derives that from
        # cash_balance x exchange_rate (contract §10 ⚠️).
        "total_evaluation_amount_local": None,
        "total_unrealized_pnl_local": None,
        "exchange_rate": to_decimal(us_detail.usd_exch_rate) if us_detail is not None else None,
        "total_evaluation_amount_krw": None,
    }


def _balances(deposit, balance, us_deposit, us_detail):
    rows = [_krw_cash_row(deposit, balance)]
    foreign = {row["currency"]: row for row in _kt00001_foreign_rows(deposit)}
    usd_row = _usd_cash_row(us_deposit, us_detail)
    if usd_row is not None:
        foreign[usd_row["currency"]] = usd_row  # richer US source wins
    rows.extend(foreign.values())
    return rows


# ---- account ------------------------------------------------------------------

def normalize_account(account, balance, deposit, us_balance=None, us_deposit=None, us_detail=None):
    """Build the internal per-account model from the domestic + US responses.

    account: {external_account_id, account_name, account_type} from ka00001.
    balance/deposit: kt00018 / kt00001. us_*: ust21070 / ust21110 / ust21160.

    The snapshot is summed from the very rows we are about to store, so it agrees
    with the API's summary by construction (apps/api computes securities from
    positions.market_value_krw, cash from balances.total_evaluation_amount_krw, and
    purchase from purchase_amount_local x exchange_rate).
    """
    positions = _domestic_positions(balance) + _us_positions(us_balance)
    balances = _balances(deposit, balance, us_deposit, us_detail)

    securities_value_krw = _sum(p["market_value_krw"] for p in positions)
    # cash = Σ(cash_balance x rate) — NEVER Σ(total_evaluation_amount_krw), which is
    # 추정예탁자산 (cash + securities) and would double-count the securities (§10 ⚠️).
    cash_value_krw = _sum(_cash_in_krw(b) for b in balances)
    total_pnl_krw = _sum(p["unrealized_pnl_krw"] for p in positions)
    purchase_value_krw = _sum(
        p["purchase_amount_local"] * p["exchange_rate"]
        for p in positions
        if p["purchase_amount_local"] is not None and p["exchange_rate"] is not None
    )

    snapshot = {
        "base_currency": "KRW",
        "cash_value_krw": cash_value_krw,
        "securities_value_krw": securities_value_krw,
        "total_assets_krw": securities_value_krw + cash_value_krw,
        "total_purchase_amount_krw": purchase_value_krw,
        "total_unrealized_pnl_krw": total_pnl_krw,
    }

    return {
        "external_account_id": account["external_account_id"],
        "account_number_masked": mask_account_number(account["external_account_id"]),
        "account_name": account.get("account_name"),
        "account_type": account.get("account_type"),
        "base_currency": "KRW",
        "balances": balances,
        "positions": positions,
        "snapshot": snapshot,
    }
