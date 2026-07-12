"""Response schemas for the domestic (국내주식) account TRs.

Field names are CONFIRMED against live responses (2026-07-12). The [D]-wrapper
guesses in kiwoom-api-reference §4 all held up, and live calls surfaced three
fields the reference never listed: trde_able_qty, d2_entra, stk_entr_prst.

Numerics arrive as zero-padded, sometimes signed strings ("000000006540000",
"-00000000379148", "-5.27"), so every value is typed Optional[str] and converted
via adapter.to_decimal. extra="allow" keeps the many fields we don't map.

The one shape pydantic still enforces (and that we WANT enforced) is that the
holdings key is a LIST. A scalar there raises ValidationError ->
KiwoomResponseShapeError -> job FAILED, rather than silently syncing 0 positions.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DomesticHolding(BaseModel):
    """One row of kt00018 acnt_evlt_remn_indv_tot (보유종목)."""

    model_config = ConfigDict(extra="allow")

    # 종목코드 — live form carries an "A" prefix ("A000660"); see adapter.normalize_ticker.
    stk_cd: Optional[str] = None
    stk_nm: Optional[str] = None  # 종목명
    rmnd_qty: Optional[str] = None  # 보유수량
    trde_able_qty: Optional[str] = None  # 거래가능수량 (CONFIRMED live; not in reference)
    pur_pric: Optional[str] = None  # 매입평균가
    cur_prc: Optional[str] = None  # 현재가
    evlt_amt: Optional[str] = None  # 평가금액
    pur_amt: Optional[str] = None  # 매입금액
    evltv_prft: Optional[str] = None  # 평가손익 (수수료·세금 반영됨)
    prft_rt: Optional[str] = None  # 수익률


class DomesticBalanceResponse(BaseModel):
    """kt00018 계좌평가잔고내역요청 (보유종목 잔고 + 요약)."""

    model_config = ConfigDict(extra="allow")

    tot_pur_amt: Optional[str] = None  # 총매입금액
    tot_evlt_amt: Optional[str] = None  # 총평가금액
    tot_evlt_pl: Optional[str] = None  # 총평가손익금액
    tot_prft_rt: Optional[str] = None  # 총수익률
    prsm_dpst_aset_amt: Optional[str] = None  # 추정예탁자산 (키움 자체 산출 총자산)
    acnt_evlt_remn_indv_tot: List[DomesticHolding] = Field(default_factory=list)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None


class DepositCurrencyItem(BaseModel):
    """One row of kt00001 stk_entr_prst (통화별 예수금). CONFIRMED live 2026-07-12."""

    model_config = ConfigDict(extra="allow")

    crnc_cd: Optional[str] = None  # 통화코드 (예: USD)
    fx_entr: Optional[str] = None  # 외화예수금
    pymn_alow_amt_entr: Optional[str] = None  # 출금가능금액 (해당 통화)


class DomesticDepositResponse(BaseModel):
    """kt00001 예수금상세현황요청 (예수금)."""

    model_config = ConfigDict(extra="allow")

    # 예수금 (D+0). Includes cash already committed to unsettled buys, so it is NOT
    # the free cash — see adapter for why d2_entra is used for asset totals.
    entr: Optional[str] = None
    d2_entra: Optional[str] = None  # D+2 예수금 (정산 후 실제 잔여 현금) — CONFIRMED live
    pymn_alow_amt: Optional[str] = None  # 출금가능금액 (D+1 기준)
    d2_pymn_alow_amt: Optional[str] = None  # D+2 출금가능금액 — same horizon as d2_entra
    ord_alow_amt: Optional[str] = None  # 주문가능금액
    profa_ch: Optional[str] = None  # 주식증거금현금
    # 통화별 예수금 배열. The reference could not confirm this key; the live name is
    # stk_entr_prst (CONFIRMED 2026-07-12). Carries the USD cash balance.
    stk_entr_prst: List[DepositCurrencyItem] = Field(default_factory=list)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None
