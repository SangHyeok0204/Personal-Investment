"""KRX self-fetch lane for the collector.

The Phase-1 collector read the legacy system's KRX cache CSVs only. Once the
legacy system is terminated nobody refreshes those CSVs, so the collector must
fetch its own KRX inputs (ETF list / per-ISIN PDF / market prices).

The network functions here are copied VERBATIM from the legacy
``etf_inav/workflows/batch.py`` so the KRX request/parse flow stays byte-parity
with production. They live here instead of importing ``batch`` because that
module imports ``etf_inav.data_sources.holiday_calendar`` (not part of the
copied Phase-1 subset) and computes ``parents[5]`` at import — mirroring the
same reasoning as ``krx_prep.py``.

Do not "improve" the copied functions — keep them identical to the legacy
source. Only ``fetch_krx_inputs`` (the orchestrator) is collector-owned glue.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
import urllib3

from collector.krx_prep import normalize_ticker

# ── constants (verbatim from batch.py) ──────────────────────────────────
KRX_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_LOGIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
KRX_LOGIN_JSP_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_MAIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"
KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}
MAX_WORKERS = 5
# Legacy batch.py uses a 15s read timeout (fast on the main PC's direct KRX
# path). Through the container's Somansa-proxied path the 구성종목 PDF endpoint
# (MDCSTAT05001) responds in ~19s, so 15s times out. Raise the JSON POST ceiling
# for the self-fetch lane (list/market still return well under this).
KRX_HTTP_TIMEOUT = 60

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


def _log(msg: str) -> None:
    print(f"[krx_fetch] {msg}", file=sys.stderr, flush=True)


# ── verbatim batch.py helpers ───────────────────────────────────────────
def decrypt_env(key: str) -> str:
    # 비밀값을 중앙 vault(평문, ETF_INAV_MONITOR__ 네임스페이스)에서 읽는다.
    # 이전 Fernet 암호문 스킴은 2026-06-25 중앙 vault 통합으로 폐기됨.
    return os.environ.get(f"ETF_INAV_MONITOR__{key}", "") or os.environ.get(key, "")


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


def post_krx_json(session: requests.Session, payload: dict, timeout: int = KRX_HTTP_TIMEOUT) -> dict:
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


# ── collector-owned orchestrator ────────────────────────────────────────
def fetch_krx_inputs(
    run_date: str,
    target_tickers: list[str],
    cache_dir: Path,
    *,
    verify_ssl: bool = False,
    timeout: int = 10,
    workers: int = MAX_WORKERS,
    sleep_seconds: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch today's KRX inputs and write them to ``cache_dir/{run_date}/`` using
    the same filenames/format the legacy cache uses, then return the dataframes.

    Mirrors the fetch branch of the legacy ``load_or_fetch_krx_inputs``: ETF list
    (filtered to targets), per-ISIN PDF for the targets, and the ETF market
    price table. Raises if the resulting PDF is empty so the caller can fall
    back to the (stale) legacy cache.
    """
    day_dir = Path(cache_dir) / run_date
    day_dir.mkdir(parents=True, exist_ok=True)

    session = make_krx_session(None, None, verify_ssl)
    try:
        etf_list_df = get_all_listed_etfs(session)
        if not etf_list_df.empty:
            etf_list_df = etf_list_df.copy()
            etf_list_df.insert(0, "ETF_DATE", run_date)
            if target_tickers:
                ticker_set = set(target_tickers)
                etf_list_df = etf_list_df[
                    etf_list_df["ISU_SRT_CD"].map(normalize_ticker).isin(ticker_set)
                ].copy()
        save_dataframe(etf_list_df, day_dir / f"krx_etf_list_{run_date}.csv")

        pdf_df, _ = collect_etf_pdf(
            date=run_date,
            session=session,
            tickers=list(target_tickers),
            max_etfs=None,
            workers=workers,
            sleep_seconds=sleep_seconds,
            include_empty=False,
            verify_ssl=verify_ssl,
        )
        if pdf_df is not None and not pdf_df.empty:
            pdf_df = pdf_df.copy()
            pdf_df["pdf_source"] = "krx_pdf"
        save_dataframe(pdf_df, day_dir / f"krx_etf_pdf_{run_date}.csv")

        market_df = get_etf_market_prices(session, run_date)
        save_dataframe(market_df, day_dir / f"krx_etf_market_{run_date}.csv")
    finally:
        session.close()

    if pdf_df is None or pdf_df.empty:
        raise RuntimeError(f"KRX self-fetch produced an empty PDF for {run_date}")
    _log(
        f"self-fetch complete date={run_date} pdf_rows={len(pdf_df)} "
        f"list_rows={len(etf_list_df)} market_rows={len(market_df)} dir={day_dir}"
    )
    return pdf_df, etf_list_df, market_df
