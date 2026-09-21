"""증권사 어댑터 추상 — 증권사를 늘릴 때 손대는 유일한 계약.

★설계 의도: 지금은 키움 하나지만, "사람 계좌만 바꾸면 그 사람도 쓸 수 있게" 하려면
  자격증명뿐 아니라 **증권사 자체도 갈아끼울 수 있어야** 한다. 동기화 핸들러가
  키움 모듈을 직접 import 하면 증권사를 늘릴 때마다 핸들러를 고치게 된다.

계약은 네 가지만 요구한다 — 계좌 목록, 예수금, 보유 종목, 그리고 연결 확인.
나머지(페이징·재시도·토큰)는 각 어댑터의 사정이다.

정규화된 반환 타입(PortfolioSnapshot)을 두는 이유: 증권사마다 필드명이 다른데
그 차이가 repositories 까지 새어 나가면, 증권사를 늘릴 때 적재 코드까지 갈라진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class AccountRef:
    """한 계좌를 가리키는 최소 정보."""

    external_account_id: str
    account_name: str | None = None
    account_type: str | None = None
    account_number_masked: str | None = None
    base_currency: str = "KRW"


@dataclass(frozen=True)
class PositionRow:
    """보유 종목 한 줄 — 증권사 필드명을 이미 벗겨낸 형태."""

    country: str
    market: str
    ticker: str
    name: str | None
    currency: str
    quantity: Decimal
    average_purchase_price: Decimal | None = None
    purchase_amount_local: Decimal | None = None
    current_price: Decimal | None = None
    market_value_local: Decimal | None = None
    unrealized_pnl_local: Decimal | None = None
    unrealized_return: Decimal | None = None
    # 환율은 **증권사가 준 값**을 그대로 싣는다. 여기서 계산하지 않는다 —
    # 종목별 수치와 합계가 서로 다른 환율을 타면 화면에서 합이 안 맞는다.
    exchange_rate: Decimal | None = None
    # ★KRW 환산값도 **증권사가 준 값**을 그대로 싣는다(키움 evlt_amt_krw/pl_amt_krw).
    #   local 값에 환율을 곱해 우리가 만들지 않는다 — 증권사 내부 환산과 소수점이
    #   달라져 합계가 어긋난다.
    #   ⚠️이 필드가 없으면 외화 종목의 평가금액이 USD 숫자 그대로 KRW 자리에 실려
    #     총자산이 1/1370 로 줄어든다(2026-09-21 해외 연동에서 실제로 겪었다).
    market_value_krw: Decimal | None = None
    unrealized_pnl_krw: Decimal | None = None
    asset_type: str | None = None


@dataclass(frozen=True)
class BalanceRow:
    """계좌×통화 예수금."""

    currency: str
    cash_balance: Decimal
    available_cash: Decimal | None = None
    total_purchase_amount_local: Decimal | None = None
    total_evaluation_amount_local: Decimal | None = None
    total_unrealized_pnl_local: Decimal | None = None
    exchange_rate: Decimal | None = None


@dataclass
class AccountPortfolio:
    """한 계좌의 동기화 결과."""

    account: AccountRef
    balances: list[BalanceRow] = field(default_factory=list)
    positions: list[PositionRow] = field(default_factory=list)
    as_of: datetime | None = None
    # 원본 응답을 그대로 보관하기 위한 (endpoint_name, payload) 목록.
    raw_pages: list[tuple[str, dict]] = field(default_factory=list)


@dataclass(frozen=True)
class TradeRow:
    """체결 한 건 — 증권사 필드명을 벗겨낸 형태.

    ⚠️금액은 **거래 통화 기준**이다. 해외 거래는 증권사가 원화 금액을 0 으로 주므로
      KRW 환산은 여기서 만들지 않는다(amount_krw 는 증권사가 실제로 줄 때만 채운다).
    """

    trade_date: date
    trade_no: str
    side: str  # BUY / SELL
    ticker: str
    name: str | None
    currency: str
    quantity: Decimal
    price: Decimal | None = None
    amount_local: Decimal | None = None
    settlement_amount_local: Decimal | None = None
    commission_local: Decimal | None = None
    tax_local: Decimal | None = None
    amount_krw: Decimal | None = None
    exchange: str | None = None
    channel: str | None = None
    processed_at: str | None = None


class BrokerAdapter:
    """증권사 하나에 대한 읽기 어댑터.

    구현체는 자격증명을 받아 생성되고, 컨텍스트 매니저로 자원을 정리한다.
    주문·매매는 이 계약에 **없다** — 이 시스템은 조회만 한다.
    """

    broker_code: str = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """네트워크 자원 정리. 기본은 아무것도 안 한다."""

    def check_connection(self) -> dict:
        """연결 확인 — 토큰 발급까지만 해 보고 메타데이터를 돌려준다.

        연동 화면의 "연결 확인" 버튼이 이걸 쓴다. 잔고를 끌어오지 않으므로
        가볍고, 실패 원인(키 문제인지 IP 문제인지)을 바로 드러낸다.
        """
        raise NotImplementedError

    def fetch_accounts(self) -> list[AccountRef]:
        raise NotImplementedError

    def fetch_portfolio(self, account: AccountRef) -> AccountPortfolio:
        raise NotImplementedError

    def fetch_trades(self, account: AccountRef, start: date, end: date) -> list[TradeRow]:
        """기간 내 체결 내역. 증권사마다 조회 기간 상한이 다르므로 구현체가 쪼갠다."""
        raise NotImplementedError
