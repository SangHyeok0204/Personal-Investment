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
    DividendFetch,
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
    normalize_ticker,
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
        #: 응답 모양이 예상과 다른 경우를 모은다. `shape_warnings` 로 꺼내 쓴다.
        self._shape_warnings: list[str] = []

    @property
    def credentials(self):
        return self._credentials

    @property
    def shape_warnings(self) -> list[str]:
        """응답에서 **아는 키를 하나도 못 찾은** 조회들.

        ★왜 필요한가: 모든 파서가 `page.get("result_list") or []` 로 시작한다.
          그래서 증권사가 키 이름을 바꾸면 **0건이 조용히 돌아온다** — 동기화는
          성공으로 끝나고 화면은 "거래 없음"이라고 말한다. 가정이 아니라 이미
          겪은 일이다: 주문 조회(ust21180)는 명세 예시가 `result_lsit`(오타)라
          두 키를 모두 받아 주고 있다. 다음번엔 못 맞힐 수도 있다.

        ⚠️**'데이터 없음'과 '모양이 바뀜'은 다르다.** 빈 목록(`result_list: []`)은
          데이터가 없는 것이고, 키 자체가 없는 것은 우리가 못 읽는 것이다.
          후자를 0건으로 넘기면 아무도 모른다.
        """
        return list(self._shape_warnings)

    def _rows(self, page: dict, *keys: str, tr: str) -> list:
        """응답 한 장에서 행 목록을 꺼낸다. 아는 키가 없으면 **기록하고** 빈 목록.

        ⚠️여기서 예외를 던지지 않는다. 한 장이 이상하다고 동기화 전체를 죽이면
          잔고까지 못 받는다 — 모아서 알리고 나머지는 계속 받는다.
        """
        for key in keys:
            if key in page:
                return page.get(key) or []
        seen = ", ".join(sorted(k for k in page if not k.startswith("return_"))[:6])
        self._shape_warnings.append(
            f"{tr}: 응답에서 {' / '.join(keys)} 를 찾지 못했습니다"
            f"(있는 키: {seen or '없음'}). 0건으로 읽었지만 **데이터가 없다는 뜻이"
            f" 아닙니다** — 증권사 응답 형식이 바뀌었을 수 있습니다."
        )
        return []

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
        """기간 내 체결 내역. 국내(kt00015)·해외(ust21100)를 각각 받아 합친다.

        ⚠️거래번호는 **일자별로 1 부터 리셋**되고 국내·해외가 따로 매긴다. 같은
          날 양쪽을 거래하면 1번이 둘 나온다 — 그래서 중복 제거도 저장도
          시장(market)까지 넣어서 한다(alembic 0018). 시장을 빼면 한쪽이 조용히
          덮인다.
        """
        rows: list[TradeRow] = []
        if "US" in self._markets:
            rows.extend(self._fetch_us_trades(start, end))
        if "KR" in self._markets:
            rows.extend(self._fetch_kr_trades(start, end))
        rows.sort(key=lambda r: (r.trade_date, r.market, r.trade_no))
        return rows

    def _fetch_us_trades(self, start: date, end: date) -> list[TradeRow]:
        """해외 체결(ust21100). 1년 상한이 있어 창을 나눠 이어 붙인다.

        ⚠️`krw_repl_skip_yn="Y"` — 원화대용 입출금을 제외한다. 매매가 아닌 자금
          이동까지 섞이면 "체결 내역"이 아니게 된다.
        """
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
                for raw in self._rows(page, "result_list", tr=API_US_TRADES):
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
        return rows

    def _fetch_kr_trades(self, start: date, end: date) -> list[TradeRow]:
        """국내 체결(kt00015 위탁종합거래내역).

        ⚠️조회기간 상한이 명세에 적혀 있지 않다. 해외 거래내역과 같은 1년으로
          보고 창을 나눈다 — 상한이 더 짧으면 에러로 드러나고, 더 길면 그냥
          호출이 몇 번 더 나갈 뿐이다. TO-VERIFY(2년치 한 번에 되는지 미확인).

        ⚠️응답 배열 키가 해외와 다르다(`trst_ovrl_trde_prps_array`). 해외 키로
          찾으면 **에러 없이 0건**이 된다.
        """
        rows: list[TradeRow] = []
        seen: set[tuple] = set()
        window_start = start
        while window_start <= end:
            window_end = min(window_start + timedelta(days=_TRADE_WINDOW_DAYS), end)
            try:
                pages = self._client.request_tr(
                    domestic.API_TRADE_HISTORY,
                    domestic.trade_history_body(window_start, window_end),
                )
            except KiwoomApiError as exc:
                if _is_no_data(exc):
                    window_start = window_end + timedelta(days=1)
                    continue  # 이 창에는 매매가 없었다 — 실패가 아니다.
                raise
            for page in pages:
                for raw in self._rows(
                    page, "trst_ovrl_trde_prps_array", tr=domestic.API_TRADE_HISTORY
                ):
                    row = _to_domestic_trade_row(raw)
                    if row is None:
                        continue
                    key = (row.trade_date, row.trade_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
            window_start = window_end + timedelta(days=1)
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
                for raw in self._rows(
                    page, "result_list", "result_lsit", tr=API_US_ORDERS
                ):
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
                for raw in self._rows(page, "result_list", tr=API_US_DAILY_PERF):
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
                    for raw in self._rows(page, "result_list", tr=API_US_REALIZED):
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

        ⚠️**못 물어본 종목을 조용히 넘기지 않는다.** 거래소를 못 찾거나 증권사가
          모르는 종목이라고 답하면 그 종목은 조회 자체를 못 한 것인데, 예전에는
          그냥 `continue` 했다. 그러면 화면에서 **'배당 0원'과 '안 물어봤다'가
          똑같이 보인다** — 배당을 주는 종목인데 빠져 있어도 알 길이 없다.
          건너뛴 티커를 두 번째 값으로 함께 돌려준다.

        돌려주는 것: `DividendFetch(배당 행, 건너뛴 티커, 새로 알아낸 거래소 코드)`

        ⚠️**배당이 0건이어도 알아낸 코드는 돌려준다.** 남겨 두지 않으면 다음
          동기화에서 같은 종목을 또 세 번 더듬는다.
        """
        if "US" not in self._markets:
            return DividendFetch(rows=[], skipped=[], exchange_codes={})

        out: list[DividendRow] = []
        skipped: list[str] = []
        found: dict[str, str] = {}
        for ticker, known_code in tickers:
            if not ticker:
                continue
            code = known_code or self._resolve_exchange_code(ticker, end)
            if code is None:
                # 세 거래소 어디에도 없다 — **조회를 못 한 것**이지 배당이 0 인 게 아니다.
                skipped.append(ticker)
                continue
            if code != known_code:
                found[ticker] = code
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
                    skipped.append(ticker)
                    continue
                raise
            for page in pages:
                for raw in self._rows(page, "result_list", tr=API_US_STOCK_DAILY):
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
        return DividendFetch(
            rows=out, skipped=sorted(set(skipped)), exchange_codes=found
        )

    def _resolve_exchange_code(self, ticker: str, end: date) -> str | None:
        """종목이 어느 거래소인지 찾는다(ND/NY/NA).

        ⚠️탐색에 **짧은 구간**을 쓴다. 전체 구간(1년)으로 찾으면 응답이 360행이라
          한 종목에 최대 3번 무거운 조회가 나가고, 실제로 read timeout 이 났다.
          맞는 거래소인지만 보면 되므로 며칠이면 충분하다.

        ⚠️**알려진 약점(2026-09-23).** 여기는 "에러가 안 나면 맞는 거래소"로
          친다 — 빈 응답도 통과한다. 그래서 **최근 5일 안에 아무 행이 없는
          종목**(이미 판 종목이 특히 그렇다)은 첫 코드인 ND 가 그대로 붙는다.
          그 종목이 사실 NYSE 면 배당 조회가 조용히 빈 값을 돌려준다 —
          건너뛴 것으로도 안 잡힌다.

          고치려면 "행이 온 코드만 인정"으로 바꿔야 하는데, 그러면 판 종목은
          매번 건너뛴 것으로 보고된다. 제대로 된 답은 **찾은 코드를 티커별로
          기억하는 것**이다. 지금은 `assets.broker_exchange_code` 에만 적는데
          assets 에는 보유 종목만 있어서 판 종목은 못 남긴다(실측: SGOV 는
          배당이 14건이나 들어왔는데 코드가 안 남아 매번 다시 더듬는다).
          `dividends` 테이블에 코드 칸이 없어 마이그레이션이 필요하다.
        """
        probe_start = end - timedelta(days=_EXCHANGE_PROBE_DAYS)
        for code in _US_EXCHANGE_CODES:
            try:
                pages = self._client.request_tr(
                    API_US_STOCK_DAILY,
                    {
                        "from": probe_start.strftime("%Y%m%d"),
                        "to": end.strftime("%Y%m%d"),
                        "stex_tp": code,
                        "stk_cd": ticker,
                    },
                    path=us_equities.US_ACNT_PATH,
                )
                # ⚠️**행이 온 코드만 인정한다.** 예전에는 "에러가 안 나면 맞는
                #   거래소"로 쳤는데, 빈 응답도 통과해서 첫 코드(ND)가 그대로
                #   붙었다. 그 종목이 사실 NYSE 면 배당 조회가 조용히 빈 값을
                #   돌려주고, 건너뛴 것으로도 안 잡힌다 — 화면에는 '배당 0원'으로
                #   보인다. 못 찾으면 못 찾았다고 하는 편이 낫다(호출부가 센다).
                if any(page.get("result_list") for page in pages):
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
        market="US",
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


def _domestic_side(rmrk_nm: str) -> str | None:
    """국내 적요명 → BUY/SELL. 해외와 달리 "현금매수"/"자기융자매도"처럼 앞에
    거래 형태가 붙어 온다 — 완전일치로 찾으면 **전부 버려진다**(0건, 예외 없음).

    ⚠️"매도"를 먼저 본다. 둘 다 들어 있는 적요명은 없어야 맞지만, 있다면
      매도로 보는 쪽이 안전하다(세금·실현손익이 걸린 쪽이다).
    """
    text = (rmrk_nm or "").strip()
    if "매도" in text:
        return "SELL"
    if "매수" in text:
        return "BUY"
    return None


def _to_domestic_trade_row(raw: dict) -> TradeRow | None:
    """kt00015 trst_ovrl_trde_prps_array 한 행 → TradeRow.

    tp="3"(매매)로 걸러 받지만 적요명이 매수/매도가 아니면 버린다 — 같은 배열에
    대출상환·연체 같은 행이 섞여 올 수 있다.

    ⚠️종목코드에 **접두어 1자리**가 붙어 온다("A005930"). 그대로 저장하면
      잔고·자산 마스터의 "005930" 과 다른 종목이 되어 화면에서 갈라진다.
    """
    side = _domestic_side(raw.get("rmrk_nm"))
    if side is None:
        return None
    trade_date = _parse_yyyymmdd(raw.get("trde_dt"))
    if trade_date is None:
        return None
    ticker = normalize_ticker(raw.get("stk_cd"))
    if not ticker:
        return None
    return TradeRow(
        trade_date=trade_date,
        # 0 패딩을 벗기지 않는다 — 증권사가 준 형태 그대로가 자연키의 일부다.
        trade_no=(raw.get("trde_no") or "").strip(),
        market="KR",
        side=side,
        ticker=ticker,
        name=(raw.get("stk_nm") or None),
        currency=(raw.get("crnc_cd") or "KRW").strip() or "KRW",
        quantity=to_decimal(raw.get("trde_qty_jwa_cnt")),
        # trde_unit 은 '거래단가/환율' 겸용 필드 — 주문 거래에서는 단가다.
        price=_opt(raw.get("trde_unit")),
        amount_local=_opt(raw.get("trde_amt")),
        settlement_amount_local=_opt(raw.get("exct_amt")),
        commission_local=_opt(raw.get("cmsn")),
        # 거래세+농특세. 소득/주민세(incm_resi_tax)는 매매세금이 아니라 따로다.
        tax_local=_opt(raw.get("trde_agri_tax")),
        # 국내는 원화 거래라 local 이 곧 원화다. 해외처럼 0 으로 오지 않는다.
        amount_krw=_opt(raw.get("trde_amt")),
        exchange=(raw.get("stex_nm") or None),
        channel=(raw.get("mdia_tp_nm") or None),
        processed_at=(raw.get("proc_tm") or None),
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
