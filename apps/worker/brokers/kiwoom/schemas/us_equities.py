"""Response schemas for the US (해외주식) account TRs.

CONFIRMED live 2026-07-12 (contract-kiwoom §10). POST /api/us/acnt with api-id
ust21070 (잔고), ust21110 (예수금), ust21160 (예수금 상세). No account number in
the request — the appkey is account-bound, same as domestic.

Kiwoom supplies the KRW conversion itself (evlt_amt_krw / pl_amt_krw / exch_rate),
so the adapter NEVER computes FX for positions.

Numerics arrive as decimal strings ("21843.4490") or zero-padded integers
("000000032765174"), and usd_exch_rate is comma-formatted ("1,484.10") — all of
which adapter.to_decimal handles. extra="allow" keeps unmapped fields.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UsHolding(BaseModel):
    """One row of ust21070 result_list (해외 보유종목)."""

    model_config = ConfigDict(extra="allow")

    stk_cd: Optional[str] = None  # plain symbol (GOOGL, SCHD, ...)
    frgn_stk_nm: Optional[str] = None  # 종목명
    # 보유수량은 poss_qty. `qty`는 미결제 매수분을 빼고 세므로 실제 보유량이 아니다
    # (live: GLW qty=1 / poss_qty=4, SKHYV qty=0 / poss_qty=2). adapter 주석 참고.
    qty: Optional[str] = None
    poss_qty: Optional[str] = None  # 보유수량 <- 실제 수량
    sell_alowq: Optional[str] = None  # 매도가능수량
    frgn_stk_book_uv: Optional[str] = None  # 매입단가 (USD)
    frgn_stk_book_amt: Optional[str] = None  # 매입금액 (USD)
    now_pric: Optional[str] = None  # 현재가 (USD)
    evlt_amt: Optional[str] = None  # 평가금액 (USD)
    pl_amt: Optional[str] = None  # 평가손익 (USD)
    pl_rt: Optional[str] = None  # 수익률
    evlt_amt_krw: Optional[str] = None  # 평가금액 (KRW) — 키움이 환산해 준 값
    pl_amt_krw: Optional[str] = None  # 평가손익 (KRW) — 키움이 환산해 준 값
    exch_rate: Optional[str] = None  # 적용환율
    crnc_code: Optional[str] = None  # USD
    natn_nm: Optional[str] = None  # 미국
    stex_nm: Optional[str] = None  # 거래소명 — live 값은 "미국" (NASDAQ/NYSE 아님)


class UsBalanceResponse(BaseModel):
    """ust21070 해외 계좌잔고내역 (보유종목 + 요약)."""

    model_config = ConfigDict(extra="allow")

    crnc_code: Optional[str] = None
    tot_evlt_amt: Optional[str] = None  # 총평가금액 (USD)
    tot_evlt_amt_krw: Optional[str] = None  # 총평가금액 (KRW)
    tot_prch_amt: Optional[str] = None  # 총매입금액 (USD)
    tot_prch_amt_krw: Optional[str] = None  # 총매입금액 (KRW)
    tot_pl_amt: Optional[str] = None  # 총손익 (USD)
    tot_pl_amt_krw: Optional[str] = None  # 총손익 (KRW)
    tot_pl_rt: Optional[str] = None  # 총수익률
    result_list: List[UsHolding] = Field(default_factory=list)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None


class UsDepositCurrency(BaseModel):
    """One row of ust21110 result_list (통화별 외화예수금)."""

    model_config = ConfigDict(extra="allow")

    crnc_code: Optional[str] = None  # USD
    crnc_nm: Optional[str] = None  # 미국달러
    fc_entra: Optional[str] = None  # 외화예수금 (D+0 — 미결제 매수분 포함)
    fc_pymn_alowa: Optional[str] = None  # 외화출금가능금액
    fc_ord_alowa: Optional[str] = None  # 외화주문가능금액
    fc_booka: Optional[str] = None  # 외화장부금액 (KRW 장부가, 시가 아님)


class UsDepositResponse(BaseModel):
    """ust21110 해외 예수금."""

    model_config = ConfigDict(extra="allow")

    krw_entra: Optional[str] = None  # 원화예수금
    result_list: List[UsDepositCurrency] = Field(default_factory=list)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None


class UsDepositDetailResponse(BaseModel):
    """ust21160 해외 예수금 상세 — the ONLY source of usd_exch_rate + the D+2 ladder.

    NOTE: contract §10 attributes usd_exch_rate to ust21110; live it is here in
    ust21160. ust21110 carries no FX rate at all.
    """

    model_config = ConfigDict(extra="allow")

    won_entr: Optional[str] = None  # 원화예수금
    usd_exch_rate: Optional[str] = None  # USD 환율, comma-formatted ("1,484.10")
    d0_usd_fx_entr: Optional[str] = None  # D+0 외화예수금
    d2_usd_fx_entr: Optional[str] = None  # D+2 외화예수금 (정산 후 실제 잔여 USD)
    return_code: Optional[int] = None
    return_msg: Optional[str] = None
