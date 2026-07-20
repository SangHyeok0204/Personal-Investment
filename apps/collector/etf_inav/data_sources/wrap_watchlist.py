"""WRAP 워치리스트 — 업로드 PDF 종목의 데이장 가격을 받아 대시보드용 산출물을 emit.

한 곳(streaming 프로세스)에서 전부 처리한다(별도 wrap_writer 프로세스 불필요):
  1) 고정 PDF(TORUS_PDF / AICORETECH_PDF) 의 ticker·비중·전일종가 읽기
  2) ticker -> (거래소,심볼) 해소(KisMaster) → KIS 데이장 가격 수신(self.rest 재사용)
  3) 전일종가 대비 수익률 계산
  4) emit:
     - wrap.js          (window.__WRAP__)        대시보드 WRAP 탭이 직접 폴링
     - wrap_prices.js   (window.__WRAP_PRICES__)  펀드별 원시 가격 기록(확장/디버깅용)
     - wrap_history.csv (append)                  포트폴리오별 실시간 수익률 시계열(시간대별 추이)

streaming 의 self.master / self.rest 재사용. iNAV / self.instruments / WS 와 독립 — 실패 무영향.
가격은 live(last)만 받는다(전일종가 분모는 사람이 PDF 에 입력).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from etf_inav.workflows.batch import (
    build_price_targets,
    normalize_fallback_snapshots,
    normalize_requested_snapshots,
)

# 포폴 정의(고정경로·이름·PDF경로)와 출력경로의 단일 출처.
WRAP_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / "모니터링" / "실시간 모니터링" / "TORUS_코어테크_모니터" / "config.json"
)

# 현금행 마커(PDF ticker). 가격 해소 없이 수익률 0%·커버로 집계한다.
CASH_TICKERS = {"CASH", "현금", "KRW", "USD"}


def _read_pdf_rows(path: Path):
    """표준 PDF(ticker|name|weight_pct|prev_close|exchange) -> 보유 list."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(header) if h}

    def cell(r, c):
        return r[idx[c]] if c in idx and idx[c] < len(r) else None

    def to_float(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = []
    for r in rows[1:]:
        if not r:
            continue
        tk = cell(r, "ticker")
        tks = str(tk).strip() if tk is not None else ""
        if not tks or " " in tks or len(tks) > 10 or not tks.isascii():
            continue  # 안내문구·빈 행 스킵
        exch = cell(r, "exchange")
        out.append({
            "ticker": tks.upper(),
            "name": cell(r, "name"),
            "weight_pct": to_float(cell(r, "weight_pct")) or 0.0,
            "prev_close": to_float(cell(r, "prev_close")),
            "exchange": str(exch).strip().upper() if exch else None,
        })
    return out


class WrapWatchlist:
    def __init__(self, master, rest, us_daytime_mode: str = "auto"):
        self.master = master
        self.rest = rest
        self.us_daytime_mode = us_daytime_mode
        self._resolved: dict[str, tuple[str, str] | None] = {}  # ticker -> (exchange, symbol)|None

    def _resolve(self, ticker: str, hint: str | None):
        if ticker in self._resolved:
            return self._resolved[ticker]
        res = None
        try:
            hit = self.master.lookup(ticker, exchange_hint=hint)
            if hit:
                res = (hit.code.upper(), hit.symbol.upper())
        except Exception as exc:
            print(f"[wrap_watchlist] resolve {ticker} 실패: {exc}", file=sys.stderr)
        if res is None:
            print(f"[wrap_watchlist] 미해소 티커(스킵): {ticker}", file=sys.stderr)
        self._resolved[ticker] = res
        return res

    def _fetch_prices(self, rows_by_pf: dict) -> dict:
        """모든 포폴 티커의 데이장 가격 1회 조회 -> symbol -> {last, tradeTime, exchange}."""
        instruments: dict[tuple[str, str], None] = {}
        for rows in rows_by_pf.values():
            for h in rows:
                if str(h["ticker"]).upper() in CASH_TICKERS:
                    continue  # 현금은 가격 해소 불필요(미해소 로그 소음 방지)
                r = self._resolve(h["ticker"], h["exchange"])
                if r:
                    instruments[r] = None
        if not instruments:
            return {}
        inst_list = [{"exchange": ex, "ticker": sym} for (ex, sym) in instruments]

        target_rows, _ = build_price_targets(inst_list, self.us_daytime_mode)
        targets = [(row["request_exchange"], row["ticker"]) for row in target_rows]
        requested = self.rest.snapshots(
            targets, batch_delay_seconds=0.05, max_workers=8, overseas_batch_size=10
        )
        snaps, fallback = normalize_requested_snapshots(target_rows, requested)
        if fallback:
            fb = self.rest.snapshots(
                [(r["exchange"], r["ticker"]) for r in fallback],
                batch_delay_seconds=0.05, max_workers=8, overseas_batch_size=10,
            )
            snaps.extend(normalize_fallback_snapshots(fallback, fb))

        price_by_symbol: dict[str, dict] = {}
        for s in snaps:
            sym = (s.get("symbol") or "").upper()
            last = s.get("last")
            if not sym or last is None:
                continue
            try:
                last = float(last)
            except (TypeError, ValueError):
                continue
            price_by_symbol[sym] = {
                "last": last,
                "tradeTime": s.get("trade_time") or s.get("tradeTime"),
                "exchange": (s.get("exchange") or "").upper(),
            }
        return price_by_symbol

    def run_cycle(self) -> None:
        cfg = json.loads(WRAP_CONFIG_PATH.read_text(encoding="utf-8"))
        pdfs = cfg.get("portfolio_pdfs", {})
        names = cfg.get("portfolio_names", {})
        order = cfg.get("portfolios", list(pdfs.keys()))

        # 종목 분류(대/중/소) 사전 — classification.json(매일 08:00 추출) 캐시 로드.
        # 키 = ticker.upper(). 없으면 빈 dict(분류는 옵션, 실패 무영향).
        classification: dict = {}
        cls_path = cfg.get("classification_json")
        if cls_path:
            try:
                from etf_inav.data_sources.wrap_classification import load_classification
                classification = load_classification(Path(cls_path))
            except Exception as exc:
                print(f"[wrap_watchlist] 분류 로드 실패: {exc}", file=sys.stderr)

        rows_by_pf = {
            key: (_read_pdf_rows(Path(path)) if Path(path).exists() else [])
            for key, path in pdfs.items()
        }
        price_by_symbol = self._fetch_prices(rows_by_pf)

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ts = int(time.time() * 1000)

        wrap_prices_portfolios: dict[str, dict] = {}
        wrap_portfolios: list[dict] = []
        for key in [k for k in order if k in rows_by_pf] + [k for k in rows_by_pf if k not in order]:
            rows = rows_by_pf[key]
            prices: dict[str, dict] = {}
            holdings: list[dict] = []
            ret_sum = mw = tw = 0.0
            nm = 0
            for h in rows:
                is_cash = str(h["ticker"]).upper() in CASH_TICKERS
                r = self._resolved.get(h["ticker"])
                info = price_by_symbol.get(r[1]) if r else None
                live = info["last"] if info else None
                if info:
                    prices[h["ticker"]] = info
                prev = h["prev_close"]
                if is_cash:
                    # 현금은 자기 통화 기준 불변 → 수익률 0%, 커버로 집계(0 기여)
                    ret, contrib, live, matched = 0.0, 0.0, prev, True
                else:
                    ret = ((live / prev) - 1.0) * 100.0 if (live is not None and prev) else None
                    contrib = (h["weight_pct"] / 100.0 * ret) if ret is not None else None
                    matched = live is not None
                tw += h["weight_pct"]
                if contrib is not None:
                    ret_sum += contrib
                    mw += h["weight_pct"]
                    nm += 1
                cls = classification.get(str(h["ticker"]).upper(), {})
                holdings.append({
                    "ticker": h["ticker"],
                    "name": h["name"],
                    "exchange": h["exchange"] or (info["exchange"] if info else None),
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
                })
            holdings.sort(key=lambda x: x["weight_pct"] or 0, reverse=True)
            wrap_prices_portfolios[key] = {"name": names.get(key, key), "prices": prices}
            wrap_portfolios.append({
                "key": key,
                "name": names.get(key, key),
                "return_pct": ret_sum,
                "matched_weight_pct": mw,
                "total_weight_pct": tw,
                "n_matched": nm,
                "n_total": len(rows),
                "holdings": holdings,
            })

        # emit wrap.js (대시보드) + wrap_prices.js (원시 가격기록)
        self._write_js(
            {"date": datetime.now().strftime("%Y%m%d"), "generatedAt": generated_at,
             "timestamp": ts, "priceGeneratedAt": generated_at, "portfolios": wrap_portfolios},
            Path(cfg["wrap_js_out"]), "__WRAP__", "__onWrap__",
        )
        self._write_js(
            {"generatedAt": generated_at, "timestamp": ts, "portfolios": wrap_prices_portfolios},
            Path(cfg["wrap_prices_js"]), "__WRAP_PRICES__", "__onWrapPrices__",
        )

        # 포트폴리오별 실시간 수익률 시계열 적재(시간대별 추이용). 실패해도 cycle 무영향.
        try:
            self._append_history(cfg, wrap_portfolios, generated_at, ts)
        except Exception as exc:
            print(f"[wrap_watchlist] history append 실패: {exc}", file=sys.stderr)

    @staticmethod
    def _append_history(cfg: dict, portfolios: list[dict], generated_at: str, ts: int) -> None:
        """포트폴리오별 실시간 수익률을 시계열 CSV 에 1행씩 append.

        경로: config 의 ``wrap_history_csv`` 우선, 없으면 wrap.js 옆 ``wrap_history.csv``.
        한 줄 = (한 사이클, 한 포트폴리오). Excel 한글 호환 위해 utf-8-sig.
        """
        import csv

        if not portfolios:
            return
        out = Path(
            cfg.get("wrap_history_csv")
            or Path(cfg["wrap_js_out"]).with_name("wrap_history.csv")
        )
        new_file = not out.exists()
        with out.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow([
                    "timestamp", "generatedAt", "key", "name",
                    "return_pct", "matched_weight_pct", "n_matched", "n_total",
                ])
            for p in portfolios:
                w.writerow([
                    ts, generated_at, p["key"], p["name"],
                    round(p["return_pct"], 6), round(p["matched_weight_pct"], 6),
                    p["n_matched"], p["n_total"],
                ])

    @staticmethod
    def _write_js(payload, out_path: Path, var: str, cb: str) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str)
        text = (
            f"window.{var}=" + body + ";\n"
            f"if(typeof window.{cb}==='function')window.{cb}(window.{var});\n"
        )
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, out_path)
