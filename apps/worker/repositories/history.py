"""체결·일별성과·실현손익 적재 (alembic 0007·0008).

전부 **덮어쓰기(upsert)** 다. 같은 기간을 다시 조회해도 행이 늘지 않아야 한다 —
증권사가 값을 사후 정정하는 경우(예: 정산 확정)가 있어 최신 값으로 갱신되어야 하고,
동기화를 두 번 돌렸다고 체결이 두 배로 보이면 안 된다.

자연키는 실측으로 정한 것들이다(api_guide.md §2 참고):
  trades                     (account_id, market, settlement_date, trade_no)
                               ← trade_no 는 **결제일** 기준 일자별 리셋(alembic 0018·0028)
  account_daily_performance  (account_id, base_date)
  realized_pnl               (account_id, sell_date, ticker)     ← 증권사가 매도일×종목 집계
  orders                     (account_id, order_date, order_no)  ← 주문 상태는 사후에 바뀐다
"""
import uuid
from collections import defaultdict

from sqlalchemy import text

_TRADE_UPSERT = text(
    """
    INSERT INTO trades (
        id, account_id, asset_id, ticker, asset_name, trade_date, settlement_date,
        trade_date_source, trade_no, market, side,
        quantity, price, currency, amount_local, settlement_amount_local,
        commission_local, tax_local, amount_krw, exchange, channel, processed_at,
        source_job_id
    ) VALUES (
        :id, :account_id, :asset_id, :ticker, :asset_name, :trade_date, :settlement_date,
        :trade_date_source, :trade_no, :market, :side,
        :quantity, :price, :currency, :amount_local, :settlement_amount_local,
        :commission_local, :tax_local, :amount_krw, :exchange, :channel, :processed_at,
        :source_job_id
    )
    ON CONFLICT (account_id, market, settlement_date, trade_no) DO UPDATE SET
        -- ★2026-10-05 주문과 짝지어 복원한 체결일은 재동기화가 결제일로 되돌리지 않는다.
        --   (짝짓기는 적재 뒤 resolve_us_trade_dates 가 매번 다시 한다.)
        trade_date = CASE WHEN trades.trade_date_source = 'order'
                          THEN trades.trade_date ELSE EXCLUDED.trade_date END,
        trade_date_source = CASE WHEN trades.trade_date_source = 'order'
                                 THEN trades.trade_date_source
                                 ELSE EXCLUDED.trade_date_source END,
        asset_id = EXCLUDED.asset_id,
        ticker = EXCLUDED.ticker,
        asset_name = EXCLUDED.asset_name,
        side = EXCLUDED.side,
        quantity = EXCLUDED.quantity,
        price = EXCLUDED.price,
        currency = EXCLUDED.currency,
        amount_local = EXCLUDED.amount_local,
        settlement_amount_local = EXCLUDED.settlement_amount_local,
        commission_local = EXCLUDED.commission_local,
        tax_local = EXCLUDED.tax_local,
        amount_krw = EXCLUDED.amount_krw,
        exchange = EXCLUDED.exchange,
        channel = EXCLUDED.channel,
        processed_at = EXCLUDED.processed_at,
        source_job_id = EXCLUDED.source_job_id,
        updated_at = now()
    """
)

_PERF_UPSERT = text(
    """
    INSERT INTO account_daily_performance (
        id, account_id, base_date, deposit_assets_krw, stock_value_krw, pnl_krw,
        cumulative_pnl_krw, dividend_krw, commission_tax_krw, buy_amount_krw,
        sell_amount_krw, deposit_krw, withdrawal_krw, return_rate, exchange_rate,
        source_job_id
    ) VALUES (
        :id, :account_id, :base_date, :deposit_assets_krw, :stock_value_krw, :pnl_krw,
        :cumulative_pnl_krw, :dividend_krw, :commission_tax_krw, :buy_amount_krw,
        :sell_amount_krw, :deposit_krw, :withdrawal_krw, :return_rate, :exchange_rate,
        :source_job_id
    )
    ON CONFLICT (account_id, base_date) DO UPDATE SET
        deposit_assets_krw = EXCLUDED.deposit_assets_krw,
        stock_value_krw = EXCLUDED.stock_value_krw,
        pnl_krw = EXCLUDED.pnl_krw,
        cumulative_pnl_krw = EXCLUDED.cumulative_pnl_krw,
        dividend_krw = EXCLUDED.dividend_krw,
        commission_tax_krw = EXCLUDED.commission_tax_krw,
        buy_amount_krw = EXCLUDED.buy_amount_krw,
        sell_amount_krw = EXCLUDED.sell_amount_krw,
        deposit_krw = EXCLUDED.deposit_krw,
        withdrawal_krw = EXCLUDED.withdrawal_krw,
        return_rate = EXCLUDED.return_rate,
        exchange_rate = EXCLUDED.exchange_rate,
        source_job_id = EXCLUDED.source_job_id,
        updated_at = now()
    """
)

_REALIZED_UPSERT = text(
    """
    INSERT INTO realized_pnl (
        id, account_id, asset_id, ticker, asset_name, sell_date, quantity, currency,
        avg_buy_price, avg_sell_price, buy_amount_local, sell_amount_local,
        commission_tax_local, pnl_local, buy_amount_krw, sell_amount_krw,
        commission_tax_krw, pnl_krw, pnl_rate, buy_exchange_rate, sell_exchange_rate,
        fx_pnl_krw, exchange, source_job_id
    ) VALUES (
        :id, :account_id, :asset_id, :ticker, :asset_name, :sell_date, :quantity, :currency,
        :avg_buy_price, :avg_sell_price, :buy_amount_local, :sell_amount_local,
        :commission_tax_local, :pnl_local, :buy_amount_krw, :sell_amount_krw,
        :commission_tax_krw, :pnl_krw, :pnl_rate, :buy_exchange_rate, :sell_exchange_rate,
        :fx_pnl_krw, :exchange, :source_job_id
    )
    ON CONFLICT (account_id, sell_date, ticker) DO UPDATE SET
        asset_id = EXCLUDED.asset_id,
        asset_name = EXCLUDED.asset_name,
        quantity = EXCLUDED.quantity,
        currency = EXCLUDED.currency,
        avg_buy_price = EXCLUDED.avg_buy_price,
        avg_sell_price = EXCLUDED.avg_sell_price,
        buy_amount_local = EXCLUDED.buy_amount_local,
        sell_amount_local = EXCLUDED.sell_amount_local,
        commission_tax_local = EXCLUDED.commission_tax_local,
        pnl_local = EXCLUDED.pnl_local,
        buy_amount_krw = EXCLUDED.buy_amount_krw,
        sell_amount_krw = EXCLUDED.sell_amount_krw,
        commission_tax_krw = EXCLUDED.commission_tax_krw,
        pnl_krw = EXCLUDED.pnl_krw,
        pnl_rate = EXCLUDED.pnl_rate,
        buy_exchange_rate = EXCLUDED.buy_exchange_rate,
        sell_exchange_rate = EXCLUDED.sell_exchange_rate,
        fx_pnl_krw = EXCLUDED.fx_pnl_krw,
        exchange = EXCLUDED.exchange,
        source_job_id = EXCLUDED.source_job_id,
        updated_at = now()
    """
)

_DIVIDEND_UPSERT = text(
    """
    INSERT INTO dividends (
        id, account_id, asset_id, ticker, asset_name, pay_date, amount_krw,
        currency, source_job_id
    ) VALUES (
        :id, :account_id, :asset_id, :ticker, :asset_name, :pay_date, :amount_krw,
        :currency, :source_job_id
    )
    ON CONFLICT (account_id, pay_date, ticker) DO UPDATE SET
        asset_id = EXCLUDED.asset_id,
        asset_name = EXCLUDED.asset_name,
        amount_krw = EXCLUDED.amount_krw,
        currency = EXCLUDED.currency,
        source_job_id = EXCLUDED.source_job_id,
        updated_at = now()
    """
)

#: 증권사 거래소 코드 캐시. 한 번 찾으면 다음 동기화에서 헛호출이 줄어든다.
_SET_EXCHANGE_CODE = text(
    "UPDATE assets SET broker_exchange_code = :code, updated_at = now() "
    "WHERE ticker = :ticker AND broker_exchange_code IS DISTINCT FROM :code"
)

#: ⚠️`assets` 에는 **보유 종목만** 있어서 판 종목의 코드는 거기 못 남는다
#:  (실측: SGOV 는 배당이 14건인데 코드가 안 남아 매번 세 거래소를 다시
#:  더듬었다). 티커별 표에 따로 남긴다 — alembic 0017.
_REMEMBER_EXCHANGE_CODE = text(
    "INSERT INTO broker_exchange_codes (ticker, code, source) "
    "VALUES (:ticker, :code, :source) "
    "ON CONFLICT (ticker) DO UPDATE SET "
    "  code = EXCLUDED.code, source = EXCLUDED.source, updated_at = now()"
)

_FIND_ASSET = text(
    "SELECT id FROM assets WHERE ticker = :ticker ORDER BY created_at LIMIT 1"
)


def _asset_id_for(conn, ticker, cache):
    """종목 마스터를 찾아 준다. 없으면 None — 이미 판 종목은 마스터가 없을 수 있다."""
    if ticker not in cache:
        cache[ticker] = conn.execute(_FIND_ASSET, {"ticker": ticker}).scalar()
    return cache[ticker]


def upsert_trades(conn, account_id, trades, source_job_id=None):
    cache: dict = {}
    for trade in trades:
        conn.execute(
            _TRADE_UPSERT,
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "asset_id": _asset_id_for(conn, trade.ticker, cache),
                "ticker": trade.ticker,
                "asset_name": trade.name,
                "trade_date": trade.trade_date,
                # 자연키라 비울 수 없다 — 안 준 행(옛 호출자)은 체결일과 같다고 본다.
                "settlement_date": trade.settlement_date or trade.trade_date,
                "trade_date_source": trade.trade_date_source,
                "trade_no": trade.trade_no,
                "market": trade.market,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": trade.price,
                "currency": trade.currency,
                "amount_local": trade.amount_local,
                "settlement_amount_local": trade.settlement_amount_local,
                "commission_local": trade.commission_local,
                "tax_local": trade.tax_local,
                "amount_krw": trade.amount_krw,
                "exchange": trade.exchange,
                "channel": trade.channel,
                "processed_at": trade.processed_at,
                "source_job_id": source_job_id,
            },
        )
    return len(trades)


#: 결제일이 주문일보다 이만큼 넘게 늦으면 짝으로 보지 않는다. 실측(2026-10-05,
#: 92건) 최대 4일(주말 낀 T+2) — 연휴 여유를 두고 10일.
_SETTLEMENT_LAG_MAX_DAYS = 10


def match_execution_dates(trades, orders) -> dict:
    """해외 체결 → 체결일(= 주문일). {trade.id: order_date} 로 돌려준다.

    ★왜: ust21100 의 deal_dt 는 결제일이다(alembic 0028). 주문 원장(ust21180)에는
      주문일이 있고 체결가·체결수량이 체결 원장과 그대로 같다(실측 92건).

    짝 조건 — 같은 종목·방향, 주문일 ≤ 결제일(10일 안), 체결가가 둘 다 있으면 같아야 한다.
      1) 체결수량 == 체결 수량인 주문 하나. 결제일에서 **가장 가까운 앞** 주문을 고른다.
      2) 없으면 같은 주문일의 주문들 합이 수량과 같을 때(증권사가 같은 날 같은 종목
         주문을 한 줄로 합쳐 결제한다 — 실측 EETH 2주+32주 → 34주 한 줄).
    ⚠️**일대일**로 쓴다. 쓴 주문을 다시 쓰면 같은 (종목, 수량)이 여러 번인 계좌에서
      (SCHD 10주 매수 6번) 엉뚱한 날짜가 붙는다. 결제일 순으로 짝짓는다.
    ⚠️못 찾은 체결은 결과에 없다 — 호출자가 결제일 그대로 두고 'settlement' 로 표시한다.
      앞 영업일로 미루는 식의 추측은 하지 않는다.
    """
    pool = [o for o in orders if (o.filled_quantity or 0) > 0]
    used: set[int] = set()
    resolved: dict = {}

    def fits(t, o) -> bool:
        if o.ticker != t.ticker or o.side != t.side:
            return False
        lag = (t.settlement_date - o.order_date).days
        if not 0 <= lag <= _SETTLEMENT_LAG_MAX_DAYS:
            return False
        return t.price is None or o.filled_price is None or o.filled_price == t.price

    ordered = sorted(trades, key=lambda t: (t.settlement_date, t.trade_no))
    for t in ordered:
        candidates = [
            i for i, o in enumerate(pool)
            if i not in used and fits(t, o) and o.filled_quantity == t.quantity
        ]
        if candidates:
            # 가장 늦은 주문일(= 결제일에 가장 가까운 앞), 같으면 주문번호 순.
            best = min(candidates, key=lambda i: (-pool[i].order_date.toordinal(),
                                                  pool[i].order_no))
            used.add(best)
            resolved[t.id] = pool[best].order_date

    for t in ordered:
        if t.id in resolved:
            continue
        by_date: dict = defaultdict(list)
        for i, o in enumerate(pool):
            if i not in used and fits(t, o):
                by_date[o.order_date].append(i)
        for order_date in sorted(by_date, reverse=True):
            group = by_date[order_date]
            if sum(pool[i].filled_quantity for i in group) == t.quantity:
                used.update(group)
                resolved[t.id] = order_date
                break
    return resolved


_US_TRADES_FOR_MATCH = text(
    "SELECT id, settlement_date, trade_no, ticker, side, quantity, price, "
    "       trade_date, trade_date_source "
    "FROM trades WHERE account_id = :acc AND market = 'US'"
)
_FILLED_ORDERS = text(
    "SELECT order_date, order_no, ticker, side, filled_quantity, filled_price "
    "FROM orders WHERE account_id = :acc AND coalesce(filled_quantity, 0) > 0"
)
_SET_TRADE_DATE = text(
    "UPDATE trades SET trade_date = :trade_date, trade_date_source = :source, "
    "  updated_at = now() WHERE id = :id"
)


def resolve_us_trade_dates(conn, account_id) -> dict[str, int]:
    """해외 체결의 체결일을 주문 원장으로 복원한다(alembic 0028). 계좌 전체를 매번 다시 짝짓는다.

    ★DB 에 쌓인 주문 원장을 쓴다 — 이번 동기화에서 주문 조회가 실패했거나 조회 창(3개월)
      밖의 옛 체결도 같은 결과가 나온다. 같은 데이터면 같은 답이라 몇 번 돌려도 같다.
    ⚠️자연키는 결제일이라 여기서 trade_date 를 바꿔도 행이 늘지 않는다.
    돌려주는 값: {"order": 짝지은 수, "settlement": 못 짝지어 결제일로 둔 수, "changed": 바뀐 행}.
    """
    trades = conn.execute(_US_TRADES_FOR_MATCH, {"acc": account_id}).all()
    orders = conn.execute(_FILLED_ORDERS, {"acc": account_id}).all()
    resolved = match_execution_dates(trades, orders)
    counts = {"order": 0, "settlement": 0, "changed": 0}
    for t in trades:
        if t.id in resolved:
            trade_date, source = resolved[t.id], "order"
        else:
            trade_date, source = t.settlement_date, "settlement"
        counts[source] += 1
        if (t.trade_date, t.trade_date_source) != (trade_date, source):
            conn.execute(
                _SET_TRADE_DATE, {"trade_date": trade_date, "source": source, "id": t.id}
            )
            counts["changed"] += 1
    return counts


def upsert_daily_performance(conn, account_id, rows, source_job_id=None):
    for row in rows:
        conn.execute(
            _PERF_UPSERT,
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "base_date": row.base_date,
                "deposit_assets_krw": row.deposit_assets_krw,
                "stock_value_krw": row.stock_value_krw,
                "pnl_krw": row.pnl_krw,
                "cumulative_pnl_krw": row.cumulative_pnl_krw,
                "dividend_krw": row.dividend_krw,
                "commission_tax_krw": row.commission_tax_krw,
                "buy_amount_krw": row.buy_amount_krw,
                "sell_amount_krw": row.sell_amount_krw,
                "deposit_krw": row.deposit_krw,
                "withdrawal_krw": row.withdrawal_krw,
                "return_rate": row.return_rate,
                "exchange_rate": row.exchange_rate,
                "source_job_id": source_job_id,
            },
        )
    return len(rows)


def upsert_realized_pnl(conn, account_id, rows, source_job_id=None):
    cache: dict = {}
    for row in rows:
        conn.execute(
            _REALIZED_UPSERT,
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "asset_id": _asset_id_for(conn, row.ticker, cache),
                "ticker": row.ticker,
                "asset_name": row.name,
                "sell_date": row.sell_date,
                "quantity": row.quantity,
                "currency": row.currency,
                "avg_buy_price": row.avg_buy_price,
                "avg_sell_price": row.avg_sell_price,
                "buy_amount_local": row.buy_amount_local,
                "sell_amount_local": row.sell_amount_local,
                "commission_tax_local": row.commission_tax_local,
                "pnl_local": row.pnl_local,
                "buy_amount_krw": row.buy_amount_krw,
                "sell_amount_krw": row.sell_amount_krw,
                "commission_tax_krw": row.commission_tax_krw,
                "pnl_krw": row.pnl_krw,
                "pnl_rate": row.pnl_rate,
                "buy_exchange_rate": row.buy_exchange_rate,
                "sell_exchange_rate": row.sell_exchange_rate,
                "fx_pnl_krw": row.fx_pnl_krw,
                "exchange": row.exchange,
                "source_job_id": source_job_id,
            },
        )
    return len(rows)


def upsert_dividends(conn, account_id, rows, source_job_id=None):
    """배당 적재 + 찾아낸 거래소 코드 캐시."""
    cache: dict = {}
    for row in rows:
        conn.execute(
            _DIVIDEND_UPSERT,
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "asset_id": _asset_id_for(conn, row.ticker, cache),
                "ticker": row.ticker,
                "asset_name": row.name,
                "pay_date": row.pay_date,
                "amount_krw": row.amount_krw,
                "currency": row.currency,
                "source_job_id": source_job_id,
            },
        )
    return len(rows)


def remember_exchange_codes(conn, rows, source: str = "dividend") -> int:
    """종목별 거래소 코드를 남긴다. 다음 조회에서 탐색을 건너뛴다.

    두 군데에 적는다.
      · `assets.broker_exchange_code` — 보유 종목 화면들이 이미 읽고 있다.
      · `broker_exchange_codes` — **판 종목까지** 남는 티커별 표(alembic 0017).

    ⚠️assets 에만 적으면 판 종목은 코드를 잃는다. 그러면 탐색을 "행이 온 코드만
      인정"으로 조일 수 없다 — 판 종목이 매번 '확인 못 함'으로 보고되기 때문이다.
    """
    seen = {}
    for row in rows:
        code = getattr(row, "broker_exchange_code", None)
        ticker = getattr(row, "ticker", None)
        if code and ticker and ticker not in seen:
            seen[ticker] = code
    for ticker, code in seen.items():
        conn.execute(_SET_EXCHANGE_CODE, {"code": code, "ticker": ticker})
        conn.execute(
            _REMEMBER_EXCHANGE_CODE,
            {"ticker": ticker, "code": code, "source": source},
        )
    return len(seen)


def remember_probed_codes(conn, codes: dict[str, str]) -> int:
    """더듬어 찾은 거래소 코드를 티커별 표에 남긴다.

    ⚠️`remember_exchange_codes` 는 **배당 행**에서 코드를 거둔다. 배당을 안 주는
      종목은 행이 없어 코드가 안 남고, 그래서 동기화마다 세 거래소를 다시
      더듬었다. 여기서는 배당 유무와 무관하게 남긴다.
    """
    for ticker, code in codes.items():
        if ticker and code:
            conn.execute(
                _REMEMBER_EXCHANGE_CODE,
                {"ticker": ticker, "code": code, "source": "probe"},
            )
    return len(codes)


def tickers_for_dividends(conn, account_id):
    """배당을 조회할 종목 목록 — 현재 보유 + 과거 체결 종목 전부.

    이미 판 종목도 그 해에 배당을 받았을 수 있다. 보유만 보면 이력이 빈다.
    """
    # ⚠️assets 에서만 뽑으면 **이미 판 종목이 빠진다** — assets 행은 보유 포지션에서만
    #   만들어지기 때문이다. 실측에서 SGOV(전량 매도)가 통째로 빠져 배당이 20건 중
    #   10건만 들어왔다. 체결 테이블에서 티커를 직접 모으고, 거래소 코드는 있으면 붙인다.
    #
    # ⚠️거래소 코드도 같은 이유로 **티커별 표**(alembic 0017)를 먼저 본다.
    #   assets 에만 적어 두면 판 종목은 코드를 잃어 매번 다시 더듬는다.
    #
    # ⚠️그래도 **한 번도 코드를 못 남긴 판 종목**은 영영 못 찾는다. 탐색은
    #   "최근 5일에 행이 온 코드만 인정"인데 판 종목은 최근 행이 없다 — 그래서
    #   SGOV·QLD·AVGO 등 7종목이 동기화마다 '확인 못 함'으로 보고됐다(실측
    #   2026-10-05, SGOV 는 배당 14건이 이미 있는데도). 표가 생기기(0017) 전에
    #   들어온 배당이라 코드가 안 남았다. 마지막 근거로 **실현손익의 거래소명**
    #   (ust21530 stex_nm)을 쓴다 — 체결·주문의 stex_nm 은 "미국"뿐이라 못 쓰지만
    #   실현손익은 거래소를 적어 준다. 실측에서 탐색으로 찾은 코드 7종목과 전부
    #   일치했다(나스닥→ND, 뉴욕증권거래소→NY; NYSE Arca 인 SOXL 도 NY).
    #   모르는 이름은 None 으로 두어 예전처럼 탐색에 맡긴다.
    rows = conn.execute(
        text(
            "WITH held AS ( "
            "  SELECT a.ticker FROM assets a "
            "  JOIN current_positions p ON p.asset_id = a.id AND p.account_id = :acc "
            "), traded AS ( "
            "  SELECT DISTINCT ticker FROM trades WHERE account_id = :acc "
            "), all_tickers AS ( "
            "  SELECT ticker FROM held UNION SELECT ticker FROM traded "
            "), realized AS ( "
            "  SELECT ticker, max(CASE trim(exchange) "
            "    WHEN '나스닥' THEN 'ND' WHEN '뉴욕증권거래소' THEN 'NY' END) AS code "
            "  FROM realized_pnl GROUP BY ticker "
            ") "
            "SELECT t.ticker, coalesce(c.code, max(a.broker_exchange_code), r.code) "
            "FROM all_tickers t "
            "LEFT JOIN assets a ON a.ticker = t.ticker "
            "LEFT JOIN broker_exchange_codes c ON c.ticker = t.ticker "
            "LEFT JOIN realized r ON r.ticker = t.ticker "
            "GROUP BY t.ticker, c.code, r.code ORDER BY t.ticker"
        ),
        {"acc": account_id},
    ).all()
    return [(r[0], r[1]) for r in rows]


_ORDER_UPSERT = text(
    """
    INSERT INTO orders (
        id, account_id, asset_id, ticker, asset_name, order_date, order_no,
        order_time, side, order_type, currency, order_quantity, filled_quantity,
        cancelled_quantity, modified_quantity, remaining_quantity, order_price,
        filled_price, stop_price, filled_amount, exchange, channel, reserve_type,
        source_job_id
    ) VALUES (
        :id, :account_id, :asset_id, :ticker, :asset_name, :order_date, :order_no,
        :order_time, :side, :order_type, :currency, :order_quantity, :filled_quantity,
        :cancelled_quantity, :modified_quantity, :remaining_quantity, :order_price,
        :filled_price, :stop_price, :filled_amount, :exchange, :channel, :reserve_type,
        :source_job_id
    )
    ON CONFLICT (account_id, order_date, order_no) DO UPDATE SET
        asset_id = EXCLUDED.asset_id,
        ticker = EXCLUDED.ticker,
        asset_name = EXCLUDED.asset_name,
        order_time = EXCLUDED.order_time,
        side = EXCLUDED.side,
        order_type = EXCLUDED.order_type,
        currency = EXCLUDED.currency,
        order_quantity = EXCLUDED.order_quantity,
        filled_quantity = EXCLUDED.filled_quantity,
        cancelled_quantity = EXCLUDED.cancelled_quantity,
        modified_quantity = EXCLUDED.modified_quantity,
        remaining_quantity = EXCLUDED.remaining_quantity,
        order_price = EXCLUDED.order_price,
        filled_price = EXCLUDED.filled_price,
        stop_price = EXCLUDED.stop_price,
        filled_amount = EXCLUDED.filled_amount,
        exchange = EXCLUDED.exchange,
        channel = EXCLUDED.channel,
        reserve_type = EXCLUDED.reserve_type,
        source_job_id = EXCLUDED.source_job_id,
        updated_at = now()
    """
)


def upsert_orders(conn, account_id, orders, source_job_id=None):
    """주문 내역 적재.

    ⚠️덮어쓰기여야 한다. 주문 상태(체결수량·취소수량·잔량)는 **사후에 바뀐다** —
      오늘 미체결이던 주문이 내일 체결될 수 있다. 같은 주문번호는 최신 값으로.
    ⚠️asset_id 는 없을 수 있다. 한 번도 체결된 적 없는 종목은 assets 행이 없다
      (실측: SKHYV 는 주문 3건 전부 미체결이라 assets 에 없다).
    """
    cache: dict = {}
    for order in orders:
        conn.execute(
            _ORDER_UPSERT,
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "asset_id": _asset_id_for(conn, order.ticker, cache),
                "ticker": order.ticker,
                "asset_name": order.name,
                "order_date": order.order_date,
                "order_no": order.order_no,
                "order_time": order.order_time,
                "side": order.side,
                "order_type": order.order_type,
                "currency": order.currency,
                "order_quantity": order.order_quantity,
                "filled_quantity": order.filled_quantity,
                "cancelled_quantity": order.cancelled_quantity,
                "modified_quantity": order.modified_quantity,
                "remaining_quantity": order.remaining_quantity,
                "order_price": order.order_price,
                "filled_price": order.filled_price,
                "stop_price": order.stop_price,
                "filled_amount": order.filled_amount,
                "exchange": order.exchange,
                "channel": order.channel,
                "reserve_type": order.reserve_type,
                "source_job_id": source_job_id,
            },
        )
    return len(orders)

