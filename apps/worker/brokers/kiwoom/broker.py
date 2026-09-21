"""KiwoomAdapter — BrokerAdapter 계약의 키움 구현.

기존 절차형 모듈(client/domestic/adapter)은 그대로 두고 **감싸기만** 한다. 잘
동작하고 테스트가 두꺼운 코드를 재작성할 이유가 없다. 여기서 하는 일은:
  - 자격증명 객체를 받아 클라이언트를 만든다(전역 환경변수를 읽지 않는다)
  - 원본 응답 페이지를 (endpoint_name, payload) 로 들고 나온다(원문 보관용)
  - 연결 확인(check_connection)을 잔고 조회와 분리한다

★"키만 바꾸면 다른 사람"이 성립하는 이유: 이 클래스는 BrokerCredentials 하나만
  받는다. 어디서도 os.environ 을 보지 않으므로, 자격증명을 바꿔 새 인스턴스를
  만들면 그 사람의 계좌가 조회된다. 토큰도 자격증명 지문으로 갈린 캐시를 탄다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ..base import AccountPortfolio, AccountRef, BalanceRow, BrokerAdapter, PositionRow
from ..registry import register
from . import auth as auth_module
from . import domestic
from . import us_equities
from .adapter import mask_account_number, normalize_account, to_decimal
from .client import KiwoomClient
from .exceptions import KiwoomAuthError


@register("KIWOOM")
class KiwoomAdapter(BrokerAdapter):
    #: 기본으로 조회할 시장. 연결마다 바꿀 수 있다.
    DEFAULT_MARKETS = ("KR", "US")

    def __init__(
        self,
        credentials,
        http_client=None,
        token_store=None,
        sleep=None,
        markets=None,
    ):
        """markets: 조회할 시장 집합. ("US",) 면 해외만, ("KR",) 면 국내만.

        ★2026-09-21 사용자 요청: 이 계좌는 국내 비중이 작고 해외가 본체라
          국내를 빼고 해외만 보고 싶다. 시장을 끄고 켜는 것은 **조회 비용**과도
          직결된다 — 안 보는 시장의 TR 을 매번 부르면 유량제한만 축낸다.
        """
        self._credentials = credentials
        self._markets = tuple(
            m.upper() for m in (markets if markets is not None else self.DEFAULT_MARKETS)
        )
        if not self._markets:
            raise ValueError("markets 가 비어 있습니다 — 조회할 시장이 없습니다")
        self._token_store = token_store or auth_module.default_store
        kwargs = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        self._client = KiwoomClient(
            credentials.base_url,
            credentials.app_key,
            credentials.secret_key,
            http_client=http_client,
            **kwargs,
        )

    @property
    def credentials(self):
        return self._credentials

    @property
    def markets(self):
        return self._markets

    @property
    def client(self):
        """하위 모듈(domestic 등)에 넘길 저수준 클라이언트."""
        return self._client

    def close(self):
        self._client.close()

    # ── 연결 확인 ────────────────────────────────────────────────────────────
    def check_connection(self) -> dict:
        """토큰 발급까지만. 실패해도 예외 대신 진단을 담은 dict 를 돌려준다.

        연동 화면이 "왜 안 되는지"를 보여줘야 하는데, 예외를 그대로 올리면
        호출부마다 문자열을 파싱하게 된다. 원인 분류는 여기서 한 번만 한다.
        """
        try:
            self._client.ensure_token()
        except KiwoomAuthError as exc:
            return {
                "ok": False,
                "reason": _classify_auth_failure(str(exc)),
                "message": str(exc),
                **self._credentials.redacted(),
            }
        except Exception as exc:  # 네트워크·HTTP 오류
            return {
                "ok": False,
                "reason": "network",
                "message": f"{type(exc).__name__}: {exc}",
                **self._credentials.redacted(),
            }
        meta = self._token_store.metadata(self._credentials.fingerprint)
        return {"ok": True, "reason": None, "message": "토큰 발급 성공",
                **self._credentials.redacted(), **meta}

    # ── 조회 ────────────────────────────────────────────────────────────────
    def fetch_accounts(self) -> list[AccountRef]:
        pages = domestic.fetch_account_list(self._client)
        self._last_account_pages = pages
        refs = []
        for account in domestic.parse_account_list(pages):
            external = account.get("external_account_id") or account.get("account_no") or ""
            refs.append(
                AccountRef(
                    external_account_id=external,
                    account_name=account.get("account_name"),
                    account_type=account.get("account_type"),
                    account_number_masked=mask_account_number(external),
                )
            )
        return refs

    def fetch_portfolio(self, account: AccountRef) -> AccountPortfolio:
        raw_account = {
            "external_account_id": account.external_account_id,
            "account_name": account.account_name,
            "account_type": account.account_type,
        }
        raw_pages: list[tuple[str, dict]] = []
        balance = deposit = None
        us_balance = us_deposit = us_detail = None

        if "KR" in self._markets:
            balance_pages = domestic.fetch_balance(self._client, raw_account)
            deposit_pages = domestic.fetch_deposit(self._client, raw_account)
            balance = domestic.parse_balance(balance_pages)
            deposit = domestic.parse_deposit(deposit_pages)
            raw_pages += [(domestic.API_BALANCE, p) for p in balance_pages]
            raw_pages += [(domestic.API_DEPOSIT, p) for p in deposit_pages]

        if "US" in self._markets:
            us_balance_pages = us_equities.fetch_positions(self._client, raw_account)
            us_deposit_pages = us_equities.fetch_deposit(self._client, raw_account)
            us_detail_pages = us_equities.fetch_deposit_detail(self._client, raw_account)
            us_balance = us_equities.parse_positions(us_balance_pages)
            us_deposit = us_equities.parse_deposit(us_deposit_pages)
            us_detail = us_equities.parse_deposit_detail(us_detail_pages)
            raw_pages += [(us_equities.API_US_POSITIONS, p) for p in us_balance_pages]
            raw_pages += [(us_equities.API_US_DEPOSIT, p) for p in us_deposit_pages]
            raw_pages += [(us_equities.API_US_DEPOSIT_DETAIL, p) for p in us_detail_pages]

        # 국내를 끄면 kt00018/kt00001 을 아예 부르지 않으므로, 국내 쪽은 빈 응답을
        # 넣어 normalize_account 가 US 만으로 계산하게 한다.
        if balance is None:
            balance = domestic.parse_balance([{"acnt_evlt_remn_indv_tot": []}])
        if deposit is None:
            deposit = domestic.parse_deposit([{}])

        normalized = normalize_account(
            raw_account, balance, deposit, us_balance, us_deposit, us_detail
        )

        # ⚠️ust21070 의 보유종목 행에는 적용환율(exch_rate)이 **오지 않는다**(2026-09-21
        #   실측: 행 키에 없음). 환율이 비면 매입원가를 KRW 로 환산할 수 없어 수익률
        #   분모가 통째로 빠진다. 같은 응답 묶음의 ust21160 이 주는 usd_exch_rate 로
        #   채운다 — 증권사가 준 값이지 우리가 계산한 값이 아니다.
        usd_rate = _usd_rate(us_detail)

        balances = normalized.get("balances", [])
        if "KR" not in self._markets:
            # ⚠️국내 TR 을 안 불렀으면 원화 예수금은 **모르는 값**이다. adapter 의
            #   _krw_cash_row 는 빈 kt00001 응답에서 0 을 만들어 내는데, 0 원과
            #   '모름'은 다르다 — 0 이라고 단언하면 화면이 없는 사실을 말하게 된다.
            #   대신 ust21160 이 주는 won_entr(원화예수금)로 채운다.
            #   ⚠️kt00001 의 D+2 결제 반영분이 아니라 D+0 값이다 — 미결제 정산이
            #     있으면 kt00001 수치와 다를 수 있다.
            won = _won_entr(us_detail)
            balances = [
                {**b, "cash_balance": won, "available_cash": None}
                if b.get("currency") == "KRW"
                else b
                for b in balances
                if b.get("currency") != "KRW" or won is not None
            ]

        positions = []
        for p in normalized.get("positions", []):
            if p.get("currency") == "USD" and p.get("exchange_rate") is None and usd_rate:
                p = {**p, "exchange_rate": usd_rate}
            positions.append(_to_position_row(p))

        return AccountPortfolio(
            account=account,
            balances=[_to_balance_row(b) for b in balances],
            positions=positions,
            as_of=datetime.now(timezone.utc),
            raw_pages=raw_pages,
        )


def _usd_rate(us_detail):
    """ust21160 의 usd_exch_rate. "1,371.70" 처럼 콤마가 섞여 온다."""
    if us_detail is None:
        return None
    raw = getattr(us_detail, "usd_exch_rate", None)
    if raw in (None, ""):
        return None
    return to_decimal(str(raw).replace(",", ""))


def _won_entr(us_detail):
    """ust21160 의 won_entr(원화예수금). 키움이 자리수 0 패딩으로 준다."""
    if us_detail is None:
        return None
    raw = getattr(us_detail, "won_entr", None)
    if raw in (None, ""):
        return None
    return to_decimal(str(raw).replace(",", ""))


def _classify_auth_failure(message: str) -> str:
    """실패 원인을 화면이 쓸 수 있는 라벨로.

    키움은 원인이 달라도 HTTP 200 + return_code=3 으로 내려주므로 메시지를 본다.
    ⚠️문자열 매칭이라 키움이 문구를 바꾸면 'unknown' 으로 떨어진다 — 그래도
      메시지 원문을 같이 들고 나가므로 화면에서 원인을 읽을 수는 있다.
    """
    text = message or ""
    if "IP" in text and ("등록" in text or "allow" in text.lower()):
        return "ip_not_allowed"
    if "8050" in text:
        return "ip_not_allowed"
    if "appkey" in text.lower() or "시크릿" in text or "secret" in text.lower():
        return "bad_credentials"
    return "unknown"


# 키움은 수익률을 **퍼센트**로 준다(prft_rt/pl_rt: 17.45 = 17.45%). 이 시스템의
# 경계 안쪽은 전부 **비율**(0.1745)로 통일한다 — API·화면·집계가 한 단위를 쓰지
# 않으면 어딘가에서 100배가 튄다. 변환은 증권사 경계인 여기서 한 번만 한다.
# 실측 검산(2026-09-21, 실계좌): 손익 -1,288,406 / 매입 8,759,000 = -14.71%,
# 키움 보고값 -14.71 — 퍼센트가 맞다.
_PERCENT = Decimal("100")


def _to_position_row(p: dict) -> PositionRow:
    return PositionRow(
        country=p.get("country", "KR"),
        market=p.get("market", "KRX"),
        ticker=p["ticker"],
        # ⚠️어댑터는 'asset_name' 키로 내보낸다. 'name' 으로 읽으면 종목명이
        #   조용히 사라진다(값이 None 이라 예외도 안 난다).
        name=p.get("asset_name") or p.get("name"),
        currency=p.get("currency", "KRW"),
        quantity=to_decimal(p.get("quantity")),
        average_purchase_price=_opt(p.get("average_purchase_price")),
        purchase_amount_local=_opt(p.get("purchase_amount_local")),
        current_price=_opt(p.get("current_price")),
        market_value_local=_opt(p.get("market_value_local")),
        unrealized_pnl_local=_opt(p.get("unrealized_pnl_local")),
        unrealized_return=_percent_to_ratio(p.get("unrealized_return")),
        exchange_rate=_opt(p.get("exchange_rate")),
        market_value_krw=_opt(p.get("market_value_krw")),
        unrealized_pnl_krw=_opt(p.get("unrealized_pnl_krw")),
        asset_type=p.get("asset_type"),
    )


def _percent_to_ratio(value):
    """퍼센트 → 비율. None 은 None 으로 둔다(0% 로 바꾸면 '미수집'이 '본전'이 된다)."""
    dec = _opt(value)
    return None if dec is None else dec / _PERCENT


def _to_balance_row(b: dict) -> BalanceRow:
    return BalanceRow(
        currency=b.get("currency", "KRW"),
        cash_balance=to_decimal(b.get("cash_balance")),
        available_cash=_opt(b.get("available_cash")),
        total_purchase_amount_local=_opt(b.get("total_purchase_amount_local")),
        total_evaluation_amount_local=_opt(b.get("total_evaluation_amount_local")),
        total_unrealized_pnl_local=_opt(b.get("total_unrealized_pnl_local")),
        exchange_rate=_opt(b.get("exchange_rate")),
    )


def _opt(value):
    """None 은 None 으로 둔다 — to_decimal 이 0 으로 바꾸면 '미수집'이 '0원'이 된다."""
    return None if value is None else to_decimal(value)
