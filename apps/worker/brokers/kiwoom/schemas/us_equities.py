"""US-equities response schemas — STUB (NOT_SUPPORTED this round).

Kiwoom US REST support is unconfirmed in official docs (kiwoom-api-reference.md
§5: everything here is [TV] / TO-VERIFY). We do NOT parse US responses this
round. The field map below is transcribed from the reference so that flipping
us_equities.US_SUPPORTED to True later is a fill-in-the-blanks task, not a
research task. DO NOT rely on these names until verified against a real call.

Endpoint (assumed): POST /api/us/acnt  (mirror of domestic /api/dostk/acnt)

ust21070 잔고 (balance):
    tot_evlt_amt   총평가금액
    tot_prch_amt   총매입금액
    tot_pl_amt     총손익
    poss_qty/qty   보유수량
    sell_alowq     매도가능수량
    now_pric       현재가
    evlt_amt       평가금액
    exch_rate      환율            <- KRW 환산에 필요

ust21110 예수금:
    krw_entra      원화예수금
    fc_entra       외화예수금
    fc_pymn_alowa  외화출금가능
    fc_booka       외화장부

ust21120 통화별 예수금·평가:
    won_entr       원화예수금
    fx_entr        외화예수금
    evlt_amt       평가
    crnc_rt        통화환율        <- KRW 환산에 필요
    chg_entr       (변동)

ust21160 예수금상세:
    won_entr       원화예수금
    usd_exch_rate  USD 환율        <- KRW 환산에 필요
    d0_usd_fx_entr D0 USD 외화예수금
    d1_usd_fx_entr D1 USD 외화예수금
"""

# When real schemas are added, define them here (pydantic BaseModel,
# extra="allow", Optional fields) exactly like schemas/domestic.py.
