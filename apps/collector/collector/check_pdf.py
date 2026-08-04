"""CHECK CLIST 원시 바스켓 → KRX 스키마 PDF 변환 lane.

시트-리더(``check_sheet_reader.ps1``, CHECK PC)가 매일 08:01 S드라이브에 떨구는
``check_pdf/check_pdf_raw_{date}.csv`` 를 KRX PDF 와 동일 스키마로 변환한다.

원래 이 변환은 구시스템 ``streaming.py`` 가 호출해 결과를
``output/results/etf_inav/{date}/krx_etf_pdf_{date}.csv`` 로 기록했고, collector 는
그 파일만 읽었다. streaming.py 가 정지한 2026-07-31 이후로는 원시 바스켓만 매일
갱신되고 변환된 PDF 는 생성되지 않아 collector 가 계속 STALE_CACHE 로 떨어졌다
(2026-08-03 확인: 457480 TSLA 수량 425(7/31) vs 427(당일)). 그래서 변환을 여기로
가져온다. 레거시 출력 경로는 ``:ro`` 마운트라 파일로 쓰지 않고 DataFrame 을 그대로
엔진에 넘긴다.

``convert`` 이하는 레거시 ``etf_inav/data_sources/check_pdf_to_krx.py`` 에서 VERBATIM
복사했다 (krx_prep.py / krx_fetch.py 와 같은 이유 — 게이트 판정이 구시스템과
한 글자도 달라지면 안 된다). "개선"하지 말 것. ``load_check_pdf`` 만 collector 소유
글루로, 레거시 ``build_check_pdf`` 의 all-or-nothing 게이트를 파일 기록 없이 옮긴 것.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from etf_inav.core.engine import KRW_CASH_CODE, SETTING_CASH_CODE

CASH_CODES = {SETTING_CASH_CODE, KRW_CASH_CODE}

# 기존 KRX PDF CSV 의 전체 컬럼(순서 고정) — batch.collect_etf_pdf 산출물과 일치.
OUTPUT_COLUMNS = [
    "ETF_DATE", "ETF_ISU_CD", "ETF_TICKER", "ETF_NAME",
    "COMPST_ISU_CD", "COMPST_ISU_CD2", "MKT_ID", "SECUGRP_ID",
    "COMPST_ISU_NM", "COMPST_ISU_CU1_SHRS", "VALU_AMT", "COMPST_AMT", "COMPST_RTO",
]

# 합계불변식 허용오차(평가금액 합 vs 설정현금액).
INVARIANT_TOLERANCE = 0.005  # 0.5%

# 설정현금액(CASH00000001) 행이 원래 없는 ETF — 국내주식형 0199C0 은 KRX 정식
# PDF(예: 20260720)에도 CASH00000001 없이 원화현금만 실린다(2026-07-22 확인).
NO_SETTING_CASH_TICKERS = {"0199C0"}


def _log(msg: str) -> None:
    print(f"[check_pdf] {msg}", file=sys.stderr, flush=True)


# ── verbatim check_pdf_to_krx.py ────────────────────────────────────────
def _norm_check(code) -> str:
    return "" if code is None else str(code).strip().upper()


def _is_number(v) -> bool:
    if v is None:
        return False
    text = str(v).strip().replace(",", "").replace("%", "")
    if text in ("", "-", "nan", "None", "#N/A", "#VALUE!", "#NAME?"):
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _num(v) -> float:
    return float(str(v).strip().replace(",", "").replace("%", ""))


def convert(
    raw_csv: Path,
    etf_names: dict[str, str],
    target_date: str,
) -> tuple[pd.DataFrame, dict]:
    """원시 바스켓 → KRX 스키마 DataFrame. (df, status) 반환.

    status = {"ok": [tickers], "rejected": {ticker: reason}, "unmapped": [(ticker, code)]}
    df 에는 ok 인 ETF 만 포함된다(fail-loud: rejected ETF 는 1행도 안 들어감).
    ISIN 은 원시행의 ``isin`` 컬럼(CHECK globalstndcode)을 그대로 사용.
    """
    raw = pd.read_csv(raw_csv, dtype=str, keep_default_na=False)

    status: dict = {"ok": [], "rejected": {}, "unmapped": []}
    out_rows: list[dict] = []

    for ticker, grp in raw.groupby("etf_ticker", dropna=False):
        ticker = _norm_check(ticker)
        if not ticker:
            continue
        reject: str | None = None
        eft_rows: list[dict] = []
        sum_amt = setting_cash_amt = 0.0
        has_setting_cash = False

        for _, r in grp.iterrows():
            code = _norm_check(r.get("code"))
            name = (r.get("name") or "").strip()
            basis = _norm_check(r.get("basis_date"))
            if basis and basis != target_date:
                reject = f"stale(기준일 {basis}≠{target_date})"
                break
            if not _is_number(r.get("qty")) or not _is_number(r.get("amt")) or not _is_number(r.get("weight")):
                reject = f"#N/A/비수치 셀(code={code})"
                break
            qty, amt, weight = _num(r["qty"]), _num(r["amt"]), _num(r["weight"])

            if code in CASH_CODES:
                isin = code  # 현금코드 그대로 통과(유효 ISIN 아님 → engine 이 cash 로 분기)
                if code == SETTING_CASH_CODE:
                    has_setting_cash, setting_cash_amt = True, amt
                    continue  # 설정현금액은 '총 CU 기준액'이라 보유행 아님 → 합계에서 제외
            else:
                isin = _norm_check(r.get("isin"))  # CHECK 가 직접 제공(globalstndcode)
                if (not isin or isin == "-") and re.fullmatch(r"KR4[A-Z0-9]{9}", code):
                    # 장내파생(선물·옵션) 행은 CHECK 가 globalstndcode 를 '-' 로 주는
                    # 대신 단축코드 자리에 완전한 KR4 ISIN 을 싣는다(0199C0 위클리
                    # 옵션에서 확인). KRX PDF 도 같은 값을 COMPST_ISU_CD 로 싣던
                    # 행이므로 코드를 ISIN 으로 그대로 쓴다.
                    isin = code
                if not isin or isin == "-":
                    status["unmapped"].append((ticker, code))
                    reject = f"ISIN 없음(code={code})"
                    break
            # 장내파생(ISIN KR4~)의 amt 는 명목금액이라 설정현금액과 안 맞는다 —
            # 엔진 선물 특례와 같은 원리로 합계불변식에서만 제외(행은 emit).
            if not isin.startswith("KR4"):
                sum_amt += amt
            eft_rows.append({
                "ETF_DATE": target_date, "ETF_ISU_CD": "",
                "ETF_TICKER": ticker, "ETF_NAME": etf_names.get(ticker, ""),
                "COMPST_ISU_CD": isin, "COMPST_ISU_CD2": isin,
                "MKT_ID": "", "SECUGRP_ID": "", "COMPST_ISU_NM": name,
                "COMPST_ISU_CU1_SHRS": qty, "VALU_AMT": amt,
                "COMPST_AMT": amt, "COMPST_RTO": weight,
            })

        if reject is None and not has_setting_cash and ticker not in NO_SETTING_CASH_TICKERS:
            reject = "설정현금액(CASH00000001) 행 없음 — 미완성 바스켓"
        if reject is None and setting_cash_amt > 0:
            drift = abs(sum_amt - setting_cash_amt) / setting_cash_amt
            if drift > INVARIANT_TOLERANCE:
                reject = f"합계불변식 위반(drift={drift:.3%})"

        if reject is not None:
            status["rejected"][ticker] = reject
            print(f"[check_pdf] REJECT {ticker}: {reject}", file=sys.stderr)
            continue
        status["ok"].append(ticker)
        out_rows.extend(eft_rows)

    df = pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS) if out_rows else pd.DataFrame(columns=OUTPUT_COLUMNS)
    return df, status


# ── collector-owned glue ────────────────────────────────────────────────
def load_check_pdf(
    raw_dir: Path,
    target_date: str,
    target_tickers: list[str],
    etf_names: dict[str, str] | None = None,
) -> pd.DataFrame | None:
    """오늘자 원시 바스켓을 KRX 스키마 DataFrame 으로 변환해 반환. 실패면 None.

    레거시 ``build_check_pdf`` 와 같은 all-or-nothing 게이트: 타깃 ticker 전부가 ok
    일 때만 반환한다(부분 완성은 거부 → 호출자가 KRX/STALE 로 폴백). 레거시와 달리
    파일은 쓰지 않는다 — 출력 경로가 ``:ro`` 마운트라서.
    """
    raw = Path(raw_dir) / f"check_pdf_raw_{target_date}.csv"
    if not raw.exists():
        _log(f"원시 바스켓 없음: {raw}")
        return None
    try:
        df, status = convert(raw, etf_names or {}, target_date)
    except Exception as exc:  # noqa: BLE001 - 변환 실패 → 호출자가 폴백
        _log(f"변환 실패: {exc!r}")
        return None

    have = {str(t).strip().upper() for t in df["ETF_TICKER"].unique()} if not df.empty else set()
    missing = sorted({str(t).strip().upper() for t in target_tickers} - have)
    if missing or df.empty:
        _log(f"미완성(누락 {missing}) → 폴백")
        return None

    _log(f"CHECK PDF 적용: {len(status['ok'])} ETF, rows={len(df)} ({raw.name})")
    return df
