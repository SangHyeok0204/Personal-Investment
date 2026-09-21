"""체결·일별성과·실현손익 적재 (alembic 0007·0008).

전부 **덮어쓰기(upsert)** 다. 같은 기간을 다시 조회해도 행이 늘지 않아야 한다 —
증권사가 값을 사후 정정하는 경우(예: 정산 확정)가 있어 최신 값으로 갱신되어야 하고,
동기화를 두 번 돌렸다고 체결이 두 배로 보이면 안 된다.

자연키는 실측으로 정한 것들이다(api_guide.md §2 참고):
  trades                     (account_id, trade_date, trade_no)  ← trade_no 는 일자별 리셋
  account_daily_performance  (account_id, base_date)
  realized_pnl               (account_id, sell_date, ticker)     ← 증권사가 매도일×종목 집계
"""
import uuid

from sqlalchemy import text

_TRADE_UPSERT = text(
    """
    INSERT INTO trades (
        id, account_id, asset_id, ticker, asset_name, trade_date, trade_no, side,
        quantity, price, currency, amount_local, settlement_amount_local,
        commission_local, tax_local, amount_krw, exchange, channel, processed_at,
        source_job_id
    ) VALUES (
        :id, :account_id, :asset_id, :ticker, :asset_name, :trade_date, :trade_no, :side,
        :quantity, :price, :currency, :amount_local, :settlement_amount_local,
        :commission_local, :tax_local, :amount_krw, :exchange, :channel, :processed_at,
        :source_job_id
    )
    ON CONFLICT (account_id, trade_date, trade_no) DO UPDATE SET
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
                "trade_no": trade.trade_no,
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
