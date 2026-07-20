"""Deterministic replay-parity harness for the ported ETF iNAV engine (plan MF-B).

Feeds RECORDED engine inputs (reconstructed from each capture record's
``components`` payload) into the VERBATIM ``etf_inav.core.engine.InavEngine``
and asserts the recomputed outputs match the RECORDED outputs.

Capture format
--------------
gzip JSONL, one paired record per tick, produced by a daemon that mirrors the
OLD production ``kis_inav.js`` + ``kis_inav_components.js`` emitters::

    {"captured_at": <iso8601>, "edge": <bool>,
     "inav":       <kis_inav.js payload>,             # per-ETF summary
     "components": <kis_inav_components.js payload>}   # per-ETF constituents + fxRates

``components.byEtf[ticker]`` carries per-constituent inputs *and* outputs:
``quantity`` / ``livePrice`` / ``basePrice`` / ``fxRate`` / ``currency`` /
``exchange`` / ``isCash`` (inputs) and ``krwPrice`` / ``liveValueKrw`` /
``valueSource`` (outputs). ``components.fxRates`` is the global FX table and
``components.byEtf[ticker].inavTotalKrw`` the per-ETF total.
``inav.byCode[ticker]`` carries ``inav_per_share`` and the integer counts.

Engine path exercised
---------------------
For each record we build a real ``InavEngine`` from a reconstructed prepared-PDF
DataFrame + instrument map, seed it with ``set_fx_rates`` + per-ISIN
``update_price`` snapshots, then call ``compute()``. This drives the full
verbatim path: ``_prepare_etf_meta`` / ``_normalize_market`` / ``_build_base`` /
``_merge_snapshot`` / ``compute`` / ``_summarize``.

The only pieces NOT exercised are the collector's data-source fetchers (KIS/TWSE
REST, Naver FX, OpenFIGI ``resolve_instruments``) — collector plumbing, not the
iNAV engine under test — whose OUTPUTS we supply directly from the recorded
payload. Cash rows (원화현금 / setting-cash anchors) are KRX-provided anchors:
their ``liveValueKrw`` is fed as ``reference_value_krw`` and echoed by the
engine, so cash is a routing/pass-through check, not an arithmetic one. The
independently-recomputed quantities are the security rows
(``quantity × livePrice × fxRate × multiplier``) and the per-ETF aggregates.

Gate
----
Relative error <= 1e-9 on continuous fields (per-component ``krwPrice`` &
``liveValueKrw``; per-ETF ``inavTotalKrw`` & ``inav_per_share``); exact equality
on integer/enum fields (``component_count``, ``price_candidate_count``,
``priced_component_count``, ``isCash``, ``quantity``). Non-zero exit on any
breach. Tolerances are never loosened to pass: a systematic mismatch is a
genuine engine-port bug this harness exists to catch.

Usage
-----
    python -m collector.replay <capture.jsonl.gz> [--limit N] [--report path.json]

``--limit N`` samples N records spread evenly across the file (first..last).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys

import pandas as pd

from etf_inav.core.engine import (
    INAV_DIVISOR,
    KRW_CASH_CODE,
    SETTING_CASH_CODE,
    InavEngine,
)

REL_TOL = 1e-9
CASH_CODES = {KRW_CASH_CODE, SETTING_CASH_CODE}

CONTINUOUS_FIELDS = ("krwPrice", "liveValueKrw", "inavTotalKrw", "inav_per_share")
EXACT_FIELDS = (
    "component_count",
    "price_candidate_count",
    "priced_component_count",
    "isCash",
    "quantity",
)


# ── reconstruction ──────────────────────────────────────────────────────────
def _reconstruct_inputs(by_etf: dict) -> tuple[list[dict], dict, dict]:
    """Invert the recorded ``components`` payload back into engine inputs.

    Returns ``(pdf_rows, instruments_by_isin, price_by_isin)`` where ``pdf_rows``
    reconstructs the columns ``prepare_pdf_df`` would have produced for the KRX
    PDF, ``instruments_by_isin`` mirrors ``resolve_instruments`` output (ISIN →
    KIS exchange/currency), and ``price_by_isin`` mirrors the seeded REST/TWSE
    snapshots. Prices are keyed globally by ISIN exactly like the live engine.
    """
    pdf_rows: list[dict] = []
    instruments: dict[str, dict] = {}
    prices: dict[str, dict] = {}
    for ticker, etf in by_etf.items():
        etf_name = etf.get("etfName") or ""
        for comp in etf.get("components", []):
            isin = str(comp.get("isin") or "").upper()
            is_cash = bool(comp.get("isCash"))
            pdf_rows.append(
                {
                    "ETF_TICKER": ticker,
                    "ETF_NAME": etf_name,
                    # component_code (→ cash detection) derives from these.
                    "COMPST_ISU_CD": isin,
                    "COMPST_ISU_CD2": isin,
                    # compute() maps live/base prices by component_isin.
                    "component_isin": isin,
                    "quantity": comp.get("quantity"),
                    # Only consumed by the engine for cash anchors.
                    "reference_value_krw": comp.get("liveValueKrw") if is_cash else None,
                    # Drives price_candidate_count; non-cash rows are candidates.
                    "is_price_candidate": not is_cash,
                }
            )
            if is_cash:
                continue
            if isin not in instruments:
                instruments[isin] = {
                    "isin": isin,
                    "ticker": "",
                    "exchange": str(comp.get("exchange") or ""),
                    "currency": str(comp.get("currency") or ""),
                }
            # valueSource records whether a live tick existed. 'base_fallback'
            # means the live tick was absent, so feed last=None and let the
            # engine fall through to base_price (전일 종가).
            live_ok = comp.get("valueSource") == "qty_price_fx"
            prices[isin] = {
                "last": comp.get("livePrice") if live_ok else None,
                "base": comp.get("basePrice"),
                "currency": str(comp.get("currency") or "") or None,
            }
    return pdf_rows, instruments, prices


def _recomputed_krw_price(row: dict) -> float | None:
    """Per-unit KRW price the engine implies for a component row.

    Securities: ``live_price × fx_rate × multiplier`` (KFO futures ×10). Cash
    anchors have no per-unit price — their ``liveValueKrw`` is the whole amount,
    so the recorded ``krwPrice`` equals ``live_value_krw``.
    """
    if row["is_setting_cash"] or row["is_krw_cash"]:
        return row["live_value_krw"]
    multiplier = 10.0 if str(row.get("kis_exchange") or "").upper() == "KFO" else 1.0
    # Mirror the price the engine actually valued the row with: base_fallback
    # rows (off-hours overseas markets) use base_price (전일 종가); priced rows
    # use the live tick. So krwPrice compares against the same basis.
    if row.get("value_source") == "base_fallback":
        unit_price = row.get("base_price")
    else:
        unit_price = row.get("live_price")
    fx_rate = row.get("fx_rate")
    if unit_price is None or fx_rate is None:
        return None
    if isinstance(unit_price, float) and math.isnan(unit_price):
        return None
    if isinstance(fx_rate, float) and math.isnan(fx_rate):
        return None
    return unit_price * fx_rate * multiplier


# ── comparison ──────────────────────────────────────────────────────────────
def _rel_error(recomputed, recorded) -> float | None:
    """Relative error of ``recomputed`` vs the recorded reference value."""
    if recorded is None:
        return None
    try:
        rec = float(recorded)
        com = float(recomputed)
    except (TypeError, ValueError):
        return math.inf
    if math.isnan(rec):
        return None
    if math.isnan(com):
        return math.inf
    if rec == 0.0:
        return 0.0 if com == 0.0 else math.inf
    return abs(com - rec) / abs(rec)


class ParityTracker:
    def __init__(self) -> None:
        self.max_rel = {field: 0.0 for field in CONTINUOUS_FIELDS}
        self.worst = {field: None for field in CONTINUOUS_FIELDS}
        self.exact_mismatch = {field: 0 for field in EXACT_FIELDS}
        self.violations: list[dict] = []
        self.records = 0
        self.etfs = 0
        self.components = 0

    def continuous(self, field, recomputed, recorded, ident) -> None:
        rel = _rel_error(recomputed, recorded)
        if rel is None:
            return
        if rel > self.max_rel[field]:
            self.max_rel[field] = rel
            self.worst[field] = {**ident, "recomputed": recomputed, "recorded": recorded}
        if rel > REL_TOL:
            self.violations.append(
                {
                    "field": field,
                    "rel_error": rel,
                    "recomputed": recomputed,
                    "recorded": recorded,
                    **ident,
                }
            )

    def exact(self, field, recomputed, recorded, ident) -> None:
        if recomputed != recorded:
            self.exact_mismatch[field] += 1
            self.violations.append(
                {
                    "field": field,
                    "rel_error": None,
                    "recomputed": recomputed,
                    "recorded": recorded,
                    **ident,
                }
            )

    @property
    def passed(self) -> bool:
        cont_ok = all(v <= REL_TOL for v in self.max_rel.values())
        exact_ok = all(v == 0 for v in self.exact_mismatch.values())
        return cont_ok and exact_ok


def _check_record(record: dict, index: int, tracker: ParityTracker) -> None:
    comp_payload = record["components"]
    inav_payload = record["inav"]
    by_etf = comp_payload["byEtf"]
    fx_rates = comp_payload["fxRates"]
    inav_by_code = inav_payload.get("byCode") or {}
    captured_at = record.get("captured_at")

    pdf_rows, instruments, prices = _reconstruct_inputs(by_etf)
    prepared_pdf = pd.DataFrame(pdf_rows)
    engine = InavEngine(prepared_pdf, None, None, instruments=list(instruments.values()))
    engine.set_fx_rates(fx_rates)
    for isin, snapshot in prices.items():
        engine.update_price(isin, snapshot)
    comp_df, summ_df = engine.compute()

    eng_component = {
        (r["ETF_TICKER"], r["component_isin"]): r for r in comp_df.to_dict("records")
    }
    eng_summary = {r["ETF_TICKER"]: r for r in summ_df.to_dict("records")}

    tracker.records += 1
    for ticker, etf in by_etf.items():
        tracker.etfs += 1
        summ = eng_summary.get(ticker)
        recorded_code = inav_by_code.get(ticker, {})
        etf_ident = {"record": index, "captured_at": captured_at, "etf": ticker}

        # ── per-ETF aggregates ──
        if summ is not None:
            inav_ps = summ.get("inav_per_share")
            inav_total = (
                inav_ps * INAV_DIVISOR
                if inav_ps is not None and not (isinstance(inav_ps, float) and math.isnan(inav_ps))
                else None
            )
            tracker.continuous("inavTotalKrw", inav_total, etf.get("inavTotalKrw"), etf_ident)
            tracker.continuous(
                "inav_per_share", inav_ps, recorded_code.get("inav_per_share"), etf_ident
            )
            for field in ("component_count", "price_candidate_count", "priced_component_count"):
                if field in recorded_code:
                    tracker.exact(field, _as_int(summ.get(field)), recorded_code.get(field), etf_ident)

        # ── per-component ──
        for comp in etf.get("components", []):
            tracker.components += 1
            isin = str(comp.get("isin") or "").upper()
            row = eng_component.get((ticker, isin))
            ident = {**etf_ident, "isin": isin}
            if row is None:
                tracker.violations.append({"field": "missing_engine_row", "rel_error": math.inf, **ident})
                continue
            tracker.continuous("liveValueKrw", row.get("live_value_krw"), comp.get("liveValueKrw"), ident)
            tracker.continuous("krwPrice", _recomputed_krw_price(row), comp.get("krwPrice"), ident)
            tracker.exact("isCash", bool(row["is_setting_cash"] or row["is_krw_cash"]), bool(comp.get("isCash")), ident)
            tracker.exact("quantity", _as_float(row.get("quantity")), _as_float(comp.get("quantity")), ident)


def _as_int(value):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    try:
        if value is None:
            return None
        f = float(value)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ── record iteration / sampling ─────────────────────────────────────────────
def _iter_all(path: str):
    """Yield ``(index, record)`` for every complete JSON record.

    The capture file is appended live (~1/s), so its final gzip member may lack
    an end-of-stream marker and its last line may be half-written. Records before
    the tail decompress intact; we stop cleanly at the first decode error rather
    than raising, and skip a trailing partial line.
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        index = -1
        try:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # trailing partial line from the live writer
                index += 1
                yield index, record
        except (EOFError, OSError):
            return  # truncated final gzip member on a live-appended file


def _selected_indices(total: int, limit: int | None) -> set[int] | None:
    if not limit or limit >= total:
        return None
    if limit == 1:
        return {0}
    return {round(k * (total - 1) / (limit - 1)) for k in range(limit)}


# ── reporting ───────────────────────────────────────────────────────────────
def _print_summary(tracker: ParityTracker, path: str, records_total: int, sampled: bool) -> None:
    print("=== iNAV replay parity (plan MF-B) ===")
    print(f"file            : {path}")
    scope = "evenly sampled" if sampled else "all"
    print(f"records tested  : {tracker.records} / {records_total}  ({scope})")
    print(f"ETFs tested     : {tracker.etfs}")
    print(f"components tested: {tracker.components}")
    print(f"gate            : relative <= {REL_TOL:g} (continuous), exact (integer/enum)")
    print()
    print("max relative error per continuous field:")
    for field in CONTINUOUS_FIELDS:
        rel = tracker.max_rel[field]
        status = "OK" if rel <= REL_TOL else "FAIL"
        print(f"  {field:<16}: {rel:.3e}   [{status}]")
    print()
    print("exact-match fields (mismatch count):")
    for field in EXACT_FIELDS:
        count = tracker.exact_mismatch[field]
        status = "OK" if count == 0 else "FAIL"
        print(f"  {field:<22}: {count}   [{status}]")
    print()
    breaches = len(tracker.violations)
    print(f"rows exceeding gate: {breaches}")
    for violation in tracker.violations[:20]:
        rel = violation.get("rel_error")
        rel_txt = f"{rel:.3e}" if isinstance(rel, float) and math.isfinite(rel) else str(rel)
        print(
            f"  - {violation.get('field')} etf={violation.get('etf')} "
            f"isin={violation.get('isin', '-')} rel={rel_txt} "
            f"recomputed={violation.get('recomputed')} recorded={violation.get('recorded')}"
        )
    if breaches > 20:
        print(f"  ... and {breaches - 20} more (see --report)")
    print()
    print(f"RESULT: {'PASS' if tracker.passed else 'FAIL'}")


def _write_report(tracker: ParityTracker, path: str, capture: str, records_total: int) -> None:
    report = {
        "capture_file": capture,
        "rel_tol": REL_TOL,
        "records_total": records_total,
        "records_tested": tracker.records,
        "etfs_tested": tracker.etfs,
        "components_tested": tracker.components,
        "max_rel_error": tracker.max_rel,
        "worst": tracker.worst,
        "exact_mismatch_counts": tracker.exact_mismatch,
        "violation_count": len(tracker.violations),
        "violations": tracker.violations[:1000],
        "pass": tracker.passed,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ETF iNAV replay-parity harness (MF-B)")
    parser.add_argument("capture", help="path to inav_replay_*.jsonl.gz")
    parser.add_argument("--limit", type=int, default=None, help="sample N records spread evenly")
    parser.add_argument("--report", default=None, help="write a JSON report to this path")
    args = parser.parse_args(argv)

    tracker = ParityTracker()
    if args.limit:
        # Sampling needs a total up front; buffer complete records (used for
        # smoke runs on partial/live captures) then pick an even spread.
        records = list(_iter_all(args.capture))
        records_total = len(records)
        if records_total == 0:
            print(f"no complete records in {args.capture}", file=sys.stderr)
            return 2
        selected = _selected_indices(records_total, args.limit)
        sampled = selected is not None
        for index, record in records:
            if selected is None or index in selected:
                _check_record(record, index, tracker)
    else:
        # Full run: stream every record (memory-light for the large full-day file).
        records_total = 0
        sampled = False
        for index, record in _iter_all(args.capture):
            _check_record(record, index, tracker)
            records_total = index + 1
        if records_total == 0:
            print(f"no complete records in {args.capture}", file=sys.stderr)
            return 2

    _print_summary(tracker, args.capture, records_total, sampled)
    if args.report:
        _write_report(tracker, args.report, args.capture, records_total)
        print(f"report written  : {args.report}")

    return 0 if tracker.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
