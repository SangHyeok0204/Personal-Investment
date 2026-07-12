"""Map validated Kiwoom schemas -> internal position/balance/snapshot models.

Central numeric parsing lives in to_decimal: Kiwoom returns amounts/quantities/
rates as strings that may be zero-padded, comma-grouped, or signed (reference
§6.6 [TV]). Everything numeric goes through it. Domestic rows are KRW with
exchange_rate 1.0, so *_krw == *_local.
"""
from decimal import Decimal, InvalidOperation

_ZERO = Decimal("0")
DOMESTIC_EXCHANGE_RATE = Decimal("1.0")


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


def mask_account_number(external_account_id):
    """앞4 + **** + 뒤2 (reference/contract masking rule for logs & DB column)."""
    if not external_account_id:
        return None
    text = str(external_account_id)
    if len(text) <= 2:
        return "****"
    if len(text) <= 6:
        return text[:2] + "****"
    return text[:4] + "****" + text[-2:]


def normalize_domestic_account(account, balance, deposit):
    """Build the internal per-account model from kt00018 잔고 + kt00001 예수금.

    account: {external_account_id, account_name, account_type} from ka00001.
    balance: DomesticBalanceResponse (kt00018). deposit: DomesticDepositResponse.
    """
    rate = DOMESTIC_EXCHANGE_RATE

    positions = []
    for holding in balance.acnt_evlt_remn_indv_tot:
        ticker = (holding.stk_cd or "").strip()
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
                # kt00018 does not report an available (거래가능) quantity.
                "available_quantity": None,
                "average_purchase_price": to_decimal(holding.pur_pric),
                "purchase_amount_local": to_decimal(holding.pur_amt),
                "current_price": to_decimal(holding.cur_prc),
                "market_value_local": market_value_local,
                "unrealized_pnl_local": unrealized_pnl_local,
                "unrealized_return": to_decimal(holding.prft_rt),
                "exchange_rate": rate,
                "market_value_krw": market_value_local,
                "unrealized_pnl_krw": unrealized_pnl_local,
            }
        )

    cash_balance = _dec_or_zero(to_decimal(deposit.entr))
    total_purchase_local = to_decimal(balance.tot_pur_amt)
    total_market_local = to_decimal(balance.tot_evlt_amt)
    total_pnl_local = to_decimal(balance.tot_evlt_pl)
    total_eval_local = to_decimal(balance.prsm_dpst_aset_amt)
    if total_eval_local is None:
        total_eval_local = _dec_or_zero(total_market_local) + cash_balance

    balances = [
        {
            "currency": "KRW",
            "cash_balance": cash_balance,
            "available_cash": to_decimal(deposit.pymn_alow_amt),
            "total_purchase_amount_local": total_purchase_local,
            "total_market_value_local": total_market_local,
            "total_evaluation_amount_local": total_eval_local,
            "total_unrealized_pnl_local": total_pnl_local,
            "exchange_rate": rate,
            "total_evaluation_amount_krw": total_eval_local,
        }
    ]

    securities_value_krw = _dec_or_zero(total_market_local)
    snapshot = {
        "base_currency": "KRW",
        "cash_value_krw": cash_balance,
        "securities_value_krw": securities_value_krw,
        "total_assets_krw": securities_value_krw + cash_balance,
        "total_purchase_amount_krw": total_purchase_local,
        "total_unrealized_pnl_krw": total_pnl_local,
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
