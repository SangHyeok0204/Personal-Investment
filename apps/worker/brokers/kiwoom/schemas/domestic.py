"""Response schemas for the domestic (국내주식) account TRs.

Field names come from kiwoom-api-reference.md §4 (source [D]: dongbin300/
KiwoomRestApi.Net raw JSON field names). Numeric fields arrive as strings with
leading zeros/signs, so every value is typed Optional[str] and converted with
adapter.to_decimal downstream. extra="allow" keeps unmapped fields.

The ONE thing pydantic still enforces (and that we WANT it to enforce) is the
SHAPE of the holdings array: acnt_evlt_remn_indv_tot must be a list. A scalar
there raises ValidationError -> KiwoomResponseShapeError -> job FAILED.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DomesticHolding(BaseModel):
    """One row of kt00018 acnt_evlt_remn_indv_tot (보유종목)."""

    model_config = ConfigDict(extra="allow")

    stk_cd: Optional[str] = None  # 종목코드
    stk_nm: Optional[str] = None  # 종목명
    rmnd_qty: Optional[str] = None  # 보유수량
    pur_pric: Optional[str] = None  # 매입평균가
    cur_prc: Optional[str] = None  # 현재가
    evlt_amt: Optional[str] = None  # 평가금액
    pur_amt: Optional[str] = None  # 매입금액
    evltv_prft: Optional[str] = None  # 평가손익
    prft_rt: Optional[str] = None  # 수익률


class DomesticBalanceResponse(BaseModel):
    """kt00018 계좌평가잔고내역요청 (보유종목 잔고 + 요약)."""

    model_config = ConfigDict(extra="allow")

    tot_pur_amt: Optional[str] = None  # 총매입금액
    tot_evlt_amt: Optional[str] = None  # 총평가금액
    tot_evlt_pl: Optional[str] = None  # 총평가손익금액
    tot_prft_rt: Optional[str] = None  # 총수익률
    prsm_dpst_aset_amt: Optional[str] = None  # 추정예탁자산
    acnt_evlt_remn_indv_tot: List[DomesticHolding] = Field(default_factory=list)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None


class DomesticDepositResponse(BaseModel):
    """kt00001 예수금상세현황요청 (예수금)."""

    model_config = ConfigDict(extra="allow")

    entr: Optional[str] = None  # 예수금
    pymn_alow_amt: Optional[str] = None  # 출금가능금액
    ord_alow_amt: Optional[str] = None  # 주문가능금액
    profa_ch: Optional[str] = None  # 주식증거금현금
    return_code: Optional[int] = None
    return_msg: Optional[str] = None
