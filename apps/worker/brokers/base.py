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
class DividendFetch:
    """배당 조회 한 번의 결과.

    ⚠️세 가지를 **따로** 들고 나온다.
      · rows           받은 배당
      · skipped        거래소를 못 찾거나 증권사가 모른다고 해서 **못 물어본** 종목.
                       '배당 0원'과 구분하려고 따로 센다.
      · exchange_codes 이번에 알아낸 (티커 → 거래소 코드). 배당이 0건이어도
                       코드는 알아낼 수 있고, 그걸 남겨야 다음에 다시 안 더듬는다.
    """

    rows: list["DividendRow"]
    skipped: list[str]
    exchange_codes: dict[str, str]


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
    #: KR / US. ⚠️자연키의 일부다 — 거래번호가 일자별로 리셋되는데 국내·해외가
    #:  따로 매겨서, 시장을 빼면 같은 날 1번끼리 덮어쓴다(alembic 0018).
    market: str
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


@dataclass(frozen=True)
class OrderRow:
    """주문 한 건 — 체결 이력이 감추는 것들.

    체결(TradeRow)은 "성사된 것"만 알려준다. 주문은 **하려고 한 것 전부**를
    알려주므로 미체결·취소·슬리피지·주문 채널이 여기에만 있다.

    ⚠️`filled_price` 는 미체결이면 None 이다. 증권사는 0 으로 주는데 그대로 두면
      "0달러에 체결"로 읽힌다.
    """

    order_date: date
    order_no: str
    side: str  # BUY / SELL
    ticker: str
    name: str | None
    currency: str
    order_time: str | None = None
    order_type: str | None = None
    order_quantity: Decimal | None = None
    filled_quantity: Decimal | None = None
    cancelled_quantity: Decimal | None = None
    modified_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    order_price: Decimal | None = None
    filled_price: Decimal | None = None
    stop_price: Decimal | None = None
    filled_amount: Decimal | None = None
    exchange: str | None = None
    channel: str | None = None
    reserve_type: str | None = None


@dataclass(frozen=True)
class DailyPerformanceRow:
    """계좌 일별 성과 한 점. 전부 KRW — 증권사가 이미 환산해 준 값이다."""

    base_date: date
    deposit_assets_krw: Decimal | None = None
    stock_value_krw: Decimal | None = None
    pnl_krw: Decimal | None = None
    cumulative_pnl_krw: Decimal | None = None
    dividend_krw: Decimal | None = None
    commission_tax_krw: Decimal | None = None
    buy_amount_krw: Decimal | None = None
    sell_amount_krw: Decimal | None = None
    deposit_krw: Decimal | None = None
    withdrawal_krw: Decimal | None = None
    return_rate: Decimal | None = None
    exchange_rate: Decimal | None = None


@dataclass(frozen=True)
class RealizedPnlRow:
    """실현손익 한 건 (매도일 × 종목 집계).

    ⚠️환차손익(fx_pnl_krw)은 주가 손익과 별개다 — 합치지 않는다.
    """

    sell_date: date
    ticker: str
    name: str | None
    currency: str
    quantity: Decimal
    avg_buy_price: Decimal | None = None
    avg_sell_price: Decimal | None = None
    buy_amount_local: Decimal | None = None
    sell_amount_local: Decimal | None = None
    commission_tax_local: Decimal | None = None
    pnl_local: Decimal | None = None
    buy_amount_krw: Decimal | None = None
    sell_amount_krw: Decimal | None = None
    commission_tax_krw: Decimal | None = None
    pnl_krw: Decimal | None = None
    pnl_rate: Decimal | None = None
    buy_exchange_rate: Decimal | None = None
    sell_exchange_rate: Decimal | None = None
    fx_pnl_krw: Decimal | None = None
    exchange: str | None = None


@dataclass(frozen=True)
class DividendRow:
    """배당 수령 한 건. 금액은 증권사가 준 **원화** 값이다."""

    pay_date: date
    ticker: str
    name: str | None
    amount_krw: Decimal
    currency: str = "KRW"
    #: 이 종목이 어느 거래소로 조회됐는지(ND/NY/NA). 다음 조회에서 재탐색을 줄인다.
    broker_exchange_code: str | None = None


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

    def fetch_daily_performance(
        self, account: AccountRef, start: date, end: date
    ) -> list[DailyPerformanceRow]:
        """계좌 일별 성과 시계열. 증권사가 들고 있는 과거를 그대로 받아 온다."""
        raise NotImplementedError

    def fetch_realized_pnl(
        self, account: AccountRef, start: date, end: date
    ) -> list[RealizedPnlRow]:
        """실현손익(매도 확정분)."""
        raise NotImplementedError

    def fetch_dividends(
        self,
        account: AccountRef,
        tickers: list[tuple[str, str | None]],
        start: date,
        end: date,
    ) -> "DividendFetch":
        """배당 수령 이력 · 못 물어본 종목 · 새로 알아낸 거래소 코드.

        tickers: (종목코드, 증권사 거래소코드 or None). 코드를 모르면 구현체가 찾는다.

        ⚠️건너뛴 것을 따로 내놓지 않으면 화면에서 **'배당 0원'과 '안 물어봤다'가
          똑같이 보인다.**
        """
        raise NotImplementedError
