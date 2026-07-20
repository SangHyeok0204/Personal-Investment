from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import date as dt_date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import urllib3
from cryptography.fernet import Fernet
from dotenv import load_dotenv

from etf_inav.core.engine import InavEngine, KRW_CASH_CODE, SETTING_CASH_CODE
from etf_inav.data_sources import holiday_calendar
from etf_inav.data_sources.kis_prices import resolve_instruments
from etf_inav.data_sources.naver_fx import fetch_fx_table
from etf_inav.data_sources.twse_prices import (
    SUPPORTED_EXCHANGES as TAIWAN_EXCHANGES,
    fetch_twse_prices,
    is_twse_trading_hours,
)
from kis_api.auth import KisAuth, KisCredentials
from kis_api.master import KisMaster
from kis_api.rest_client import KisRestClient
from kis_api.store import KisStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NEW_ROOT = Path(__file__).resolve().parents[5]
VAULT_ENV = NEW_ROOT / "data" / "_비밀값(중요)" / ".env"
load_dotenv(VAULT_ENV)

KST = timezone(timedelta(hours=9))
KST_DATE_FORMAT = "%Y%m%d"
KRX_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_LOGIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
KRX_LOGIN_JSP_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_MAIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"
KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}
DEFAULT_PRICE_ISIN_PREFIXES = "ALL"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "etf_inav_config.json"
DEFAULT_OUTPUT_DIR = NEW_ROOT / "data" / "ETF_iNAV모니터" / "output" / "results" / "etf_inav"
DEFAULT_KRX_CACHE_DIR = NEW_ROOT / "data" / "ETF_iNAV모니터" / "cache" / "krx"
MAX_WORKERS = 5
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

COMPONENT_PRICE_COLUMNS = [
    "ISIN",
    "ticker",
    "exchange",
    "price_exchange",
    "price_session",
    "currency",
    "base_price",
    "live_price",
    "trade_time",
    "korea_time",
    "rsym",
    "rec_time",
]

REQUIRED_PRICE_COLUMNS = [
    "ISIN",
    "component_name",
    "ETF_TICKERS",
    "ETF_COUNT",
    "row_count",
    "total_quantity",
    "reference_value_krw",
]

US_EXCHANGES = {"NAS", "NYS", "AMS"}
US_DAYTIME_EXCHANGE_MAP = {"NAS": "BAQ", "NYS": "BAY", "AMS": "BAA"}
# Venues that are *not* priceable via KIS REST; routed to alternate data
# sources (currently only Taiwan via mis.twse.com.tw).
NON_KIS_PRICE_EXCHANGES = set(TAIWAN_EXCHANGES)
US_EASTERN = ZoneInfo("America/New_York")
US_DAYTIME_STANDARD_START_KST = dt_time(10, 0)
US_DAYTIME_DST_START_KST = dt_time(9, 0)
US_DAYTIME_STANDARD_END_KST = dt_time(18, 0)
US_DAYTIME_DST_END_KST = dt_time(17, 0)


def decrypt_env(key: str) -> str:
    # 비밀값을 중앙 vault(평문, ETF_INAV_MONITOR__ 네임스페이스)에서 읽는다.
    # 이전 Fernet 암호문 스킴은 2026-06-25 중앙 vault 통합으로 폐기됨.
    return os.environ.get(f"ETF_INAV_MONITOR__{key}", "") or os.environ.get(key, "")


def today_yyyymmdd() -> str:
    return dt_date.today().strftime(KST_DATE_FORMAT)


def now_kst_string() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def now_kst() -> datetime:
    return datetime.now(KST)


def ensure_kst(value: datetime | None = None) -> datetime:
    current = value or now_kst()
    if current.tzinfo is None:
        return current.replace(tzinfo=KST)
    return current.astimezone(KST)


def is_us_dst(value: datetime | None = None) -> bool:
    return bool(ensure_kst(value).astimezone(US_EASTERN).dst())


_NYSE_CALENDAR = None


@lru_cache(maxsize=1024)
def _nyse_session_open(day: dt_date) -> bool:
    """True if NYSE has a regular session on ``day``. NYSE pandas calendar."""
    global _NYSE_CALENDAR
    if _NYSE_CALENDAR is None:
        import pandas_market_calendars as mcal

        _NYSE_CALENDAR = mcal.get_calendar("NYSE")
    return len(_NYSE_CALENDAR.valid_days(str(day), str(day))) > 0


def is_us_market_open(day: dt_date) -> bool:
    """True if the US market is open on ``day`` (a KST calendar date).

    The shared Holidays Excel (holiday_calendar) is the source of truth. When it
    has no entry for ``day`` (row or year file missing), fall back to the NYSE
    pandas calendar so US holiday protection never regresses while the sheet is
    still being populated.

    On a US holiday there is no live daytime session, so KIS keeps returning the
    last (stale) BAQ/BAY values; treating the window as inactive routes us to the
    regular NAS/NYS close instead.
    """
    status = holiday_calendar.us_status(day)  # True=휴장, False=개장, None=데이터 없음
    if status is not None:
        return not status
    return _nyse_session_open(day)


def us_daytime_window(value: datetime | None = None) -> dict:
    current = ensure_kst(value)
    dst = is_us_dst(current)
    start = US_DAYTIME_DST_START_KST if dst else US_DAYTIME_STANDARD_START_KST
    end = US_DAYTIME_DST_END_KST if dst else US_DAYTIME_STANDARD_END_KST
    market_open = is_us_market_open(current.date())
    active = market_open and (start <= current.time() < end)
    return {
        "active": active,
        "market_open": market_open,
        "is_dst": dst,
        "kst_now": current,
        "start": start,
        "end": end,
    }


def format_kst_time(value: dt_time) -> str:
    return value.strftime("%H:%M")


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


def load_config(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


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


def save_dataframe(df: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if output.suffix.lower() == ".parquet":
            df.to_parquet(output, index=False)
        else:
            df.to_csv(output, index=False, encoding="utf-8-sig")
    except PermissionError:
        fallback = output.with_name(f"{output.stem}_updated{output.suffix}")
        if output.suffix.lower() == ".parquet":
            df.to_parquet(fallback, index=False)
        else:
            df.to_csv(fallback, index=False, encoding="utf-8-sig")
        print(f"WARNING: could not write locked file {output}; saved {fallback}")


def load_cached_dataframe(cache_path: Path, legacy_path: Path | None = None) -> tuple[pd.DataFrame | None, Path | None]:
    if cache_path.exists():
        return load_csv(cache_path), cache_path
    if legacy_path is not None and legacy_path.exists():
        df = load_csv(legacy_path)
        save_dataframe(df, cache_path)
        return df, legacy_path
    return None, None


def select_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = None
    return out[columns]


def format_elapsed(seconds: float) -> str:
    return f"{seconds:.2f}s"


def record_timing(timings: list[tuple[str, float]], label: str, started_at: float) -> float:
    elapsed = time.perf_counter() - started_at
    timings.append((label, elapsed))
    print(f"[timing] {label}: {format_elapsed(elapsed)}")
    return elapsed


def timed_step(label: str, timings: list[tuple[str, float]], func, *args, **kwargs):
    started_at = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        record_timing(timings, label, started_at)


def timed_call(func, *args, **kwargs):
    started_at = time.perf_counter()
    result = func(*args, **kwargs)
    return result, time.perf_counter() - started_at


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


def post_krx_json(session: requests.Session, payload: dict, timeout: int = 15) -> dict:
    response = session.post(KRX_URL, headers=KRX_HEADERS, data=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def login_krx(session: requests.Session, user: str, pw: str) -> None:
    session.get(KRX_MAIN_PAGE_URL, headers=KRX_HEADERS, timeout=15)
    session.get(KRX_LOGIN_PAGE_URL, headers=KRX_HEADERS, timeout=15)
    session.get(
        KRX_LOGIN_JSP_URL,
        headers={**KRX_HEADERS, "Referer": KRX_LOGIN_PAGE_URL},
        timeout=15,
    )
    headers = {
        **KRX_HEADERS,
        "Referer": KRX_LOGIN_PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    payload = {
        "mbrId": user,
        "pw": pw,
        "mbrNm": "",
        "telNo": "",
        "di": "",
        "certType": "",
    }
    response = session.post(KRX_LOGIN_URL, headers=headers, data=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    error_code = data.get("_error_code", "")
    if error_code == "CD011":
        payload["skipDup"] = "Y"
        response = session.post(KRX_LOGIN_URL, headers=headers, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        error_code = data.get("_error_code", "")

    if error_code and error_code != "CD001":
        raise RuntimeError(f"KRX login failed: {error_code} {data.get('_error_message', '')}")


def make_krx_session(user: str | None, pw: str | None, verify_ssl: bool) -> requests.Session:
    session = requests.Session()
    session.verify = verify_ssl
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    krx_user = user or decrypt_env("KRX_USER")
    krx_pw = pw or decrypt_env("KRX_PW")
    if not krx_user or not krx_pw:
        session.close()
        raise RuntimeError("KRX credentials are required. Set KRX_USER/KRX_PW in .env or pass CLI args.")

    login_krx(session, krx_user, krx_pw)
    return session


def normalize_pdf_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in PDF_COLUMNS:
        if column not in df.columns:
            df[column] = None
    return df[PDF_COLUMNS]


def get_all_listed_etfs(session: requests.Session) -> pd.DataFrame:
    raw = post_krx_json(session, {"bld": "dbms/MDC/STAT/standard/MDCSTAT04601"})
    return pd.DataFrame(raw.get("output", []))


def get_etf_pdf_by_isin(session: requests.Session, isin: str, date: str) -> pd.DataFrame:
    raw = post_krx_json(
        session,
        {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT05001",
            "trdDd": date,
            "isuCd": isin,
        },
    )
    return pd.DataFrame(raw.get("output", []))


def get_etf_market_prices(session: requests.Session, date: str) -> pd.DataFrame:
    raw = post_krx_json(
        session,
        {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT04301",
            "trdDd": date,
        },
    )
    return pd.DataFrame(raw.get("output", []))


def fetch_one_etf_pdf(date: str, etf: dict, cookies: dict | None = None, verify_ssl: bool = False) -> dict:
    try:
        with requests.Session() as session:
            session.verify = verify_ssl
            if cookies:
                session.cookies.update(cookies)
            pdf_df = get_etf_pdf_by_isin(session, isin=etf["isin"], date=date)
        return {
            "order": etf["order"],
            "isin": etf["isin"],
            "ticker": etf["ticker"],
            "name": etf["name"],
            "pdf_df": pdf_df,
            "failed": False,
        }
    except Exception as exc:
        return {
            "order": etf["order"],
            "isin": etf["isin"],
            "ticker": etf["ticker"],
            "name": etf["name"],
            "pdf_df": pd.DataFrame(),
            "failed": True,
            "error": str(exc),
        }


def collect_etf_pdf(
    date: str,
    session: requests.Session,
    tickers: list[str],
    max_etfs: int | None,
    workers: int,
    sleep_seconds: float,
    include_empty: bool,
    verify_ssl: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    etf_list = get_all_listed_etfs(session)
    if etf_list.empty:
        return pd.DataFrame(), etf_list

    etf_list = etf_list.copy()
    etf_list.insert(0, "ETF_DATE", date)
    etf_list["ISU_SRT_CD"] = etf_list["ISU_SRT_CD"].map(normalize_ticker)

    if tickers:
        ticker_set = set(tickers)
        etf_list = etf_list[etf_list["ISU_SRT_CD"].isin(ticker_set)].copy()
    if max_etfs is not None:
        etf_list = etf_list.head(max_etfs).copy()

    records = []
    for order, (_, etf) in enumerate(etf_list.iterrows()):
        records.append(
            {
                "order": order,
                "isin": etf["ISU_CD"],
                "ticker": etf["ISU_SRT_CD"],
                "name": etf.get("ISU_ABBRV") or etf.get("ISU_NM") or "",
            }
        )

    if not records:
        return pd.DataFrame(), etf_list

    rows: list[tuple[int, pd.DataFrame]] = []
    failed = []
    max_workers = min(MAX_WORKERS, max(1, workers), len(records))
    cookies = dict(session.cookies)
    start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_one_etf_pdf, date, etf, cookies, verify_ssl)
            for etf in records
        ]
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            pdf_df = result["pdf_df"]
            ticker = result["ticker"]

            if result["failed"]:
                failed.append(ticker)
                print(f"[{idx}/{len(records)}] ticker={ticker} status=FAILED")
                continue

            if pdf_df.empty and not include_empty:
                print(f"[{idx}/{len(records)}] ticker={ticker} status=EMPTY_SKIPPED")
                continue
            if pdf_df.empty:
                pdf_df = pd.DataFrame([{column: None for column in PDF_COLUMNS}])

            pdf_df = normalize_pdf_columns(pdf_df)
            pdf_df.insert(0, "ETF_DATE", date)
            pdf_df.insert(1, "ETF_ISU_CD", result["isin"])
            pdf_df.insert(2, "ETF_TICKER", ticker)
            pdf_df.insert(3, "ETF_NAME", result["name"])
            rows.append((result["order"], pdf_df))

            elapsed = time.time() - start
            print(f"[{idx}/{len(records)}] ticker={ticker} status=OK rows={len(pdf_df)} elapsed={elapsed:.1f}s")
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    if failed:
        print(f"failed ETF count={len(failed)} tickers={','.join(failed)}")

    if not rows:
        return pd.DataFrame(columns=["ETF_DATE", "ETF_ISU_CD", "ETF_TICKER", "ETF_NAME"] + PDF_COLUMNS), etf_list

    rows.sort(key=lambda item: item[0])
    return pd.concat([row_df for _, row_df in rows], ignore_index=True), etf_list


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


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


def _pdf_cash_amt_populated(value) -> bool:
    """Whether a COMPST_AMT cell carries a usable numeric cash amount.

    KRX MDCSTAT05001 occasionally pads cash COMPST_AMT with ``-`` during
    intraday windows before today's PDF is fully published; we treat that as
    missing data.
    """
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text == "-":
        return False
    cleaned = text.replace(",", "").lstrip("-")
    return cleaned.replace(".", "", 1).isdigit() if cleaned else False


def pdf_has_complete_cash(pdf_df: pd.DataFrame) -> bool:
    """True when every cash row in the PDF has a populated COMPST_AMT."""
    if pdf_df is None or pdf_df.empty:
        return False
    code_col = "COMPST_ISU_CD2" if "COMPST_ISU_CD2" in pdf_df.columns else "COMPST_ISU_CD"
    if code_col not in pdf_df.columns or "COMPST_AMT" not in pdf_df.columns:
        return False
    codes = pdf_df[code_col].astype(str).str.strip()
    cash_rows = pdf_df[codes.isin(CASH_COMPONENT_CODES)]
    if cash_rows.empty:
        return True
    return cash_rows["COMPST_AMT"].apply(_pdf_cash_amt_populated).all()


def count_pdf_etfs(pdf_df: pd.DataFrame) -> int:
    """Number of distinct ETFs carried in a KRX PDF dataframe."""
    if pdf_df is None or pdf_df.empty or "ETF_TICKER" not in pdf_df.columns:
        return 0
    tickers = pdf_df["ETF_TICKER"].map(normalize_ticker)
    return int(tickers[tickers.astype(bool)].nunique())


def pdf_etf_flags(pdf_df: pd.DataFrame, target_tickers) -> dict[str, int]:
    """Per-monitored-ETF receipt flag: 1 if the ticker appears in the PDF else 0."""
    present: set[str] = set()
    if pdf_df is not None and not pdf_df.empty and "ETF_TICKER" in pdf_df.columns:
        present = {t for t in pdf_df["ETF_TICKER"].map(normalize_ticker) if t}
    return {
        norm: (1 if norm in present else 0)
        for norm in (normalize_ticker(t) for t in target_tickers)
        if norm
    }


def pdf_has_all_target_etfs(pdf_df: pd.DataFrame, target_tickers) -> bool:
    """True when every monitored ETF (target ticker) is present in the PDF.

    With no target set (ALL mode) there is no fixed expected count, so this
    returns True and the caller keeps its prior behavior.
    """
    flags = pdf_etf_flags(pdf_df, target_tickers)
    if not flags:
        return True
    return all(flags.values())


def merge_cash_from_previous_pdf(
    today_df: pd.DataFrame,
    prev_pdf_path: Path,
) -> pd.DataFrame:
    """Return a copy of ``today_df`` with cash rows' COMPST_AMT (and the
    related VALU_AMT/COMPST_RTO if present) replaced by values pulled from
    a prior trading day's PDF cache, matched by (ETF_ISU_CD, cash code).
    """
    if not prev_pdf_path.exists():
        return today_df
    try:
        prev_df = pd.read_csv(prev_pdf_path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError):
        return today_df
    code_col_prev = "COMPST_ISU_CD2" if "COMPST_ISU_CD2" in prev_df.columns else "COMPST_ISU_CD"
    if code_col_prev not in prev_df.columns or "ETF_ISU_CD" not in prev_df.columns:
        return today_df

    prev_codes = prev_df[code_col_prev].astype(str).str.strip()
    prev_cash = prev_df[prev_codes.isin(CASH_COMPONENT_CODES)]
    lookup: dict[tuple[str, str], pd.Series] = {}
    for _, row in prev_cash.iterrows():
        key = (
            str(row.get("ETF_ISU_CD", "")).strip(),
            str(row.get(code_col_prev, "")).strip(),
        )
        lookup[key] = row

    out = today_df.copy()
    code_col_today = "COMPST_ISU_CD2" if "COMPST_ISU_CD2" in out.columns else "COMPST_ISU_CD"
    if code_col_today not in out.columns or "ETF_ISU_CD" not in out.columns:
        return today_df
    today_codes = out[code_col_today].astype(str).str.strip()
    cash_mask = today_codes.isin(CASH_COMPONENT_CODES)
    update_cols = [c for c in ("VALU_AMT", "COMPST_AMT", "COMPST_RTO") if c in out.columns]

    for idx in out.index[cash_mask]:
        key = (
            str(out.at[idx, "ETF_ISU_CD"]).strip(),
            str(out.at[idx, code_col_today]).strip(),
        )
        prev_row = lookup.get(key)
        if prev_row is None:
            continue
        for col in update_cols:
            if col in prev_row.index:
                out.at[idx, col] = prev_row[col]
    return out


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


def build_required_price_df(prepared_pdf: pd.DataFrame) -> pd.DataFrame:
    if prepared_pdf is None or prepared_pdf.empty:
        return pd.DataFrame(columns=REQUIRED_PRICE_COLUMNS)

    candidates = prepared_pdf[
        prepared_pdf["is_price_candidate"] & prepared_pdf["component_isin"].astype(bool)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=REQUIRED_PRICE_COLUMNS)

    rows = []
    for isin, group in candidates.groupby("component_isin", dropna=False):
        etf_tickers = sorted(
            {
                normalize_ticker(value)
                for value in group["ETF_TICKER"].dropna().tolist()
                if normalize_ticker(value)
            }
        )
        rows.append(
            {
                "ISIN": isin,
                "component_name": group["COMPST_ISU_NM"].dropna().iloc[0]
                if group["COMPST_ISU_NM"].dropna().size
                else "",
                "ETF_TICKERS": ",".join(etf_tickers),
                "ETF_COUNT": len(etf_tickers),
                "row_count": len(group),
                "total_quantity": group["quantity"].sum(min_count=1),
                "reference_value_krw": group["reference_value_krw"].sum(min_count=1),
            }
        )
    return pd.DataFrame(rows)[REQUIRED_PRICE_COLUMNS].sort_values("ISIN")


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


def build_component_price_df(
    instruments: list[dict],
    snapshots: list[dict],
) -> pd.DataFrame:
    instrument_by_key = {(row["exchange"], row["ticker"]): row for row in instruments}
    rows = []

    for snap in snapshots:
        key = (snap.get("exchange", "").upper(), snap.get("symbol", "").upper())
        instrument = instrument_by_key.get(key, {})
        last = to_number(snap.get("last"))
        base = to_number(snap.get("base"))

        rows.append(
            {
                "ISIN": str(instrument.get("isin") or "").upper(),
                "ticker": key[1],
                "exchange": key[0],
                "price_exchange": snap.get("price_exchange") or key[0],
                "price_session": snap.get("price_session") or "regular",
                "currency": snap.get("currency"),
                "live_price": last,
                "base_price": base,
                "trade_time": snap.get("trade_time"),
                "korea_time": snap.get("korea_time"),
                "rsym": snap.get("rsym"),
                "rec_time": now_kst_string(),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["ISIN"])
    return pd.DataFrame(rows).drop_duplicates("ISIN")


def use_us_daytime_prices(mode: str, value: datetime | None = None) -> tuple[bool, dict]:
    window = us_daytime_window(value)
    normalized_mode = (mode or "auto").strip().lower()
    if normalized_mode == "force":
        return True, window
    if normalized_mode == "off":
        return False, window
    return bool(window["active"]), window


def build_price_targets(
    instruments: list[dict],
    us_daytime_mode: str,
) -> tuple[list[dict], dict]:
    use_daytime, window = use_us_daytime_prices(us_daytime_mode)
    targets: list[dict] = []
    daytime_count = 0
    for row in instruments:
        exchange = str(row.get("exchange") or "").upper()
        ticker = str(row.get("ticker") or "").upper()
        request_exchange = exchange
        price_session = "regular"
        if use_daytime and exchange in US_DAYTIME_EXCHANGE_MAP:
            request_exchange = US_DAYTIME_EXCHANGE_MAP[exchange]
            price_session = "us_daytime"
            daytime_count += 1
        targets.append(
            {
                "exchange": exchange,
                "request_exchange": request_exchange,
                "ticker": ticker,
                "price_session": price_session,
            }
        )

    window = dict(window)
    window["use_daytime"] = use_daytime
    window["daytime_count"] = daytime_count
    return targets, window


def normalize_requested_snapshots(
    target_rows: list[dict],
    snapshots: list[dict],
) -> tuple[list[dict], list[dict]]:
    normalized: list[dict] = []
    fallback_targets: list[dict] = []
    for target, snapshot in zip(target_rows, snapshots):
        snap = dict(snapshot or {})
        request_exchange = target["request_exchange"]
        original_exchange = target["exchange"]
        ticker = target["ticker"]
        snap["price_exchange"] = (snap.get("exchange") or request_exchange).upper()
        snap["price_session"] = target["price_session"]
        snap["exchange"] = original_exchange
        snap["symbol"] = ticker
        if target["price_session"] == "us_daytime" and (snap.get("error") or snap.get("last") is None):
            fallback_targets.append(target)
            continue
        normalized.append(snap)
    return normalized, fallback_targets


def normalize_fallback_snapshots(
    fallback_targets: list[dict],
    snapshots: list[dict],
) -> list[dict]:
    normalized: list[dict] = []
    for target, snapshot in zip(fallback_targets, snapshots):
        snap = dict(snapshot or {})
        original_exchange = target["exchange"]
        ticker = target["ticker"]
        snap["price_exchange"] = (snap.get("exchange") or original_exchange).upper()
        snap["price_session"] = "regular_fallback"
        snap["exchange"] = original_exchange
        snap["symbol"] = ticker
        normalized.append(snap)
    return normalized


def fetch_taiwan_snapshots(
    instruments: list[dict],
    timeout: int = 10,
    verify_ssl: bool = False,
) -> list[dict]:
    """Fetch Taiwan prices via mis.twse.com.tw and align snapshots to each
    instrument's declared exchange so engine key matching (and the resulting
    component price df) keeps working when OpenFIGI labels a TPEx listing as
    TWSE (or vice versa). The actual venue is preserved in ``price_exchange``
    and the ``rsym`` channel string.
    """
    if not instruments:
        return []
    targets = [
        ((inst.get("exchange") or "").upper(), str(inst.get("ticker") or "").upper())
        for inst in instruments
    ]
    targets = [(exchange, symbol) for exchange, symbol in targets if exchange and symbol]
    if not targets:
        return []
    raw = fetch_twse_prices(targets, timeout=timeout, verify_ssl=verify_ssl)
    instrument_exchange_by_symbol = {
        symbol: exchange for exchange, symbol in targets
    }
    normalized: list[dict] = []
    for snap in raw:
        symbol = (snap.get("symbol") or "").upper()
        original_exchange = instrument_exchange_by_symbol.get(symbol)
        if not original_exchange:
            continue
        snap = dict(snap)
        snap["price_exchange"] = (snap.get("exchange") or original_exchange).upper()
        snap["price_session"] = "twse_regular"
        snap["exchange"] = original_exchange
        snap["symbol"] = symbol
        normalized.append(snap)
    return normalized


def normalize_component_price_df(price_df: pd.DataFrame) -> pd.DataFrame:
    if price_df is None or price_df.empty:
        return pd.DataFrame(columns=COMPONENT_PRICE_COLUMNS)

    df = price_df.copy()
    legacy_map = {
        "live_price": ["live_price", "price", "live_price_local", "live_price_usd"],
        "base_price": ["base_price", "base_price_local", "base_price_usd"],
        "return_rate": ["return_rate", "return_local", "return_usd"],
    }
    for target, candidates in legacy_map.items():
        if target in df.columns:
            continue
        source = first_existing_column(df, candidates)
        if source is not None:
            df[target] = df[source]

    if "ISIN" in df.columns:
        isin = df["ISIN"].fillna("").astype(str).str.upper()
        korean = isin.str.startswith("KR") & isin.str.len().eq(12)
        if korean.any():
            for column in ("ticker", "exchange", "currency"):
                if column not in df.columns:
                    df[column] = ""
            derived_symbol = isin.str.slice(3, 9)
            missing_ticker = df["ticker"].fillna("").astype(str).str.strip().eq("")
            df.loc[korean & missing_ticker, "ticker"] = derived_symbol[korean & missing_ticker]
            exchange = df["exchange"].fillna("").astype(str).str.upper()
            df.loc[korean & exchange.ne("KFO"), "exchange"] = "KRX"
            df.loc[korean, "currency"] = "KRW"
    return df


def fetch_component_prices(
    pdf_df: pd.DataFrame,
    db_path: Path | None,
    verify_ssl: bool,
    timeout: int,
    isin_batch_size: int,
    batch_delay_seconds: float,
    openfigi_api_key: str | None,
    paper: bool,
    price_requests_per_second: float,
    price_workers: int,
    overseas_price_batch_size: int,
    us_daytime_mode: str,
) -> tuple[pd.DataFrame, dict]:
    started_at = time.perf_counter()
    stock_rows = build_component_stock_rows(pdf_df)
    print(f"[timing] price lane build stock rows: {format_elapsed(time.perf_counter() - started_at)}")
    if not stock_rows:
        return pd.DataFrame(columns=["ISIN"]), {"instruments": [], "unresolved": [], "prices": []}

    started_at = time.perf_counter()
    store = KisStore(db_path=db_path)
    store.init_db()
    auth = KisAuth(KisCredentials.from_env(paper=paper), verify_ssl=verify_ssl, timeout=timeout)
    master = KisMaster(verify_ssl=verify_ssl)
    client = KisRestClient(auth=auth, timeout=timeout)
    print(f"[timing] price lane initialize clients: {format_elapsed(time.perf_counter() - started_at)}")

    started_at = time.perf_counter()
    instruments, unresolved = resolve_instruments(
        stock_rows,
        store=store,
        master=master,
        openfigi_api_key=openfigi_api_key,
        verify_ssl=verify_ssl,
        timeout=timeout,
        isin_batch_size=isin_batch_size,
        batch_delay_seconds=batch_delay_seconds,
    )
    print(f"[timing] price lane resolve instruments: {format_elapsed(time.perf_counter() - started_at)}")

    kis_instruments = [
        inst for inst in instruments
        if (inst.get("exchange") or "").upper() not in NON_KIS_PRICE_EXCHANGES
    ]
    taiwan_instruments = [
        inst for inst in instruments
        if (inst.get("exchange") or "").upper() in TAIWAN_EXCHANGES
    ]

    target_rows, daytime_window = build_price_targets(kis_instruments, us_daytime_mode)
    targets = [(row["request_exchange"], row["ticker"]) for row in target_rows]
    price_delay_seconds = 1.0 / price_requests_per_second
    window_text = (
        f"{format_kst_time(daytime_window['start'])}-"
        f"{format_kst_time(daytime_window['end'])} KST"
    )
    print(
        f"KIS price snapshot targets={len(targets)} mode={'paper' if paper else 'live'} "
        f"rate_limit={price_requests_per_second:g}/s workers={price_workers} "
        f"overseas_batch_size={overseas_price_batch_size}"
    )
    print(
        f"US daytime prices mode={us_daytime_mode} active={daytime_window['use_daytime']} "
        f"market_open={daytime_window.get('market_open')} "
        f"us_dst={daytime_window['is_dst']} window={window_text} "
        f"targets={daytime_window['daytime_count']}"
    )
    started_at = time.perf_counter()
    requested_snapshots = client.snapshots(
        targets,
        batch_delay_seconds=price_delay_seconds,
        max_workers=price_workers,
        overseas_batch_size=overseas_price_batch_size,
    )
    snapshots, fallback_targets = normalize_requested_snapshots(target_rows, requested_snapshots)
    if fallback_targets:
        fallback_snapshot_rows = client.snapshots(
            [(row["exchange"], row["ticker"]) for row in fallback_targets],
            batch_delay_seconds=price_delay_seconds,
            max_workers=price_workers,
            overseas_batch_size=overseas_price_batch_size,
        )
        snapshots.extend(normalize_fallback_snapshots(fallback_targets, fallback_snapshot_rows))
        print(f"US daytime price fallback targets={len(fallback_targets)}")
    print(f"[timing] price lane fetch KIS snapshots: {format_elapsed(time.perf_counter() - started_at)}")

    if taiwan_instruments:
        started_at = time.perf_counter()
        twse_snapshots = fetch_taiwan_snapshots(
            taiwan_instruments,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
        snapshots.extend(twse_snapshots)
        print(
            f"[timing] price lane fetch TWSE snapshots: "
            f"{format_elapsed(time.perf_counter() - started_at)} "
            f"targets={len(taiwan_instruments)} returned={len(twse_snapshots)} "
            f"trading_hours={is_twse_trading_hours()}"
        )

    started_at = time.perf_counter()
    price_df = build_component_price_df(instruments, snapshots)
    print(f"[timing] price lane build price dataframe: {format_elapsed(time.perf_counter() - started_at)}")
    return price_df, {
        "instruments": instruments,
        "unresolved": unresolved,
        "prices": snapshots,
    }


def load_or_fetch_component_prices(
    args: argparse.Namespace,
    prepared_pdf: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if args.price_csv:
        price_df = normalize_component_price_df(load_csv(args.price_csv))
        return price_df, {"instruments": [], "unresolved": [], "prices": []}
    if args.no_fetch_prices:
        return pd.DataFrame(columns=COMPONENT_PRICE_COLUMNS), {
            "instruments": [],
            "unresolved": [],
            "prices": [],
        }
    price_requests_per_second = args.price_requests_per_second
    if price_requests_per_second is None:
        price_requests_per_second = 2.0 if args.paper else 20.0
    if price_requests_per_second <= 0:
        raise ValueError("--price-requests-per-second must be greater than 0")

    price_workers = args.price_workers
    if price_workers is None:
        price_workers = 2 if args.paper else 8
    if price_workers <= 0:
        raise ValueError("--price-workers must be greater than 0")

    overseas_price_batch_size = args.overseas_price_batch_size
    if overseas_price_batch_size is None:
        overseas_price_batch_size = 1 if args.paper else 10
    if overseas_price_batch_size <= 0:
        raise ValueError("--overseas-price-batch-size must be greater than 0")
    if args.paper and overseas_price_batch_size > 1:
        overseas_price_batch_size = 1

    price_df, price_result = fetch_component_prices(
        prepared_pdf,
        db_path=args.db_path,
        verify_ssl=args.verify_ssl,
        timeout=args.timeout,
        isin_batch_size=args.isin_batch_size,
        batch_delay_seconds=args.batch_delay_seconds,
        openfigi_api_key=args.openfigi_api_key,
        paper=args.paper,
        price_requests_per_second=price_requests_per_second,
        price_workers=price_workers,
        overseas_price_batch_size=overseas_price_batch_size,
        us_daytime_mode=args.us_daytime_prices,
    )
    return normalize_component_price_df(price_df), price_result


def load_or_fetch_krx_inputs(
    args: argparse.Namespace,
    cache_dir: Path,
    target_tickers: list[str],
    legacy_cache_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pdf_df = load_csv(args.pdf_csv) if args.pdf_csv else None
    etf_list_df = load_csv(args.etf_list_csv) if args.etf_list_csv else None
    market_df = load_csv(args.market_csv) if args.market_csv else None

    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_cache = cache_dir / f"krx_etf_pdf_{args.date}.csv"
    etf_list_cache = cache_dir / f"krx_etf_list_{args.date}.csv"
    market_cache = cache_dir / f"krx_etf_market_{args.date}.csv"
    legacy_pdf_cache = legacy_cache_dir / f"krx_etf_pdf_{args.date}.csv" if legacy_cache_dir else None
    legacy_etf_list_cache = legacy_cache_dir / f"krx_etf_list_{args.date}.csv" if legacy_cache_dir else None
    legacy_market_cache = legacy_cache_dir / f"krx_etf_market_{args.date}.csv" if legacy_cache_dir else None

    if pdf_df is None:
        pdf_df, used_cache = load_cached_dataframe(pdf_cache, legacy_pdf_cache)
        if used_cache:
            print(f"Skipped KRX PDF fetch: using cached {used_cache}")
    if etf_list_df is None:
        etf_list_df, used_cache = load_cached_dataframe(etf_list_cache, legacy_etf_list_cache)
        if used_cache:
            print(f"Skipped KRX ETF list fetch: using cached {used_cache}")
    if market_df is None:
        market_df, used_cache = load_cached_dataframe(market_cache, legacy_market_cache)
        if used_cache:
            print(f"Skipped KRX market fetch: using cached {used_cache}")

    needs_pdf = pdf_df is None or pdf_df.empty
    needs_etf_list = etf_list_df is None
    needs_market = market_df is None and not args.no_market_fetch

    if not (needs_pdf or needs_etf_list or needs_market):
        return pdf_df, etf_list_df, market_df

    session = make_krx_session(args.krx_user, args.krx_pw, args.verify_ssl)
    try:
        if needs_etf_list:
            etf_list_df = get_all_listed_etfs(session)
            if not etf_list_df.empty:
                etf_list_df = etf_list_df.copy()
                etf_list_df.insert(0, "ETF_DATE", args.date)
                if target_tickers:
                    ticker_set = set(target_tickers)
                    etf_list_df = etf_list_df[
                        etf_list_df["ISU_SRT_CD"].map(normalize_ticker).isin(ticker_set)
                    ].copy()
            save_dataframe(etf_list_df, etf_list_cache)

        if needs_pdf:
            krx_pdf_df, _ = collect_etf_pdf(
                date=args.date,
                session=session,
                tickers=target_tickers,
                max_etfs=args.max_etfs,
                workers=args.workers,
                sleep_seconds=args.krx_sleep_seconds,
                include_empty=args.include_empty,
                verify_ssl=args.verify_ssl,
            )
            if not krx_pdf_df.empty:
                krx_pdf_df = krx_pdf_df.copy()
                krx_pdf_df["pdf_source"] = "krx_pdf"
                pdf_df = krx_pdf_df
                save_dataframe(pdf_df, pdf_cache)

        if needs_market:
            market_df = get_etf_market_prices(session, args.date)
            save_dataframe(market_df, market_cache)
    finally:
        session.close()

    if market_df is None:
        market_df = pd.DataFrame()
    return pdf_df, etf_list_df, market_df


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate Korea-listed ETF iNAV using KRX PDF, Naver FX, and KIS local-currency prices."
    )
    parser.add_argument("date", nargs="?", default=today_yyyymmdd(), help="Trade date in YYYYMMDD format.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON config path.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ETF tickers. Overrides config.")
    parser.add_argument("--all-etfs", action="store_true", help="Ignore config tickers and run all listed ETFs.")
    parser.add_argument("--max-etfs", type=int, default=None, help="Limit ETF count for testing.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_KRX_CACHE_DIR, help="KRX input cache directory.")
    parser.add_argument(
        "--save-all",
        "--save-artifacts",
        dest="save_all",
        action="store_true",
        help="Save KRX inputs, required price list, component prices, and component-level detail CSVs.",
    )
    parser.add_argument("--pdf-csv", type=Path, default=None, help="Use a saved KRX ETF PDF CSV instead of fetching.")
    parser.add_argument("--etf-list-csv", type=Path, default=None, help="Use a saved KRX ETF list CSV instead of fetching.")
    parser.add_argument("--market-csv", type=Path, default=None, help="Use a saved ETF market price CSV instead of fetching.")
    parser.add_argument("--price-csv", dest="price_csv", type=Path, default=None, help="Use a saved component_prices CSV instead of fetching KIS prices.")
    parser.add_argument("--us-price-csv", dest="price_csv", type=Path, help="Backward-compatible alias for --price-csv.")
    parser.add_argument("--no-market-fetch", action="store_true", help="Skip KRX ETF market price fetch.")
    parser.add_argument("--include-empty", action="store_true", help="Keep ETF rows even when PDF is empty.")
    parser.add_argument("--krx-user", default=None, help="KRX login ID. Defaults to decrypted KRX_USER in .env.")
    parser.add_argument("--krx-pw", default=None, help="KRX login password. Defaults to decrypted KRX_PW in .env.")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="KRX PDF fetch workers.")
    parser.add_argument("--krx-sleep-seconds", type=float, default=0.0, help="Delay after each KRX PDF result.")
    parser.add_argument("--verify-ssl", action="store_true", help="Enable SSL verification for KRX/KIS/OpenFIGI.")
    parser.add_argument("--no-fetch-prices", dest="no_fetch_prices", action="store_true", help="Skip KIS/OpenFIGI price fetch.")
    parser.add_argument("--no-fetch-us-prices", dest="no_fetch_prices", action="store_true", help="Backward-compatible alias for --no-fetch-prices.")
    parser.add_argument("--price-isin-prefixes", default=None, help="ISIN country prefixes for KIS price fetch. Use ALL for no prefix filter.")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path for KIS price cache.")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP timeout seconds for KIS/OpenFIGI.")
    parser.add_argument("--isin-batch-size", type=int, default=10, help="OpenFIGI ISIN mapping batch size.")
    parser.add_argument("--batch-delay-seconds", type=float, default=2.0, help="Delay between OpenFIGI batches.")
    parser.add_argument(
        "--price-requests-per-second",
        type=float,
        default=None,
        help="KIS price snapshot REST rate limit. Defaults to 20 for live trading and 2 for paper trading.",
    )
    parser.add_argument(
        "--price-workers",
        type=int,
        default=None,
        help="Concurrent workers for KIS price snapshots. Defaults to 8 for live trading and 2 for paper trading.",
    )
    parser.add_argument(
        "--overseas-price-batch-size",
        type=int,
        default=None,
        help="Number of overseas symbols per KIS multprice request. Defaults to 10 for live trading and 1 for paper trading.",
    )
    parser.add_argument(
        "--us-daytime-prices",
        choices=("auto", "off", "force"),
        default="auto",
        help=(
            "Use US daytime trading quotes (NAS/NYS/AMS -> BAQ/BAY/BAA). "
            "auto applies during the KST daytime window, force always applies, off disables it."
        ),
    )
    parser.add_argument("--openfigi-api-key", default=None, help="Optional OpenFIGI API key.")
    parser.add_argument("--paper", action="store_true", help="Use KIS paper trading endpoint.")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    total_started_at = time.perf_counter()
    timings: list[tuple[str, float]] = []

    args = timed_step("parse arguments", timings, parse_args, argv)
    config = timed_step("load config", timings, load_config, args.config)

    setup_started_at = time.perf_counter()
    target_tickers = []
    if not args.all_etfs:
        target_tickers = parse_ticker_list(args.tickers) if args.tickers else config_tickers(config)

    output_dir = args.output_dir / args.date
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = args.cache_dir / args.date

    price_prefixes = args.price_isin_prefixes or config.get("price_isin_prefixes") or DEFAULT_PRICE_ISIN_PREFIXES
    prefixes = parse_prefixes(price_prefixes)
    record_timing(timings, "initialize run", setup_started_at)

    pdf_df, etf_list_df, market_df = timed_step(
        "load or fetch KRX inputs",
        timings,
        load_or_fetch_krx_inputs,
        args,
        cache_dir,
        target_tickers,
        legacy_cache_dir=output_dir,
    )
    pdf_df, etf_list_df, market_df = timed_step(
        "filter inputs",
        timings,
        filter_inputs_by_ticker,
        pdf_df,
        etf_list_df,
        market_df,
        tickers=target_tickers,
        max_etfs=args.max_etfs,
    )
    if pdf_df is None or pdf_df.empty:
        print("No ETF PDF rows found.")
        record_timing(timings, "total", total_started_at)
        return 1

    prepare_started_at = time.perf_counter()
    prepared_pdf = prepare_pdf_df(pdf_df, prefixes)
    required_price_df = build_required_price_df(prepared_pdf)
    record_timing(timings, "prepare PDF inputs", prepare_started_at)
    print(
        f"PDF rows={len(prepared_pdf)} ETF count={prepared_pdf['ETF_TICKER'].nunique()} "
        f"price_candidates={int(prepared_pdf['is_price_candidate'].sum())}"
    )

    print("Starting Naver FX and KIS price lanes in parallel.")
    parallel_started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        fx_future = executor.submit(
            timed_call,
            fetch_fx_table,
            timeout=args.timeout,
            verify_ssl=args.verify_ssl,
        )
        price_future = executor.submit(timed_call, load_or_fetch_component_prices, args, prepared_pdf)
        (price_df, price_result), price_elapsed = price_future.result()
        fx_table, fx_elapsed = fx_future.result()
    timings.append(("fetch component prices", price_elapsed))
    print(f"[timing] fetch component prices: {format_elapsed(price_elapsed)}")
    timings.append(("fetch Naver FX", fx_elapsed))
    print(f"[timing] fetch Naver FX: {format_elapsed(fx_elapsed)}")
    record_timing(timings, "parallel price lanes", parallel_started_at)

    print(f"Naver FX rates: {fx_table['rates']} fetched_at={fx_table['fetched_at']}")
    if fx_table.get("errors"):
        print(f"FX errors: {fx_table['errors']}")

    engine_started_at = time.perf_counter()
    engine = InavEngine(
        prepared_pdf,
        etf_list_df,
        market_df,
        instruments=price_result.get("instruments", []),
    )
    engine.set_fx_rates(fx_table)
    if price_result.get("prices"):
        engine.bulk_update_from_snapshots(price_result["prices"])
    else:
        engine.update_prices_from_df(price_df)
    engine.set_closed_exchanges(holiday_calendar.closed_exchanges())
    record_timing(timings, "initialize iNAV engine", engine_started_at)
    components, summary = timed_step("compute iNAV", timings, engine.compute)

    detail_path = output_dir / f"etf_inav_components_{args.date}.csv"
    summary_path = output_dir / f"etf_inav_summary_{args.date}.csv"
    timed_step("save summary", timings, save_dataframe, summary, summary_path)

    if args.save_all:
        timed_step("save KRX PDF artifact", timings, save_dataframe, pdf_df, output_dir / f"krx_etf_pdf_{args.date}.csv")
        timed_step(
            "save ETF list artifact",
            timings,
            save_dataframe,
            etf_list_df if etf_list_df is not None else pd.DataFrame(),
            output_dir / f"krx_etf_list_{args.date}.csv",
        )
        timed_step(
            "save ETF market artifact",
            timings,
            save_dataframe,
            market_df if market_df is not None else pd.DataFrame(),
            output_dir / f"krx_etf_market_{args.date}.csv",
        )
        timed_step(
            "save required prices artifact",
            timings,
            save_dataframe,
            required_price_df,
            output_dir / f"required_component_prices_{args.date}.csv",
        )
        timed_step(
            "save component prices artifact",
            timings,
            save_dataframe,
            select_columns(price_df, COMPONENT_PRICE_COLUMNS),
            output_dir / f"component_prices_{args.date}.csv",
        )
        timed_step("save components artifact", timings, save_dataframe, components, detail_path)

    print(f"Resolved instruments: {len(price_result.get('instruments', []))}")
    print(f"Unresolved ISINs: {len(price_result.get('unresolved', []))}")
    if args.save_all:
        print(f"Saved artifacts in: {output_dir}")
    print(f"Saved summary: {summary_path} rows={len(summary)}")
    record_timing(timings, "total", total_started_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
