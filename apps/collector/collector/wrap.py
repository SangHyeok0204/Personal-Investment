"""WRAP 포트폴리오 실시간 수익률 — collector 어댑테이션.

구시스템 파이프라인(wrap_source_refresh 08:50 PDF 재기록 → wrap_watchlist 15s
cycle → wrap.js emit)을 읽기전용 컨테이너에 맞게 재구성한다:

  * S: 는 전부 :ro — PDF/JS/CSV 를 일절 기록하지 않는다 (read-only invariant).
  * 운용역 소스 xlsx(``이상 포트폴리오 수익률.xlsx``)를 **직접** 읽어 보유목록을
    메모리에서 구성한다. 검증 규칙(기준일 신선도·비중 수치·합·스케일 판별)은
    ``wrap_source_refresh.refresh_portfolio_pdf`` 와 동일하게 적용하고, 검증
    실패 시 구시스템이 마지막으로 기록한 포트폴리오 PDF(xlsx)로 폴백한다.
  * 분류(대/중/소)는 소스 xlsx 의 ``종목_분류`` 시트에서 직접 읽고(mtime 캐시),
    실패 시 classification.json 폴백.
  * 티커 해소·가격 수신은 verbatim ``WrapWatchlist`` 의 ``_resolve`` /
    ``_fetch_prices`` 를 재사용한다 (KisMaster + rest.snapshots).

페이로드 스키마는 구 wrap.js(window.__WRAP__)와 동일 + 부가 필드
(``holdings_source``, ``basis_date``)만 추가.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from etf_inav.data_sources.wrap_classification import (
    _read_classification_sheet,
    load_classification,
)
from etf_inav.data_sources.wrap_source_refresh import (
    MAX_BASIS_AGE_DAYS,
    WEIGHT_SUM_MIN,
    WEIGHT_SUM_TOLERANCE,
    _is_num,
    _read_source,
)
from etf_inav.data_sources.wrap_watchlist import (
    CASH_TICKERS,
    WrapWatchlist,
    _read_pdf_rows,
)

WRAP_CONFIG_DIR = Path(
    os.environ.get("COLLECTOR_WRAP_CONFIG", "/srv/legacy/wrap_config")
)
WRAP_DATA_DIR = Path(os.environ.get("COLLECTOR_WRAP_DATA", "/srv/legacy/wrap_data"))
WRAP_SOURCE_DIR = Path(
    os.environ.get("COLLECTOR_WRAP_SOURCE", "/srv/legacy/wrap_source")
)

# 소스/config 재확인 주기(초). 실제 xlsx 재읽기는 mtime 변경 시에만.
SOURCE_CHECK_S = 60.0

# config.json 의 Windows 절대경로 → 컨테이너 마운트 경로 접두사 맵.
_WIN_PREFIX_MAP: list[tuple[str, Path]] = [
    ("S:\\GE\\raw\\data\\TORUS_코어테크_모니터", WRAP_DATA_DIR),
    (
        "S:\\GE\\Wonjae\\02_운용펀드_글로벌\\(Wrap) 한국투자 미국 AI코어테크랩\\4_수익률",
        WRAP_SOURCE_DIR,
    ),
]


def _log(msg: str) -> None:
    print(f"[wrap] {msg}", file=sys.stderr, flush=True)


def map_windows_path(win_path: str) -> Path | None:
    """config.json 의 ``S:\\...`` 절대경로를 컨테이너 :ro 마운트 경로로 변환."""
    raw = str(win_path or "").strip()
    if not raw:
        return None
    for prefix, root in _WIN_PREFIX_MAP:
        if raw.lower().startswith(prefix.lower()):
            rest = raw[len(prefix):].lstrip("\\/")
            return root / rest.replace("\\", "/") if rest else root
    return None


def holdings_from_source(
    src_path: Path, sheet: str
) -> tuple[list[dict] | None, str]:
    """운용역 소스 시트 → wrap_watchlist 보유행(list) 를 메모리에서 구성.

    검증 규칙은 ``wrap_source_refresh.refresh_portfolio_pdf`` 와 동일 (파일
    기록·sidecar 만 없음). 실패 시 (None, 사유) — 호출부가 PDF 폴백.
    """
    rows, basis_date = _read_source(src_path, sheet)
    if basis_date is None:
        return None, "no_basis_date(F2)"
    if (datetime.now().date() - basis_date).days > MAX_BASIS_AGE_DAYS:
        return None, f"stale_basis({basis_date})"

    securities = [r for r in rows if not r["is_cash"]]
    cash_rows = [r for r in rows if r["is_cash"]]
    if not securities:
        return None, "no_securities"
    bad = [r["ticker"] or r["name"] for r in securities if not _is_num(r["weight"])]
    if bad:
        return None, f"non_numeric_weight(n={len(bad)})"
    cash_w_raw = sum(r["weight"] for r in cash_rows if _is_num(r["weight"]))
    sec_w_raw = sum(r["weight"] for r in securities)
    total_raw = sec_w_raw + cash_w_raw

    # 스케일 판별: 분수(합 0.75~1.05) → ×100, 퍼센트(합 75~105) → ×1, 그 외 거부.
    if WEIGHT_SUM_MIN / 100.0 <= total_raw <= 1.0 + 0.05:
        factor = 100.0
    elif WEIGHT_SUM_MIN <= total_raw <= 100.0 + 5.0:
        factor = 1.0
    else:
        return None, f"weight_sum_off({total_raw:.4f})"
    final_total = total_raw * factor
    if not (WEIGHT_SUM_MIN <= final_total <= 100.0 + WEIGHT_SUM_TOLERANCE):
        return None, f"weight_sum_off({final_total:.3f}%)"

    out: list[dict] = []
    for r in securities:
        prev = r["prev"] if (_is_num(r["prev"]) and r["prev"] > 0) else None
        out.append(
            {
                "ticker": r["ticker"],
                "name": "" if r["name"] is None else str(r["name"]),
                "weight_pct": round(r["weight"] * factor, 6),
                "prev_close": prev,
                "exchange": None,  # WrapWatchlist 가 KisMaster 로 자동 해소
            }
        )
    if cash_rows and _is_num(cash_rows[0]["weight"]):
        out.append(
            {
                "ticker": "CASH",
                "name": "현금",
                "weight_pct": round(cash_w_raw * factor, 6),
                "prev_close": None,
                "exchange": None,
            }
        )
    return out, basis_date.strftime("%Y%m%d")


class WrapCollector:
    def __init__(self, master, rest, us_daytime_mode: str = "auto") -> None:
        self.watchlist = WrapWatchlist(master, rest, us_daytime_mode)
        self.config: dict = {}
        self._config_mtime: float | None = None
        self._holdings: dict[str, list[dict]] = {}
        self._holdings_meta: dict[str, dict] = {}
        self._last_source_check = 0.0
        self._cls_cache: dict = {}
        self._cls_mtime: float | None = None

    # ── config / 보유목록 / 분류 ───────────────────────────────────────
    def _load_config(self) -> dict:
        path = WRAP_CONFIG_DIR / "config.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return self.config
        if self.config and self._config_mtime == mtime:
            return self.config
        try:
            self.config = json.loads(path.read_text(encoding="utf-8"))
            self._config_mtime = mtime
        except Exception as exc:  # noqa: BLE001 - last-good 유지
            _log(f"config 읽기 실패: {exc!r}")
        return self.config

    def _refresh_holdings(self, cfg: dict) -> None:
        now = time.time()
        if self._holdings and now - self._last_source_check < SOURCE_CHECK_S:
            return
        self._last_source_check = now
        pdfs = cfg.get("portfolio_pdfs", {})
        sources = cfg.get("wrap_sources", {})
        keys = list(cfg.get("portfolios") or []) or list(pdfs.keys())
        for key in keys:
            src = sources.get(key) or {}
            src_path = map_windows_path(src.get("path", ""))
            sheet = src.get("sheet", "")
            loaded: list[dict] | None = None
            meta: dict = {}
            if src_path is not None and sheet and src_path.exists():
                try:
                    src_mtime = src_path.stat().st_mtime
                except OSError:
                    src_mtime = None
                prev = self._holdings_meta.get(key) or {}
                if (
                    prev.get("source") == "SOURCE"
                    and prev.get("src_mtime") == src_mtime
                    and key in self._holdings
                ):
                    continue  # 소스 무변경 — 기존 보유목록 유지
                try:
                    holdings, basis = holdings_from_source(src_path, sheet)
                except Exception as exc:  # noqa: BLE001
                    holdings, basis = None, f"read_error: {exc}"
                if holdings:
                    loaded = holdings
                    meta = {"source": "SOURCE", "basis": basis, "src_mtime": src_mtime}
                    _log(f"{key}: 소스 적용 basis={basis} n={len(holdings)}")
                else:
                    _log(f"{key}: 소스 검증 실패({basis}) — PDF 폴백")
            if loaded is None and key not in self._holdings:
                pdf_path = map_windows_path(pdfs.get(key, ""))
                if pdf_path is not None and pdf_path.exists():
                    try:
                        loaded = _read_pdf_rows(pdf_path)
                        meta = {"source": "PDF_FALLBACK", "basis": None, "src_mtime": None}
                        _log(f"{key}: PDF 폴백 적용 n={len(loaded)}")
                    except Exception as exc:  # noqa: BLE001
                        _log(f"{key}: PDF 읽기 실패: {exc!r}")
            if loaded:
                self._holdings[key] = loaded
                self._holdings_meta[key] = meta

    def _classification(self, cfg: dict) -> dict:
        cs = cfg.get("classification_source") or {}
        src_path = map_windows_path(cs.get("path", ""))
        sheet = cs.get("sheet") or "종목_분류"
        if src_path is not None and src_path.exists():
            try:
                mtime = src_path.stat().st_mtime
                if self._cls_mtime == mtime and self._cls_cache:
                    return self._cls_cache
                mapping = _read_classification_sheet(src_path, sheet)
                if mapping:
                    self._cls_cache = mapping
                    self._cls_mtime = mtime
                    return mapping
            except Exception as exc:  # noqa: BLE001
                _log(f"분류 시트 읽기 실패: {exc!r}")
        cj = map_windows_path(cfg.get("classification_json", ""))
        if cj is not None:
            data = load_classification(cj)
            if data:
                return data
        return self._cls_cache

    # ── 페이로드 (구 wrap_watchlist.run_cycle 의 집계와 동일) ──────────
    def build_payload(self) -> dict | None:
        cfg = self._load_config()
        if not cfg:
            return None
        self._refresh_holdings(cfg)
        if not self._holdings:
            return None
        names = cfg.get("portfolio_names", {})
        order = cfg.get("portfolios", list(self._holdings.keys()))
        classification = self._classification(cfg)
        rows_by_pf = self._holdings
        price_by_symbol = self.watchlist._fetch_prices(rows_by_pf)

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ts = int(time.time() * 1000)
        portfolios: list[dict] = []
        for key in [k for k in order if k in rows_by_pf] + [
            k for k in rows_by_pf if k not in order
        ]:
            rows = rows_by_pf[key]
            holdings: list[dict] = []
            ret_sum = mw = tw = 0.0
            nm = 0
            for h in rows:
                is_cash = str(h["ticker"]).upper() in CASH_TICKERS
                r = self.watchlist._resolved.get(h["ticker"])
                info = price_by_symbol.get(r[1]) if r else None
                live = info["last"] if info else None
                prev = h["prev_close"]
                if is_cash:
                    # 현금은 자기 통화 기준 불변 → 수익률 0%, 커버로 집계(0 기여)
                    ret, contrib, live, matched = 0.0, 0.0, prev, True
                else:
                    ret = (
                        ((live / prev) - 1.0) * 100.0
                        if (live is not None and prev)
                        else None
                    )
                    contrib = (
                        (h["weight_pct"] / 100.0 * ret) if ret is not None else None
                    )
                    matched = live is not None
                tw += h["weight_pct"]
                if contrib is not None:
                    ret_sum += contrib
                    mw += h["weight_pct"]
                    nm += 1
                cls = classification.get(str(h["ticker"]).upper(), {})
                holdings.append(
                    {
                        "ticker": h["ticker"],
                        "name": h["name"],
                        "exchange": h["exchange"]
                        or (info["exchange"] if info else None),
                        "weight_pct": h["weight_pct"],
                        "prev_close": prev,
                        "livePrice": live,
                        "return_pct": ret,
                        "contribution_pct": contrib,
                        "matched": matched,
                        "tradeTime": info["tradeTime"] if info else None,
                        "cat1": cls.get("cat1") or "",
                        "cat2": cls.get("cat2") or "",
                        "cat3": cls.get("cat3") or "",
                    }
                )
            holdings.sort(key=lambda x: x["weight_pct"] or 0, reverse=True)
            meta = self._holdings_meta.get(key) or {}
            portfolios.append(
                {
                    "key": key,
                    "name": names.get(key, key),
                    "return_pct": ret_sum,
                    "matched_weight_pct": mw,
                    "total_weight_pct": tw,
                    "n_matched": nm,
                    "n_total": len(rows),
                    "holdings": holdings,
                    "holdings_source": meta.get("source"),
                    "basis_date": meta.get("basis"),
                }
            )
        if not portfolios:
            return None
        return {
            "date": datetime.now().strftime("%Y%m%d"),
            "generatedAt": generated_at,
            "timestamp": ts,
            "priceGeneratedAt": generated_at,
            "portfolios": portfolios,
        }
