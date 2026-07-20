"""iNAV computation engine.

Separates three data lifecycles:
- Static (PDF, ETF meta, market): set once per day at __init__
- Refreshable (FX rates): set via set_fx_rates(), expected to update on a minute-ish cadence
- Live (per-symbol prices): set via update_price()/update_price_by_key(), per-tick

Pre-merges the static PDF with KIS instrument mappings so per-tick work is
limited to small vectorized multiplications.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


SETTING_CASH_CODE = "CASH00000001"
KRW_CASH_CODE = "KRD010010001"
INAV_DIVISOR = 50000.0

_KST = timezone(timedelta(hours=9))


def _now_kst_hhmmss() -> str:
    return datetime.now(_KST).strftime("%H:%M:%S")


def _is_positive_number(value) -> bool:
    if value is None:
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _as_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_numeric(series) -> pd.Series:
    """Coerce to numeric, stripping thousands separators and percent signs.

    KRX JSON fields arrive as strings like "50,000" or "39,774.64"; plain
    pd.to_numeric would turn those into NaN.
    """
    if not isinstance(series, pd.Series):
        series = pd.Series(series)
    if series.dtype == object:
        series = (
            series.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
    return pd.to_numeric(series, errors="coerce")


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def _normalize_ticker(value) -> str:
    text = "" if value is None else str(value).strip().upper()
    if not text:
        return ""
    return text.replace(".KS", "").split()[0]


def _prepare_etf_meta(etf_list_df: pd.DataFrame | None) -> pd.DataFrame:
    if etf_list_df is None or etf_list_df.empty:
        return pd.DataFrame(columns=["ETF_TICKER", "CU_QTY", "LIST_SHRS", "ETF_LIST_NAME"])

    df = etf_list_df.copy()
    ticker_col = _first_existing_column(df, ["ETF_TICKER", "ISU_SRT_CD", "ticker"])
    name_col = _first_existing_column(df, ["ISU_ABBRV", "ETF_NAME", "ISU_NM"])
    if ticker_col is None:
        return pd.DataFrame(columns=["ETF_TICKER", "CU_QTY", "LIST_SHRS", "ETF_LIST_NAME"])

    out = pd.DataFrame()
    out["ETF_TICKER"] = df[ticker_col].map(_normalize_ticker)
    out["CU_QTY"] = _to_numeric(df["CU_QTY"]) if "CU_QTY" in df.columns else None
    out["LIST_SHRS"] = _to_numeric(df["LIST_SHRS"]) if "LIST_SHRS" in df.columns else None
    out["ETF_LIST_NAME"] = df[name_col] if name_col else ""
    return out.drop_duplicates("ETF_TICKER")


def _normalize_market(market_df: pd.DataFrame | None) -> pd.DataFrame:
    if market_df is None or market_df.empty:
        return pd.DataFrame(columns=["ETF_TICKER", "kr_etf_price", "krx_nav"])

    ticker_col = _first_existing_column(market_df, ["ETF_TICKER", "ISU_SRT_CD", "ticker", "Ticker"])
    price_col = _first_existing_column(market_df, ["kr_etf_price", "TDD_CLSPRC", "CLSPRC", "close", "price"])
    nav_col = _first_existing_column(market_df, ["krx_nav", "NAV", "LST_NAV"])
    if ticker_col is None or price_col is None:
        return pd.DataFrame(columns=["ETF_TICKER", "kr_etf_price", "krx_nav"])

    out = pd.DataFrame()
    out["ETF_TICKER"] = market_df[ticker_col].map(_normalize_ticker)
    out["kr_etf_price"] = _to_numeric(market_df[price_col])
    out["krx_nav"] = _to_numeric(market_df[nav_col]) if nav_col else None
    return out.drop_duplicates("ETF_TICKER")


SUMMARY_COLUMNS = [
    "ETF_TICKER",
    "ETF_NAME",
    "kr_etf_price",
    "inav_per_share",
    "component_count",
    "price_candidate_count",
    "priced_component_count",
]

SUMMARY_SORT_COLUMNS = ["deviation_pct", "ETF_TICKER"]


class InavEngine:
    """Pre-merges static PDF state and applies live prices + current FX on demand."""

    def __init__(
        self,
        prepared_pdf: pd.DataFrame,
        etf_list_df: pd.DataFrame | None,
        market_df: pd.DataFrame | None = None,
        instruments: list[dict] | None = None,
    ):
        self._etf_meta = _prepare_etf_meta(etf_list_df)
        self._market = _normalize_market(market_df)
        self._base = self._build_base(prepared_pdf, instruments or [])
        self._fx_rates: dict[str, float] = {"KRW": 1.0}
        self._prices: dict[str, dict] = {}
        self._closed_exchanges: set[str] = set()
        self._key_to_isin = self._index_keys(self._base)

    @staticmethod
    def _index_keys(base: pd.DataFrame) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        for row in base[["component_isin", "kis_exchange", "kis_symbol"]].itertuples(index=False):
            isin = (row.component_isin or "").upper()
            exchange = (row.kis_exchange or "").upper()
            symbol = (row.kis_symbol or "").upper()
            if isin and exchange and symbol:
                out[(exchange, symbol)] = isin
        return out

    def _build_base(self, pdf_df: pd.DataFrame, instruments: list[dict]) -> pd.DataFrame:
        df = pdf_df.copy()
        df["component_code"] = (
            df["COMPST_ISU_CD2"].fillna("").astype(str).str.strip().str.upper()
        )
        missing_code = df["component_code"].eq("")
        df.loc[missing_code, "component_code"] = (
            df.loc[missing_code, "COMPST_ISU_CD"].fillna("").astype(str).str.strip().str.upper()
        )
        df["is_setting_cash"] = df["component_code"].eq(SETTING_CASH_CODE)
        df["is_krw_cash"] = df["component_code"].eq(KRW_CASH_CODE)

        if "quantity" not in df.columns:
            df["quantity"] = df.get("COMPST_ISU_CU1_SHRS")
        df["quantity"] = _to_numeric(df["quantity"])

        if "reference_value_krw" not in df.columns:
            df["reference_value_krw"] = None
        df["reference_value_krw"] = _to_numeric(df["reference_value_krw"])

        if instruments:
            inst_df = pd.DataFrame(instruments).rename(
                columns={
                    "isin": "component_isin",
                    "ticker": "kis_symbol",
                    "exchange": "kis_exchange",
                    "currency": "kis_currency",
                }
            )
            inst_df = inst_df[["component_isin", "kis_symbol", "kis_exchange", "kis_currency"]]
            inst_df["component_isin"] = inst_df["component_isin"].astype(str).str.upper()
            df = df.merge(inst_df, on="component_isin", how="left")
        else:
            for column in ("kis_symbol", "kis_exchange", "kis_currency"):
                df[column] = ""

        for column in ("kis_symbol", "kis_exchange", "kis_currency"):
            df[column] = df[column].fillna("").astype(str).str.upper()
        return df

    @property
    def fx_rates(self) -> dict[str, float]:
        return dict(self._fx_rates)

    def set_closed_exchanges(self, exchanges) -> None:
        """KIS exchange codes whose market is 휴장 today.

        Components on these exchanges are excluded from the live-priced set so
        they fall back to their base price (전일 종가) instead of a stale live
        tick that the closed market keeps echoing.
        """
        self._closed_exchanges = {str(code).upper() for code in (exchanges or set())}

    def set_fx_rates(self, fx_table) -> None:
        rates = fx_table
        if isinstance(fx_table, dict) and "rates" in fx_table:
            rates = fx_table["rates"]
        merged = dict(rates or {})
        merged.setdefault("KRW", 1.0)
        self._fx_rates = merged

    def update_price(self, isin: str, snapshot: dict) -> None:
        if not isin:
            return
        self._merge_snapshot(isin.upper(), snapshot)

    def update_price_by_key(self, exchange: str, symbol: str, snapshot: dict) -> str | None:
        isin = self._key_to_isin.get((exchange.upper(), symbol.upper()))
        if isin is None:
            return None
        self._merge_snapshot(isin, snapshot)
        return isin

    def _merge_snapshot(self, isin: str, snapshot: dict) -> None:
        """Merge a new snapshot into _prices, preserving prior numeric fields
        when the new value is missing/zero. Guards against transient zeros
        (halts, between-trade gaps, post-close REST returning 0) that would
        otherwise wipe a valid price and cause iNAV spikes.

        Stamps ``received_at`` only when ``last`` actually changes (first
        receipt, or a different value from before). Unchanged repeat
        snapshots from batch polling keep their prior stamp so the UI
        reflects each symbol's last *price change*, not the polling
        cadence. A snapshot that already carries ``received_at`` (e.g.
        a price carried forward across a PDF rebuild) keeps that stamp.
        """
        new_last = _as_float_or_none(snapshot.get("last"))
        last_in_snap = new_last is not None and new_last > 0
        incoming_received_at = snapshot.get("received_at")
        existing = self._prices.get(isin)
        if not existing:
            new = dict(snapshot)
            if last_in_snap and not incoming_received_at:
                new["received_at"] = _now_kst_hhmmss()
            self._prices[isin] = new
            return
        existing_last = _as_float_or_none(existing.get("last"))
        price_changed = last_in_snap and (existing_last is None or existing_last != new_last)
        merged = dict(existing)
        for key, value in snapshot.items():
            if key in ("last", "base"):
                if value is None:
                    continue
                try:
                    if float(value) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
            merged[key] = value
        if price_changed and not incoming_received_at:
            merged["received_at"] = _now_kst_hhmmss()
        self._prices[isin] = merged

    def update_last_by_key(
        self,
        exchange: str,
        symbol: str,
        last: float | None,
        extra: dict | None = None,
    ) -> str | None:
        """Merge a live ``last`` (and optional fields) into an existing snapshot.

        ``base`` and ``currency`` from the initial REST snapshot are preserved;
        WebSocket ticks only carry the latest traded price. Transient zero/None
        ticks (halts, between-trade gaps) are ignored so the last known price
        survives.
        """
        isin = self._key_to_isin.get((exchange.upper(), symbol.upper()))
        if isin is None:
            return None
        snap = self._prices.get(isin)
        if snap is None:
            snap = {"exchange": exchange.upper(), "symbol": symbol.upper()}
            self._prices[isin] = snap
        existing_last = _as_float_or_none(snap.get("last"))
        price_changed = False
        if last is not None:
            try:
                new_last_value = float(last)
                if new_last_value > 0:
                    snap["last"] = last
                    if existing_last is None or existing_last != new_last_value:
                        price_changed = True
            except (TypeError, ValueError):
                pass
        if extra:
            snap.update(extra)
        if price_changed:
            snap["received_at"] = _now_kst_hhmmss()
        return isin

    def bulk_update_from_snapshots(self, snapshots: list[dict]) -> int:
        count = 0
        for snap in snapshots:
            exchange = (snap.get("exchange") or "").upper()
            symbol = (snap.get("symbol") or "").upper()
            if not exchange or not symbol:
                continue
            if self.update_price_by_key(exchange, symbol, snap) is not None:
                count += 1
        return count

    def update_prices_from_df(self, price_df: pd.DataFrame) -> int:
        """Load prices from a DataFrame keyed by ISIN (batch/CSV path)."""
        if price_df is None or price_df.empty or "ISIN" not in price_df.columns:
            return 0

        def first_value(row: dict, names: list[str]):
            for name in names:
                value = row.get(name)
                if value not in (None, ""):
                    return value
            return None

        count = 0
        now_hhmmss = _now_kst_hhmmss()
        for row in price_df.to_dict("records"):
            isin = str(row.get("ISIN") or "").upper()
            if not isin:
                continue
            last_value = first_value(row, ["live_price", "price", "live_price_local", "live_price_usd"])
            entry = {
                "last": last_value,
                "base": first_value(row, ["base_price", "base_price_local", "base_price_usd"]),
                "currency": str(row.get("currency") or "").upper() or None,
            }
            if _is_positive_number(last_value):
                entry["received_at"] = now_hhmmss
            self._prices[isin] = entry
            count += 1
        return count

    def latest_prices(self) -> dict[str, dict]:
        return dict(self._prices)

    def compute(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        df = self._base.copy()

        df["live_price"] = df["component_isin"].map(
            lambda isin: (self._prices.get((isin or "").upper()) or {}).get("last")
        )
        df["base_price"] = df["component_isin"].map(
            lambda isin: (self._prices.get((isin or "").upper()) or {}).get("base")
        )
        df["live_price"] = _to_numeric(df["live_price"])
        df["base_price"] = _to_numeric(df["base_price"])

        # Currency precedence: price snapshot's own currency, then KIS master.
        price_currency = df["component_isin"].map(
            lambda isin: (self._prices.get((isin or "").upper()) or {}).get("currency")
        )
        master_currency = (
            df["kis_currency"] if "kis_currency" in df.columns else pd.Series("", index=df.index)
        )
        missing_currency = {"": pd.NA, "NAN": pd.NA, "NONE": pd.NA, "<NA>": pd.NA}
        price_currency = (
            price_currency.fillna("").astype(str).str.strip().str.upper().replace(missing_currency)
        )
        master_currency = (
            master_currency.fillna("").astype(str).str.strip().str.upper().replace(missing_currency)
        )
        df["currency"] = price_currency.fillna(master_currency).fillna("")
        df["fx_rate"] = df["currency"].map(lambda c: self._fx_rates.get(c) if c else None)
        df["fx_rate"] = _to_numeric(df["fx_rate"])

        df["live_value_krw"] = pd.NA
        df["base_value_krw"] = pd.NA
        df["price_delta_krw"] = pd.NA
        df["value_source"] = "unpriced_no_price"
        df["row_type"] = "unpriced_component"
        df.loc[df["is_setting_cash"], "row_type"] = "setting_cash_anchor"
        df.loc[df["is_setting_cash"], "value_source"] = "setting_cash_anchor"
        df.loc[df["is_krw_cash"], "row_type"] = "krw_cash"
        df.loc[df["is_krw_cash"], "value_source"] = "krw_cash"
        df.loc[df["is_setting_cash"] | df["is_krw_cash"], "live_value_krw"] = df.loc[
            df["is_setting_cash"] | df["is_krw_cash"], "reference_value_krw"
        ]
        df.loc[df["is_setting_cash"] | df["is_krw_cash"], "base_value_krw"] = df.loc[
            df["is_setting_cash"] | df["is_krw_cash"], "reference_value_krw"
        ]

        security_component = ~df["is_setting_cash"] & ~df["is_krw_cash"]
        # KOSPI single-stock futures: 1 contract = 10 shares of underlying.
        # KIS quotes price per share, so notional = qty × price × fx × 10.
        multiplier = pd.Series(1.0, index=df.index)
        multiplier.loc[df["kis_exchange"].eq("KFO")] = 10.0
        # Holiday markets keep echoing a stale live tick; exclude them from the
        # live-priced set so they fall through to base_fallback (전일 종가).
        closed_mask = (
            df["kis_exchange"].isin(self._closed_exchanges)
            if self._closed_exchanges
            else pd.Series(False, index=df.index)
        )
        priced = (
            security_component
            & df["quantity"].notna()
            & df["live_price"].notna()
            & df["fx_rate"].notna()
            & (df["live_price"] > 0)
            & (df["fx_rate"] > 0)
            & ~closed_mask
        )
        df.loc[priced, "live_value_krw"] = (
            df.loc[priced, "quantity"]
            * df.loc[priced, "live_price"]
            * df.loc[priced, "fx_rate"]
            * multiplier.loc[priced]
        )

        base_priced = (
            security_component
            & df["quantity"].notna()
            & df["base_price"].notna()
            & df["fx_rate"].notna()
            & (df["base_price"] > 0)
            & (df["fx_rate"] > 0)
        )
        df.loc[base_priced, "base_value_krw"] = (
            df.loc[base_priced, "quantity"]
            * df.loc[base_priced, "base_price"]
            * df.loc[base_priced, "fx_rate"]
            * multiplier.loc[base_priced]
        )
        has_delta = priced & base_priced
        df.loc[has_delta, "price_delta_krw"] = (
            df.loc[has_delta, "live_value_krw"] - df.loc[has_delta, "base_value_krw"]
        )
        # When live tick is unavailable (e.g., off-hours overseas markets),
        # fall back to base_price so the row still contributes to iNAV.
        # is_price_updated stays False so 'priced_component_count' keeps its
        # live-only meaning; _summarize widens the iNAV total to include these.
        base_fallback = base_priced & ~priced
        df.loc[base_fallback, "live_value_krw"] = df.loc[base_fallback, "base_value_krw"]
        df.loc[base_fallback, "value_source"] = "base_fallback"
        df.loc[base_fallback, "row_type"] = "base_fallback_component"
        df.loc[priced, "value_source"] = "qty_price_fx"
        df.loc[priced, "row_type"] = "priced_component"
        for column in ("live_value_krw", "base_value_krw", "price_delta_krw"):
            df[column] = _to_numeric(df[column])
        df["is_price_updated"] = df["value_source"].eq("qty_price_fx")
        return df, self._summarize(df)

    def _summarize(self, components: pd.DataFrame) -> pd.DataFrame:
        def add_cash(cash_total, component_total):
            cash_missing = pd.isna(cash_total)
            component_missing = pd.isna(component_total)
            if cash_missing and component_missing:
                return pd.NA
            return (0.0 if cash_missing else cash_total) + (
                0.0 if component_missing else component_total
            )

        rows: list[dict] = []
        for ticker, group in components.groupby("ETF_TICKER", dropna=False):
            security_mask = ~group["is_setting_cash"] & ~group["is_krw_cash"]
            priced_mask = group["is_price_updated"]
            fallback_mask = group["value_source"].eq("base_fallback")
            inav_mask = priced_mask | fallback_mask
            cash_total = group.loc[group["is_krw_cash"], "live_value_krw"].sum(min_count=1)
            # Futures are marked-to-market daily; their NAV contribution is only
            # the live-vs-base PnL, not the full notional. Stocks use live_value
            # directly. base_nav excludes futures since PnL is 0 at the reference.
            kfo_grp = group["kis_exchange"].eq("KFO")
            inav_security_value = add_cash(
                group.loc[inav_mask & ~kfo_grp, "live_value_krw"].sum(min_count=1),
                group.loc[inav_mask & kfo_grp, "price_delta_krw"].sum(min_count=1),
            )
            inav_security_base = group.loc[inav_mask & ~kfo_grp, "base_value_krw"].sum(min_count=1)
            priced_value = add_cash(
                group.loc[priced_mask & ~kfo_grp, "live_value_krw"].sum(min_count=1),
                group.loc[priced_mask & kfo_grp, "price_delta_krw"].sum(min_count=1),
            )
            rows.append(
                {
                    "ETF_TICKER": ticker,
                    "ETF_NAME": group["ETF_NAME"].dropna().iloc[0] if group["ETF_NAME"].dropna().size else "",
                    "component_count": int(len(group)),
                    "price_candidate_count": int(group["is_price_candidate"].sum())
                    if "is_price_candidate" in group.columns
                    else 0,
                    "priced_component_count": int(priced_mask.sum()),
                    "unpriced_component_count": int((security_mask & ~inav_mask).sum()),
                    "inav_total_krw": add_cash(cash_total, inav_security_value),
                    "base_nav_total_krw": add_cash(cash_total, inav_security_base),
                    "cash_total_krw": cash_total,
                    "price_delta_total_krw": group.loc[priced_mask, "price_delta_krw"].sum(min_count=1),
                    "setting_cash_total_krw": group.loc[group["is_setting_cash"], "reference_value_krw"].sum(min_count=1),
                    "priced_value_krw": priced_value,
                }
            )

        summary = pd.DataFrame(rows)
        summary = summary.merge(self._etf_meta, on="ETF_TICKER", how="left")
        summary = summary.merge(self._market, on="ETF_TICKER", how="left")

        for column in (
            "CU_QTY",
            "krx_nav",
            "inav_total_krw",
            "base_nav_total_krw",
            "cash_total_krw",
            "setting_cash_total_krw",
            "price_delta_total_krw",
            "priced_value_krw",
        ):
            if column not in summary.columns:
                summary[column] = None
            summary[column] = _to_numeric(summary[column])

        summary["nav_divisor"] = INAV_DIVISOR
        summary["krx_nav_total_krw"] = summary["krx_nav"] * summary["CU_QTY"]
        summary["inav_per_share"] = summary["inav_total_krw"] / INAV_DIVISOR
        summary["base_nav_per_share"] = summary["base_nav_total_krw"] / INAV_DIVISOR
        summary["setting_cash_per_share"] = summary["setting_cash_total_krw"] / INAV_DIVISOR
        summary["priced_weight_pct"] = summary["priced_value_krw"] / summary["inav_total_krw"] * 100
        summary["inav_change_pct"] = (
            summary["inav_per_share"] / summary["base_nav_per_share"] - 1
        ) * 100
        summary["deviation_pct"] = (
            summary["kr_etf_price"] / summary["inav_per_share"] - 1
        ) * 100
        summary["anchor_diff_pct"] = (
            (summary["inav_total_krw"] - summary["setting_cash_total_krw"])
            / summary["setting_cash_total_krw"]
            * 100
        )

        for column in SUMMARY_COLUMNS:
            if column not in summary.columns:
                summary[column] = None
        sort_columns = [column for column in SUMMARY_SORT_COLUMNS if column in summary.columns]
        if sort_columns:
            summary = summary.sort_values(sort_columns, na_position="last")
        return summary[SUMMARY_COLUMNS]
