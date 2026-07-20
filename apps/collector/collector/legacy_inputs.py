"""Read-only loaders for the legacy ETF-iNAV system's artifacts.

All source paths are mounted ``:ro`` (see docker-compose collector service).
The only writable directory is ``/app/.cache`` (a named volume). We *copy*
the prod-issued KIS token, the KIS master parquet cache, and the OpenFIGI
SQLite DB into that writable dir so the verbatim modules can use them without
(a) issuing a new token — which could invalidate prod's — or (b) writing to
the read-only mounts.

Real legacy layout (discovered on S:), overridable via env:
  config          {LEGACY_CONFIG}/etf_inav_config.json
  KRX PDF/list/mkt {LEGACY_ETF_DATA}/output/results/etf_inav/{date}/krx_etf_*_{date}.csv
  KIS token        {LEGACY_ETF_DATA}/cache/token_{YYYYMMDD}.json     (KST date)
  KIS masters      {LEGACY_ETF_DATA}/cache/master/{exch}mst_{YYYYMMDD}.parquet
  OpenFIGI DB      {LEGACY_DB}/ETF_INAV_MONITOR.db
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from collector import krx_fetch
from collector.krx_prep import load_csv

_KST = timezone(timedelta(hours=9))

LEGACY_CONFIG = Path(os.environ.get("COLLECTOR_LEGACY_CONFIG", "/srv/legacy/config"))
LEGACY_ETF_DATA = Path(os.environ.get("COLLECTOR_LEGACY_ETF_DATA", "/srv/legacy/etf_data"))
LEGACY_DB = Path(os.environ.get("COLLECTOR_LEGACY_DB", "/srv/legacy/db"))

CACHE_DIR = Path(os.environ.get("COLLECTOR_CACHE_DIR", "/app/.cache"))
MASTER_CACHE_DIR = CACHE_DIR / "master"
DB_DEST = CACHE_DIR / "kis_prices.db"
# Writable KRX self-fetch cache (mirrors the legacy cache filenames/format).
KRX_SELF_FETCH_DIR = CACHE_DIR / "krx"


def _env_flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "")


# COLLECTOR_ALLOW_FETCH=1 → when today's legacy KRX cache CSVs are missing, fetch
#   them ourselves via the verbatim KRX functions. =0 restores Phase-1 behavior
#   (legacy cache only; never touch KRX).
ALLOW_FETCH = _env_flag("COLLECTOR_ALLOW_FETCH", "0")
# COLLECTOR_FORCE_FETCH=1 → always self-fetch even when today's legacy cache is
#   present (testing/drill). Ignored unless COLLECTOR_ALLOW_FETCH=1.
FORCE_FETCH = _env_flag("COLLECTOR_FORCE_FETCH", "0")

LEGACY_TOKEN_DIR = LEGACY_ETF_DATA / "cache"
LEGACY_MASTER_DIR = LEGACY_ETF_DATA / "cache" / "master"
LEGACY_KRX_ROOT = LEGACY_ETF_DATA / "output" / "results" / "etf_inav"
LEGACY_DB_FILE = LEGACY_DB / "ETF_INAV_MONITOR.db"
CONFIG_FILE = LEGACY_CONFIG / "etf_inav_config.json"

KRX_FILES = ("krx_etf_pdf_{d}.csv", "krx_etf_list_{d}.csv", "krx_etf_market_{d}.csv")


def _log(msg: str) -> None:
    print(f"[legacy] {msg}", file=sys.stderr, flush=True)


def kst_today() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


def module_date() -> str:
    """The YYYYMMDD the verbatim modules derive from ``datetime.now()`` — this
    is what KisAuth/KisMaster name their cache files after. May differ from the
    KST date if the container clock is UTC, so we stage copies under this name.
    """
    return datetime.now().strftime("%Y%m%d")


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── config ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _log(f"config read failed ({CONFIG_FILE}): {exc!r}; using empty config")
        return {}


# ── KIS token (piggyback prod; NEVER issue) ────────────────────────────
def _token_is_valid(path: Path) -> tuple[bool, float | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError):
        return False, None
    expires_at = data.get("expires_at")
    if not data.get("access_token") or not isinstance(expires_at, (int, float)):
        return False, None
    return (expires_at > time.time() + 60), float(expires_at)


def sync_token() -> tuple[bool, float | None]:
    """Copy the prod token into the writable cache under the name KisAuth will
    look for. Returns (valid, expires_at). When no valid legacy token exists we
    return False so the caller skips REST (prices go stale) — we must never let
    KisAuth issue a fresh token against the shared app key.
    """
    dest = CACHE_DIR / f"token_{module_date()}.json"
    # If a still-valid token is already staged, keep it.
    if dest.exists():
        ok, exp = _token_is_valid(dest)
        if ok:
            return True, exp
    candidates = [
        LEGACY_TOKEN_DIR / f"token_{kst_today()}.json",
        LEGACY_TOKEN_DIR / f"token_{module_date()}.json",
    ]
    for src in candidates:
        if not src.exists():
            continue
        ok, exp = _token_is_valid(src)
        if not ok:
            _log(f"legacy token {src.name} present but expired/invalid; skipping")
            continue
        try:
            shutil.copyfile(src, dest)
        except OSError as exc:
            _log(f"token copy failed {src} -> {dest}: {exc!r}")
            continue
        _log(f"token staged from {src.name} (ttl {int(exp - time.time())}s)")
        return True, exp
    _log("no valid legacy token found; KIS REST disabled (prices will be stale)")
    return False, None


# ── KIS master parquet cache (avoid re-download) ───────────────────────
def sync_master() -> int:
    """Copy the latest available master parquet per prefix into the writable
    master cache, renamed to today's module date, so KisMaster/futureoption
    master load from cache instead of downloading. Returns files staged.
    """
    ensure_dirs()
    staged = 0
    md = module_date()
    if not LEGACY_MASTER_DIR.exists():
        _log(f"legacy master dir absent: {LEGACY_MASTER_DIR}")
        return 0
    prefixes = (
        "nasmst", "nysmst", "amsmst", "hksmst", "shsmst", "szsmst", "tsemst",
        "fo_stk_code_mts",
    )
    for prefix in prefixes:
        matches = sorted(LEGACY_MASTER_DIR.glob(f"{prefix}_*.parquet"))
        if not matches:
            continue
        src = matches[-1]  # latest by date-suffixed name
        dest = MASTER_CACHE_DIR / f"{prefix}_{md}.parquet"
        if dest.exists():
            staged += 1
            continue
        try:
            shutil.copyfile(src, dest)
            staged += 1
        except OSError as exc:
            _log(f"master copy failed {src.name}: {exc!r}")
    _log(f"master parquet staged={staged} (dir={MASTER_CACHE_DIR})")
    return staged


# ── OpenFIGI SQLite DB (needs write for WAL → copy) ────────────────────
def sync_db() -> Path | None:
    ensure_dirs()
    if not LEGACY_DB_FILE.exists():
        _log(f"legacy DB absent: {LEGACY_DB_FILE}; OpenFIGI cache empty")
        return None
    if not DB_DEST.exists():
        try:
            shutil.copyfile(LEGACY_DB_FILE, DB_DEST)
            _log(f"DB staged -> {DB_DEST}")
        except OSError as exc:
            _log(f"DB copy failed: {exc!r}")
            return None
    return DB_DEST


# ── KRX inputs (PDF / list / market CSVs) ──────────────────────────────
def _dir_has_all(day_dir: Path, date: str) -> bool:
    return all((day_dir / name.format(d=date)).exists() for name in KRX_FILES)


def _latest_complete_date() -> str | None:
    if not LEGACY_KRX_ROOT.exists():
        return None
    dates = sorted(
        (p.name for p in LEGACY_KRX_ROOT.iterdir() if p.is_dir() and p.name.isdigit()),
        reverse=True,
    )
    for date in dates:
        if _dir_has_all(LEGACY_KRX_ROOT / date, date):
            return date
    return None


def _covers(day_dir: Path, date: str, tickers: list[str]) -> bool:
    """해당 캐시 dir의 ETF 목록(krx_etf_list)이 타깃 티커를 전부 포함하는지."""
    try:
        df = load_csv(day_dir / f"krx_etf_list_{date}.csv")
        listed = {str(v).strip().upper() for v in df["ISU_SRT_CD"]}
    except Exception:  # noqa: BLE001 - 읽기 실패 = 미커버로 간주(기존 규칙 유지)
        return False
    return {t.upper() for t in tickers} <= listed


def wire_holiday_dir() -> None:
    """verbatim holiday_calendar 싱글턴의 base_dir(Windows 경로 기본값)을
    컨테이너 마운트 경로로 교체한다 (모듈 무수정 — 인스턴스 속성만 주입)."""
    from etf_inav.data_sources import holiday_calendar

    holiday_dir = Path(os.environ.get("HOLIDAY_DIR", "/srv/legacy/holidays"))
    holiday_calendar._default.base_dir = holiday_dir
    holiday_calendar._default._cache.clear()


def load_krx_inputs(
    run_date: str, target_tickers: list[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    """Return (pdf_df, etf_list_df, market_df, basis_date, source).

    source is:
      * ``SELF_FETCH``   — fetched fresh from KRX into the writable cache
        (COLLECTOR_ALLOW_FETCH=1 and today's legacy cache is missing, or
        COLLECTOR_FORCE_FETCH=1).
      * ``LEGACY_CACHE`` — today's legacy cache CSVs are present.
      * ``STALE_CACHE``  — fell back to the latest available legacy date.

    When COLLECTOR_ALLOW_FETCH=0 the KRX network is never touched (Phase-1
    behavior): only LEGACY_CACHE/STALE_CACHE are returned.
    """
    tickers = list(target_tickers or [])
    legacy_today = _dir_has_all(LEGACY_KRX_ROOT / run_date, run_date)

    # SELF_FETCH: today's legacy cache missing (or forced) and fetching allowed.
    if ALLOW_FETCH and (FORCE_FETCH or not legacy_today):
        reason = "forced" if FORCE_FETCH else "legacy cache missing"
        _log(f"KRX self-fetch ({reason}) for {run_date} -> {KRX_SELF_FETCH_DIR}")
        try:
            pdf_df, etf_list_df, market_df = krx_fetch.fetch_krx_inputs(
                run_date,
                tickers,
                KRX_SELF_FETCH_DIR,
                verify_ssl=False,  # matches prod (Somansa CA baked)
                timeout=10,
            )
            _log(
                f"KRX inputs loaded basis={run_date} source=SELF_FETCH "
                f"pdf_rows={len(pdf_df)} list_rows={len(etf_list_df)} market_rows={len(market_df)}"
            )
            return pdf_df, etf_list_df, market_df, run_date, "SELF_FETCH"
        except Exception as exc:  # noqa: BLE001 - fall back to legacy cache
            _log(f"KRX self-fetch failed ({exc!r}); falling back to legacy cache")

    # SELF_CACHE: 오늘자 셀프캐시가 이미 있고, 레거시(구시스템 마지막 아침 목록)는
    # 타깃을 다 못 덮는데 셀프캐시는 덮는 경우 → 셀프캐시 우선.
    # 신규 ETF 편입 직후 재기동 시 편입분이 사라지는 후퇴 방지(2026-07-16 0199C0 사례).
    self_dir = KRX_SELF_FETCH_DIR / run_date
    if tickers and _dir_has_all(self_dir, run_date):
        if _covers(self_dir, run_date, tickers) and not (
            legacy_today and _covers(LEGACY_KRX_ROOT / run_date, run_date, tickers)
        ):
            pdf_df = load_csv(self_dir / f"krx_etf_pdf_{run_date}.csv")
            etf_list_df = load_csv(self_dir / f"krx_etf_list_{run_date}.csv")
            market_df = load_csv(self_dir / f"krx_etf_market_{run_date}.csv")
            _log(
                f"KRX inputs loaded basis={run_date} source=SELF_CACHE "
                f"pdf_rows={len(pdf_df)} list_rows={len(etf_list_df)} market_rows={len(market_df)}"
            )
            return pdf_df, etf_list_df, market_df, run_date, "SELF_CACHE"

    basis = run_date
    source = "LEGACY_CACHE"
    if not legacy_today:
        fallback = _latest_complete_date()
        if fallback is None:
            raise FileNotFoundError(
                f"No legacy KRX inputs found under {LEGACY_KRX_ROOT} "
                f"(today={run_date}); cannot build engine."
            )
        basis = fallback
        source = "STALE_CACHE"
        _log(f"today's KRX inputs missing; falling back to {fallback} (STALE_CACHE)")

    day_dir = LEGACY_KRX_ROOT / basis
    pdf_df = load_csv(day_dir / f"krx_etf_pdf_{basis}.csv")
    etf_list_df = load_csv(day_dir / f"krx_etf_list_{basis}.csv")
    market_df = load_csv(day_dir / f"krx_etf_market_{basis}.csv")
    _log(
        f"KRX inputs loaded basis={basis} source={source} "
        f"pdf_rows={len(pdf_df)} list_rows={len(etf_list_df)} market_rows={len(market_df)}"
    )
    return pdf_df, etf_list_df, market_df, basis, source
