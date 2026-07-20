"""KRX PDF preparation helpers.

These functions are copied VERBATIM from the legacy
``etf_inav/workflows/batch.py`` so the PDF→engine transform stays byte-parity
with production (the requirements.txt pandas pin exists for exactly this
replay parity). They live here instead of importing ``batch`` because that
module imports ``etf_inav.data_sources.holiday_calendar`` (not part of the
copied Phase-1 subset) and computes ``parents[5]`` at import; the collector
only needs these pure, dependency-light transforms.

Do not "improve" this file — keep it identical to the legacy source.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd

from etf_inav.core.engine import KRW_CASH_CODE, SETTING_CASH_CODE

KST = timezone(timedelta(hours=9))

DEFAULT_PRICE_ISIN_PREFIXES = "ALL"
CASH_COMPONENT_CODES = {SETTING_CASH_CODE, KRW_CASH_CODE}

PDF_COLUMNS = [
    "COMPST_ISU_CD",
    "COMPST_ISU_CD2",
    "MKT_ID",
    "SECUGRP_ID",
    "COMPST_ISU_NM",
    "COMPST_ISU_CU1_SHRS",
    "VALU_AMT",
    "COMPST_AMT",
    "COMPST_RTO",
]


def now_kst_string() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def load_csv(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def normalize_ticker(value) -> str:
    text = "" if value is None else str(value).strip().upper()
    if not text:
        return ""
    return text.replace(".KS", "").split()[0]


def parse_ticker_list(value: str | None) -> list[str]:
    if not value:
        return []
    if value.strip().upper() == "ALL":
        return []
    return [normalize_ticker(item) for item in value.split(",") if normalize_ticker(item)]


def config_tickers(config: dict) -> list[str]:
    values = (
        config.get("target_etf_tickers")
        or config.get("tickers")
        or config.get("etf_tickers")
        or []
    )
    if isinstance(values, str):
        return parse_ticker_list(values)
    return [normalize_ticker(value) for value in values if normalize_ticker(value)]


def parse_prefixes(value: str | None) -> set[str]:
    if value is None:
        value = DEFAULT_PRICE_ISIN_PREFIXES
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def to_number(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text in ("", "-", "nan", "None"):
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def first_number(*values) -> float | None:
    for value in values:
        number = to_number(value)
        if number is not None:
            return number
    return None


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def is_valid_isin(value) -> bool:
    code = "" if value is None else str(value).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", code):
        return False

    digits = ""
    for char in code:
        if char.isdigit():
            digits += char
        elif char.isalpha():
            digits += str(ord(char) - 55)
        else:
            return False

    total = 0
    for idx, digit in enumerate(reversed(digits)):
        number = int(digit)
        if idx % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return total % 10 == 0


def component_isin(row: pd.Series) -> str:
    for column in ("COMPST_ISU_CD2", "COMPST_ISU_CD"):
        value = str(row.get(column, "")).strip().upper()
        if is_valid_isin(value):
            return value
    return ""


def is_price_candidate_isin(isin: str, prefixes: set[str]) -> bool:
    if not isin or not is_valid_isin(isin):
        return False
    if not prefixes or "ALL" in prefixes:
        return True
    return isin[:2].upper() in prefixes


def prepare_pdf_df(pdf_df: pd.DataFrame, prefixes: set[str]) -> pd.DataFrame:
    df = pdf_df.copy()
    for column in ["ETF_DATE", "ETF_ISU_CD", "ETF_TICKER", "ETF_NAME"]:
        if column not in df.columns:
            df[column] = ""

    for column in PDF_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df["ETF_TICKER"] = df["ETF_TICKER"].map(normalize_ticker)
    df["component_code"] = (
        df["COMPST_ISU_CD2"].fillna("").astype(str).str.strip().str.upper()
    )
    missing_code = df["component_code"].eq("")
    df.loc[missing_code, "component_code"] = (
        df.loc[missing_code, "COMPST_ISU_CD"].fillna("").astype(str).str.strip().str.upper()
    )
    df["is_cash_component"] = df["component_code"].isin(CASH_COMPONENT_CODES)
    df["component_isin"] = df.apply(component_isin, axis=1)
    df["is_price_candidate"] = (
        ~df["is_cash_component"]
        & df["component_isin"].map(lambda value: is_price_candidate_isin(value, prefixes))
    )
    df["quantity"] = df["COMPST_ISU_CU1_SHRS"].map(to_number)
    df["valu_amt_krw"] = df["VALU_AMT"].map(to_number)
    df["compst_amt_krw"] = df["COMPST_AMT"].map(to_number)
    df["component_ratio_pct"] = df["COMPST_RTO"].map(to_number)
    df["reference_value_krw"] = [
        first_number(valu_amt, compst_amt)
        for valu_amt, compst_amt in zip(df["VALU_AMT"], df["COMPST_AMT"])
    ]
    return df


def _first_component_symbol(group: pd.DataFrame, isin: str) -> str:
    for column in ("COMPST_ISU_CD", "component_code"):
        if column not in group.columns:
            continue
        for value in group[column].dropna().tolist():
            text = str(value).strip().upper()
            if re.fullmatch(r"[A-Z0-9]{6}", text) and text != isin:
                return text

    if isin.startswith("KR") and len(isin) >= 9:
        derived = isin[3:9].upper()
        if re.fullmatch(r"[A-Z0-9]{6}", derived):
            return derived
    return ""


def build_component_stock_rows(prepared_pdf: pd.DataFrame) -> list[dict[str, str]]:
    if prepared_pdf is None or prepared_pdf.empty:
        return []

    candidates = prepared_pdf[
        prepared_pdf["is_price_candidate"] & prepared_pdf["component_isin"].astype(bool)
    ].copy()
    rows: list[dict[str, str]] = []
    for isin, group in candidates.groupby("component_isin", dropna=False):
        isin_text = str(isin or "").upper()
        if not isin_text:
            continue
        rows.append(
            {
                "ISIN": isin_text,
                "ticker": _first_component_symbol(group, isin_text),
                "MKT_ID": group["MKT_ID"].dropna().iloc[0] if "MKT_ID" in group.columns and group["MKT_ID"].dropna().size else "",
                "SECUGRP_ID": group["SECUGRP_ID"].dropna().iloc[0] if "SECUGRP_ID" in group.columns and group["SECUGRP_ID"].dropna().size else "",
                "name": group["COMPST_ISU_NM"].dropna().iloc[0] if "COMPST_ISU_NM" in group.columns and group["COMPST_ISU_NM"].dropna().size else "",
            }
        )
    return rows


def filter_inputs_by_ticker(
    pdf_df: pd.DataFrame,
    etf_list_df: pd.DataFrame,
    market_df: pd.DataFrame | None,
    tickers: list[str],
    max_etfs: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    if not tickers and max_etfs is None:
        return pdf_df, etf_list_df, market_df

    selected = tickers
    if not selected and max_etfs is not None and etf_list_df is not None and not etf_list_df.empty:
        ticker_col = first_existing_column(etf_list_df, ["ETF_TICKER", "ISU_SRT_CD", "ticker"])
        if ticker_col:
            selected = etf_list_df[ticker_col].map(normalize_ticker).dropna().drop_duplicates().head(max_etfs).tolist()
    if not selected and max_etfs is not None and pdf_df is not None and not pdf_df.empty:
        selected = pdf_df["ETF_TICKER"].map(normalize_ticker).dropna().drop_duplicates().head(max_etfs).tolist()
    if not selected:
        return pdf_df, etf_list_df, market_df

    ticker_set = set(selected)
    pdf_out = pdf_df.copy()
    if "ETF_TICKER" in pdf_out.columns:
        pdf_out = pdf_out[pdf_out["ETF_TICKER"].map(normalize_ticker).isin(ticker_set)].copy()

    etf_out = etf_list_df.copy() if etf_list_df is not None else pd.DataFrame()
    ticker_col = first_existing_column(etf_out, ["ETF_TICKER", "ISU_SRT_CD", "ticker"])
    if ticker_col:
        etf_out = etf_out[etf_out[ticker_col].map(normalize_ticker).isin(ticker_set)].copy()

    market_out = market_df
    if market_df is not None and not market_df.empty:
        ticker_col = first_existing_column(market_df, ["ETF_TICKER", "ISU_SRT_CD", "ticker", "Ticker"])
        if ticker_col:
            market_out = market_df[market_df[ticker_col].map(normalize_ticker).isin(ticker_set)].copy()
    return pdf_out, etf_out, market_out
