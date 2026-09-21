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

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from ..base import (
    AccountPortfolio,
    AccountRef,
    BalanceRow,
    BrokerAdapter,
    DailyPerformanceRow,
    DividendRow,
    PositionRow,
    RealizedPnlRow,
    OrderRow,
    TradeRow,
)
from ..registry import register
from . import auth as auth_module
from . import domestic
from . import us_equities
from .adapter import (
    mask_account_number,
    normalize_account,
    percent_to_ratio as _percent_to_ratio,
    to_decimal,
)
from .client import KiwoomClient
from .exceptions import KiwoomApiError, KiwoomAuthError


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

    def fetch_trades(self, account: AccountRef, start: date, end: date) -> list[TradeRow]:
        """기간 내 체결 내역(해외). 1년 상한이 있어 창을 나눠 이어 붙인다.

        ⚠️`krw_repl_skip_yn="Y"` — 원화대용 입출금을 제외한다. 매매가 아닌 자금
          이동까지 섞이면 "체결 내역"이 아니게 된다.
        """
        if "US" not in self._markets:
            return []

        rows: list[TradeRow] = []
        seen: set[tuple] = set()
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=_TRADE_WINDOW_DAYS), end)
            pages = self._client.request_tr(
                API_US_TRADES,
                {
                    "strt_dt": window_start.strftime("%Y%m%d"),
                    "end_dt": window_end.strftime("%Y%m%d"),
                    "tp": "3",  # 3:매매 (입출금·대체 제외)
                    "stex_tp": "",
                    "stk_cd": "",
                    "krw_repl_skip_yn": "Y",
                },
                path=us_equities.US_ACNT_PATH,
            )
            for page in pages:
                for raw in page.get("result_list") or []:
                    row = _to_trade_row(raw)
                    if row is None:
                        continue
                    # 창이 겹칠 때 같은 체결이 두 번 들어오지 않게 한다.
                    key = (row.trade_date, row.trade_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
            window_start = window_end + timedelta(days=1)

        rows.sort(key=lambda r: (r.trade_date, r.trade_no))
        return rows

    def fetch_orders(self, account: AccountRef, start: date, end: date) -> list[OrderRow]:
        """기간 내 주문 내역(해외) — 체결 이력이 감추는 것들.

        ⚠️조회 상한이 **3개월**이다(체결내역은 360일). 창을 85일로 나눠 이어 붙인다.
        ⚠️명세 예시의 응답 키는 `result_lsit`(오타)인데 실제 응답은 `result_list`
          다. 둘 다 받는다 — 어느 쪽이 올지 명세만으로는 알 수 없다.
        """
        if "US" not in self._markets:
            return []

        rows: list[OrderRow] = []
        seen: set[tuple] = set()
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=_ORDER_WINDOW_DAYS), end)
            try:
                pages = self._client.request_tr(
                    API_US_ORDERS,
                    {
                        "strt_dt": window_start.strftime("%Y%m%d"),
                        "end_dt": window_end.strftime("%Y%m%d"),
                        "slby_tp": "",
                        "stex_tp": "",
                        "stk_cd": "",
                        "oppo_trde_tp": "",
                    },
                    path=us_equities.US_ACNT_PATH,
                )
            except KiwoomApiError as exc:
                # ⚠️ust21530 과 똑같이, 주문이 없는 창은 **빈 목록이 아니라 에러**로
                #   온다(571758 "조회내역이 없습니다"). 계좌 개설 이전 구간은 당연히
                #   비어 있으므로, 이걸 안 걸러내면 창 하나 때문에 조회 전체가 죽는다.
                #   실측: 730일 동기화에서 이 예외가 이력 블록을 통째로 날려
                #   체결·실현손익·배당까지 0 건이 됐다(화면에는 '성공'으로 보였다).
                if _is_no_data(exc):
                    window_start = window_end + timedelta(days=1)
                    continue
                raise
            for page in pages:
                for raw in page.get("result_list") or page.get("result_lsit") or []:
                    row = _to_order_row(raw)
                    if row is None:
                        continue
                    key = (row.order_date, row.order_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
            window_start = window_end + timedelta(days=1)

        rows.sort(key=lambda r: (r.order_date, r.order_time or "", r.order_no))
        return rows

    def fetch_daily_performance(self, account, start: date, end: date):
        """일별 계좌 성과. 거래가 없는 날도 행이 온다(값이 전날과 같다)."""
        if "US" not in self._markets:
            return []
        rows: dict[date, DailyPerformanceRow] = {}
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=_TRADE_WINDOW_DAYS), end)
            pages = self._client.request_tr(
                API_US_DAILY_PERF,
                {"from": window_start.strftime("%Y%m%d"), "to": window_end.strftime("%Y%m%d")},
                path=us_equities.US_ACNT_PATH,
            )
            for page in pages:
                for raw in page.get("result_list") or []:
                    base = _parse_yyyymmdd(raw.get("base_dt"))
                    if base is None:
                        continue
                    # 창이 겹치면 같은 날짜가 두 번 온다 — 날짜를 키로 덮어쓴다.
                    rows[base] = DailyPerformanceRow(
                        base_date=base,
                        deposit_assets_krw=_opt(raw.get("dast")),
                        stock_value_krw=_opt(raw.get("stk_evlta")),
                        pnl_krw=_opt(raw.get("pl_amt")),
                        cumulative_pnl_krw=_opt(raw.get("acum_pl_amt")),
                        dividend_krw=_opt(raw.get("dvid_amt")),
                        commission_tax_krw=_opt(raw.get("cmsn_tax")),
                        buy_amount_krw=_opt(raw.get("buy_amt")),
                        sell_amount_krw=_opt(raw.get("sell_amt")),
                        deposit_krw=_opt(raw.get("ina_amt")),
                        withdrawal_krw=_opt(raw.get("pymn_amt")),
                        return_rate=_percent_to_ratio(raw.get("prft_rt")),
                        exchange_rate=_opt(raw.get("exrt")),
                    )
            window_start = window_end + timedelta(days=1)
        return [rows[d] for d in sorted(rows)]

    def fetch_realized_pnl(self, account, start: date, end: date):
        """실현손익. 외화·원화를 각각 받아 합친다 — 우리가 환율을 곱해 만들지 않는다.

        ⚠️매입환율과 매도환율이 달라서(실측 1,428.63 vs 1,543.00) 단일 환율로는
          증권사 값을 재현할 수 없다. 그래서 두 번 부른다.
        """
        if "US" not in self._markets:
            return []

        merged: dict[tuple, dict] = {}
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=_REALIZED_WINDOW_DAYS), end)
            for fc_krw_tp, bucket in (("0", "local"), ("1", "krw")):
                try:
                    pages = self._client.request_tr(
                        API_US_REALIZED,
                        {
                            "strt_dt": window_start.strftime("%Y%m%d"),
                            "end_dt": window_end.strftime("%Y%m%d"),
                            "fc_krw_tp": fc_krw_tp,
                        },
                        path=us_equities.US_ACNT_PATH,
                    )
                except KiwoomApiError as exc:
                    if _is_no_data(exc):
                        continue  # 이 창에는 매도가 없었다 — 실패가 아니다.
                    raise
                for page in pages:
                    for raw in page.get("result_list") or []:
                        sell_date = _parse_yyyymmdd(raw.get("sell_dt"))
                        ticker = (raw.get("stk_cd") or "").strip()
                        if sell_date is None or not ticker:
                            continue
                        entry = merged.setdefault((sell_date, ticker), {})
                        entry[bucket] = raw
            window_start = window_end + timedelta(days=1)

        out = []
        for (sell_date, ticker), parts in sorted(merged.items()):
            local = parts.get("local") or {}
            krw = parts.get("krw") or {}
            anchor = local or krw
            out.append(
                RealizedPnlRow(
                    sell_date=sell_date,
                    ticker=ticker,
                    name=(anchor.get("frgn_stk_nm") or None),
                    currency="USD",
                    quantity=to_decimal(anchor.get("sell_qty")),
                    avg_buy_price=_opt(local.get("avg_buy_uv")),
                    avg_sell_price=_opt(local.get("avg_sell_uv")),
                    buy_amount_local=_opt(local.get("buy_amt")),
                    sell_amount_local=_opt(local.get("sell_amt")),
                    commission_tax_local=_opt(local.get("cmsn_tax")),
                    pnl_local=_opt(local.get("pl_amt")),
                    buy_amount_krw=_opt(krw.get("buy_amt")),
                    sell_amount_krw=_opt(krw.get("sell_amt")),
                    commission_tax_krw=_opt(krw.get("cmsn_tax")),
                    pnl_krw=_opt(krw.get("pl_amt")),
                    pnl_rate=_percent_to_ratio(anchor.get("pl_rt")),
                    buy_exchange_rate=_opt(anchor.get("prch_exrt")),
                    sell_exchange_rate=_opt(anchor.get("sell_exrt")),
                    # 환차손익은 외화/원화 어느 호출에서나 **원화**로 온다.
                    fx_pnl_krw=_opt(anchor.get("krw_chg_dfrn_pl_amt")),
                    exchange=(anchor.get("stex_nm") or None),
                )
            )
        return out

    def fetch_dividends(self, account, tickers, start: date, end: date):
        """배당 수령 이력.

        배당 전용 TR 이 없어 일별 종목수익률(usa21730)의 dvid_amt 를 골라낸다.
        배당이 0 인 날이 대부분이라 0 은 버린다.

        ⚠️종목마다 거래소 코드를 알아야 하는데 잔고 응답이 알려주지 않는다. 이미
          아는 코드가 있으면 그것만 쓰고, 없으면 ND→NY→NA 로 찾는다. 찾은 코드는
          결과에 실어 보내 호출부가 저장하게 한다(다음부터 헛호출이 줄어든다).
        """
        if "US" not in self._markets:
            return []

        out: list[DividendRow] = []
        for ticker, known_code in tickers:
            if not ticker:
                continue
            code = known_code or self._resolve_exchange_code(ticker, end)
            if code is None:
                continue  # 세 거래소 어디에도 없다 — 조회 대상이 아니다.
            try:
                pages = self._client.request_tr(
                    API_US_STOCK_DAILY,
                    {
                        "from": start.strftime("%Y%m%d"),
                        "to": end.strftime("%Y%m%d"),
                        "stex_tp": code,
                        "stk_cd": ticker,
                    },
                    path=us_equities.US_ACNT_PATH,
                )
            except KiwoomApiError as exc:
                if _is_unknown_symbol(exc):
                    continue
                raise
            for page in pages:
                for raw in page.get("result_list") or []:
                    amount = _opt(raw.get("dvid_amt"))
                    if not amount:
                        continue  # 배당 없는 날 — 대부분이다.
                    pay_date = _parse_yyyymmdd(
                        raw.get("last_base_dt") or raw.get("frst_base_dt")
                    )
                    if pay_date is None:
                        continue
                    out.append(
                        DividendRow(
                            pay_date=pay_date,
                            ticker=ticker,
                            name=(raw.get("stk_nm") or None),
                            amount_krw=amount,
                            currency="KRW",
                            broker_exchange_code=code,
                        )
                    )

        out.sort(key=lambda d: (d.pay_date, d.ticker))
        return out

    def _resolve_exchange_code(self, ticker: str, end: date) -> str | None:
        """종목이 어느 거래소인지 찾는다(ND/NY/NA).

        ⚠️탐색에 **짧은 구간**을 쓴다. 전체 구간(1년)으로 찾으면 응답이 360행이라
          한 종목에 최대 3번 무거운 조회가 나가고, 실제로 read timeout 이 났다.
          맞는 거래소인지만 보면 되므로 며칠이면 충분하다.
        """
        probe_start = end - timedelta(days=_EXCHANGE_PROBE_DAYS)
        for code in _US_EXCHANGE_CODES:
            try:
                self._client.request_tr(
                    API_US_STOCK_DAILY,
                    {
                        "from": probe_start.strftime("%Y%m%d"),
                        "to": end.strftime("%Y%m%d"),
                        "stex_tp": code,
                        "stk_cd": ticker,
                    },
                    path=us_equities.US_ACNT_PATH,
                )
                return code
            except KiwoomApiError as exc:
                if _is_unknown_symbol(exc):
                    continue
                raise
        return None

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


# 키움 거래내역(ust21100) 상수. 값은 api_guide.md §5 / 공식 명세 참조.
API_US_TRADES = "ust21100"
API_US_ORDERS = "ust21180"
#: 조회 기간 상한. 초과하면 return_code=20 / 501058 "조회기간은 1년 이내로만 가능합니다".
#: 실측상 365일도 거부되므로 여유를 둔다.
_TRADE_WINDOW_DAYS = 360
# ⚠️주문내역(ust21180)은 **3개월 상한**이다. 체결내역(360일)과 다르다 —
#   실측: 20260601~20260922 요청에 "조회기간은 3개월 이내만 가능합니다"(return_code=20).
#   여유를 두고 85일로 끊는다.
_ORDER_WINDOW_DAYS = 85

# 주문 구분 문자열 → 표준 side. 응답은 "매수"/"매도" 로 온다.
_SIDE_BY_ORDER_NAME = {"매수": "BUY", "매도": "SELL"}
#: 매수/매도 구분은 deal_kind_nm(전부 "매매")이 아니라 rmrk_nm(적요명)에 있다.
_SIDE_BY_REMARK = {"매수": "BUY", "매도": "SELL"}

#: 일별 계좌수익률(usa21670). 조회 상한은 ust21100 과 같은 1년으로 보고 창을 나눈다.
API_US_DAILY_PERF = "usa21670"
#: 실현손익(ust21530). ⚠️상한이 **6개월**이다 — 초과 시 return_code=20 / 505657
#:  "조회기간은 6개월 이내만 가능합니다". 거래내역(1년)과 다르므로 따로 둔다.
API_US_REALIZED = "ust21530"
_REALIZED_WINDOW_DAYS = 175

#: 일별 종목수익률(usa21730). **배당 전용 TR 이 없어** 이 응답의 dvid_amt 를 쓴다.
API_US_STOCK_DAILY = "usa21730"
#: ⚠️usa21730 은 stk_cd 와 stex_tp 가 **둘 다 필수**다. 그런데 보유종목 응답의
#:  stex_nm 은 "미국"이라 거래소를 알려주지 않는다(실측). 아래 순서로 시도해
#:  값이 오는 코드를 찾는다 — 나스닥 종목이 가장 많아 ND 를 먼저 본다.
_US_EXCHANGE_CODES = ("ND", "NY", "NA")
#: 종목코드/거래소가 안 맞을 때의 코드. '없음'이지 실패가 아니다.
_UNKNOWN_SYMBOL_CODE = "1903"
#: 거래소 코드 탐색에 쓰는 구간(일). 짧게 잡아야 한다 — 전체 구간으로 찾으면
#: 한 종목에 최대 3번 360행짜리 조회가 나가 read timeout 이 난다(실측).
_EXCHANGE_PROBE_DAYS = 5


def _is_unknown_symbol(exc) -> bool:
    return _UNKNOWN_SYMBOL_CODE in (getattr(exc, "return_msg", "") or "")
#: ⚠️ust21530·ust21180 은 해당 기간에 내역이 없으면 **빈 목록이 아니라 에러**를 낸다
#:  (return_code=20 / 571758 "조회내역이 없습니다"). 여러 창으로 나눠 조회할 때
#:  매도가 없는 창이 하나만 있어도 전체가 죽으므로, 이 코드는 '없음'으로 읽는다.
_NO_DATA_CODE = "571758"


def _is_no_data(exc) -> bool:
    return _NO_DATA_CODE in (getattr(exc, "return_msg", "") or "")


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
        # ⚠️여기서 다시 나누지 않는다 — adapter.percent_to_ratio 가 이미 비율로
        #   바꿔 놨다. 두 번 나누면 100배 작아진다.
        unrealized_return=_opt(p.get("unrealized_return")),
        exchange_rate=_opt(p.get("exchange_rate")),
        market_value_krw=_opt(p.get("market_value_krw")),
        unrealized_pnl_krw=_opt(p.get("unrealized_pnl_krw")),
        asset_type=p.get("asset_type"),
    )





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


def _to_order_row(raw: dict) -> OrderRow | None:
    """ust21180 한 행 → OrderRow. 매수/매도가 아니면 버린다."""
    side = _SIDE_BY_ORDER_NAME.get((raw.get("slby_tp_nm") or "").strip())
    if side is None:
        return None
    order_date = _parse_yyyymmdd(raw.get("ord_dt"))
    if order_date is None:
        return None
    ticker = (raw.get("stk_cd") or "").strip()
    if not ticker:
        return None

    return OrderRow(
        order_date=order_date,
        # 0 패딩을 벗기지 않는다 — 증권사가 준 형태가 자연키의 일부다.
        order_no=(raw.get("ord_no") or "").strip(),
        side=side,
        ticker=ticker,
        name=(raw.get("stk_nm") or None),
        currency=(raw.get("crnc_code") or "USD").strip(),
        order_time=(raw.get("ord_time") or None),
        order_type=(raw.get("trde_tp") or None),
        order_quantity=_opt(raw.get("ord_qty")),
        filled_quantity=to_decimal(raw.get("cntr_qty")),
        cancelled_quantity=to_decimal(raw.get("cncl_qty")),
        modified_quantity=to_decimal(raw.get("mdfy_qty")),
        remaining_quantity=to_decimal(raw.get("ord_remnq")),
        order_price=_nonzero(raw.get("ord_uv")),
        # ⚠️미체결이면 0 으로 온다. 0 을 그대로 두면 "0달러에 체결"로 읽힌다.
        filled_price=_nonzero(raw.get("cntr_uv")),
        stop_price=_nonzero(raw.get("stop_pric")),
        filled_amount=_nonzero(raw.get("cntr_amt")),
        exchange=(raw.get("stex_nm") or None),
        channel=(raw.get("inpt_chnl_tp_nm") or None),
        reserve_type=(raw.get("rsrv_tp") or None),
    )


def _to_trade_row(raw: dict) -> TradeRow | None:
    """ust21100 result_list 한 행 → TradeRow. 매수/매도가 아니면 버린다."""
    side = _SIDE_BY_REMARK.get((raw.get("rmrk_nm") or "").strip())
    if side is None:
        return None
    trade_date = _parse_yyyymmdd(raw.get("deal_dt"))
    if trade_date is None:
        return None
    return TradeRow(
        trade_date=trade_date,
        # 0 패딩을 벗기지 않는다 — 증권사가 준 형태 그대로가 자연키의 일부다.
        trade_no=(raw.get("deal_no") or "").strip(),
        side=side,
        ticker=(raw.get("stk_cd") or "").strip(),
        name=(raw.get("stk_nm") or None),
        currency=(raw.get("crnc_code") or "USD").strip(),
        quantity=to_decimal(raw.get("deal_qty")),
        # uv_exrt 는 '거래단가/환율' 겸용 필드 — 해외 거래에서는 단가다.
        price=_opt(raw.get("uv_exrt")),
        amount_local=_opt(raw.get("fc_deal_amt")),
        settlement_amount_local=_opt(raw.get("fc_exct_amt")),
        commission_local=_opt(raw.get("fc_cmsn")),
        tax_local=_opt(raw.get("fc_deal_tax")),
        # ⚠️해외 거래는 원화 금액이 0 으로 온다. 0 을 금액으로 저장하면 "거래금액
        #   0원"이라는 틀린 사실이 남으므로, 0 이면 '없음'으로 둔다.
        amount_krw=_nonzero(raw.get("deal_amt")),
        exchange=(raw.get("stex_nm") or None),
        channel=(raw.get("mdia_nm") or None),
        processed_at=(raw.get("proc_time") or None),
    )


def _parse_yyyymmdd(value):
    """키움 날짜 파싱.

    ⚠️TR 마다 형식이 다르다(실측 2026-09-21):
       ust21100 거래내역        → "20260916"   (8자리)
       usa21730 일별종목수익률   → "2026-06-30" (하이픈)
      하나만 받으면 다른 쪽이 통째로 버려진다 — 배당이 0건으로 나왔던 원인이다.
      예외도 안 나고 조용히 빈다.
    """
    text = (value or "").strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _nonzero(value):
    dec = _opt(value)
    return None if dec is None or dec == 0 else dec
