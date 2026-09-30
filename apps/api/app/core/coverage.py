"""데이터 보유 현황판 — "지금 얼마나 있나"만 센다 (계획 S8 · §6, §12-8 레인 C).

⚠️전부 **읽기 전용 집계**다. 새 데이터를 만들거나 고치지 않는다.
⚠️여긴 "예측"이 아니라 "재고"다 — 무슇 원천에 몇 건이 있는지, 언제 마지막으로
  받았는지만 본다.
⚠️13D/13G 를 종목(티커)에 이어 붙이려면 발행사 CIK 가 있어야 하는데, `sec_filings`
  자체엔 티커가 없다. `form4_transactions.ticker` ↔ `issuer_cik` 매칭을 다리로 쓴다
  (`api/insiders.py` §A6 와 같은 근사) — **Form4 거래가 한 번도 없던 종목은 CIK를
  몰라 13D/13G 가 0으로 보인다.** 실제로 없는 것과 구분이 안 되므로, 그 종목들은
  KPI 옆이 아니라 표의 각주로만 밝힌다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import valuechain as vc

# 원천이 이 시간 안에 한 번도 성공하지 못하면 "오래됨" — 매일 도는 배치 기준으로
# 주말 하루를 넘겨도 오탐이 안 나게 이틀을 준다.
STALE_AFTER = timedelta(hours=48)

# kind 별로 볼 원천(source_status.source) — 실측(2026-09-27)에 있는 이름만.
_SOURCES_BY_KIND: dict[str, list[str]] = {
    "guru": ["sec_13f", "openfigi"],
    "earnings": ["nasdaq", "investing", "earnings_result", "claude", "worker:llm"],
    "filings": ["sec", "sec_form4", "sec_13dg"],
    "stocks": ["sec", "sec_13f", "sec_form4", "sec_13dg", "nasdaq", "investing", "earnings_result", "claude"],
}

_LAST_N_QUARTERS = 12


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _fmt_period(d: date | None) -> str | None:
    if d is None:
        return None
    q = (d.month - 1) // 3 + 1
    return f"{d.year % 100:02d}Q{q}"


def source_status_rows(db: Session, sources: list[str], now: datetime | None = None) -> list[dict]:
    """`source_status` 중 이 kind 에 관련된 것들 — 언제 마지막으로 성공/실패했나."""
    now = now or datetime.now(timezone.utc)
    if not sources:
        return []
    rows = db.execute(text(
        "SELECT source, last_ok_at, last_error_at, last_error_kind FROM source_status "
        "WHERE source = ANY(:s) ORDER BY source"), {"s": sources}).all()
    found = {r.source: r for r in rows}
    out = []
    for s in sources:
        r = found.get(s)
        last_ok = r.last_ok_at if r else None
        stale = last_ok is None or (now - last_ok) > STALE_AFTER
        out.append({
            "source": s,
            "last_ok_at": last_ok,
            "last_error_at": r.last_error_at if r else None,
            "last_error_kind": r.last_error_kind if r else None,
            "stale": stale,
        })
    return out


def held_and_watchlist_tickers(db: Session, *, us_only: bool = True) -> list[str]:
    """보유(수량>0) ∪ 관심종목 티커. `us_only=False` 면 국가 제한 없이 `current_positions`+`assets`
    ∪ `watchlist_items` 그대로(§6 stocks 유니버스, §12-8 레인 C 소유)."""
    country_filter = "AND a.country = 'US' " if us_only else ""
    rows = db.execute(text(
        "SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        f"WHERE p.quantity > 0 {country_filter}"
        "UNION SELECT upper(ticker) FROM watchlist_items")).scalars().all()
    return sorted(set(rows))


# ── 거장 13F ─────────────────────────────────────────────────────────────────


def guru_coverage(db: Session) -> dict:
    active_total = db.execute(text(
        "SELECT count(*) FILTER (WHERE active), count(*) FROM guru_roster WHERE kind = 'guru'")).one()
    active, total = active_total

    n_accessions = db.execute(text(
        "SELECT count(DISTINCT accession_number) FROM sec_filings WHERE form_type LIKE '13F%'")).scalar() or 0

    n_periods, lo, hi = db.execute(text(
        "SELECT count(DISTINCT period_of_report), min(period_of_report), max(period_of_report) "
        "FROM sec_filings WHERE form_type LIKE '13F%'")).one()

    n_holdings, n_cusips = db.execute(text(
        "SELECT count(*), count(DISTINCT cusip) FROM holdings_13f")).one()

    n_resolved, n_cusip_total = db.execute(text(
        "SELECT count(*) FILTER (WHERE ticker IS NOT NULL AND ticker <> ''), count(*) FROM cusip_map")).one()

    latest_period = hi
    if latest_period is not None and active:
        n_filed_latest = db.execute(text(
            "SELECT count(DISTINCT f.watch_cik) FROM sec_filings f JOIN guru_roster g ON g.cik = f.watch_cik "
            "WHERE f.form_type LIKE '13F%' AND f.period_of_report = :p AND g.kind = 'guru' AND g.active"),
            {"p": latest_period}).scalar() or 0
    else:
        n_filed_latest = 0

    resolve_pct = (n_resolved / n_cusip_total * 100) if n_cusip_total else None

    kpis = [
        {"label": "활성/전체 구루", "value": f"{active}/{total}", "hint": None},
        {"label": "13F 접수", "value": f"{n_accessions:,}건", "hint": None},
        {"label": "분기 커버리지", "value": f"{n_periods}개 분기",
         "hint": f"{_fmt_period(lo)}~{_fmt_period(hi)}" if lo and hi else None},
        {"label": "최신 분기 제출", "value": f"{n_filed_latest}/{active}",
         "hint": f"{_fmt_period(latest_period)} 기준" if latest_period else None},
        {"label": "holdings 행", "value": f"{n_holdings:,}행", "hint": f"CUSIP {n_cusips:,}종"},
        {"label": "CUSIP 해석률", "value": f"{resolve_pct:.1f}%" if resolve_pct is not None else "—",
         "hint": f"{n_resolved:,}/{n_cusip_total:,}"},
    ]

    # 구루 × 최근 12분기 히트맵(제출 여부).
    quarters = [q for (q,) in db.execute(text(
        "SELECT DISTINCT period_of_report FROM sec_filings WHERE form_type LIKE '13F%' "
        "AND period_of_report IS NOT NULL ORDER BY 1 DESC LIMIT :n"), {"n": _LAST_N_QUARTERS}).all()]
    quarters.sort()  # 오래된 → 최신, 왼쪽에서 오른쪽으로 읽히게.

    roster = db.execute(text(
        "SELECT cik, COALESCE(guru_name, firm) AS name FROM guru_roster "
        "WHERE kind = 'guru' AND active ORDER BY name")).all()

    filed = defaultdict(set)
    if quarters:
        for cik, period in db.execute(text(
            "SELECT DISTINCT watch_cik, period_of_report FROM sec_filings "
            "WHERE form_type LIKE '13F%' AND period_of_report = ANY(:p)"), {"p": quarters}).all():
            filed[cik].add(period)

    rows = [{
        "key": cik,
        "label": name,
        "link": None,
        "cells": [bool(period in filed.get(cik, ())) for period in quarters],
    } for cik, name in roster]

    return {
        "kpis": kpis,
        "table": {"columns": [_fmt_period(q) for q in quarters], "rows": rows},
        "anomalies": [],
        "notes": [],
    }


# ── 어닝 콜 / 이슈 ────────────────────────────────────────────────────────────


def earnings_coverage(db: Session) -> dict:
    targets = held_and_watchlist_tickers(db, us_only=True)
    tracked = db.execute(text(
        "SELECT count(DISTINCT ticker) FROM earnings_events WHERE ticker = ANY(:t)"), {"t": targets}).scalar() or 0

    n_events, n_ev_tickers, lo_q, hi_q = db.execute(text(
        "SELECT count(*), count(DISTINCT ticker), min(quarter), max(quarter) FROM earnings_events "
        "WHERE ticker = ANY(:t)"), {"t": targets}).one()

    n_with_result = db.execute(text(
        "SELECT count(*) FROM earnings_events e JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker = ANY(:t)"), {"t": targets}).scalar() or 0

    n_wp, n_wp_import, n_wp_llm, n_wp_result = db.execute(text(
        "SELECT count(*), count(*) FILTER (WHERE w.source = 'import'), "
        "count(*) FILTER (WHERE w.source = 'llm'), count(*) FILTER (WHERE w.result IS NOT NULL) "
        "FROM earnings_watchpoints w JOIN earnings_events e ON e.ticker = w.ticker AND e.quarter = w.quarter "
        "WHERE w.ticker = ANY(:t)"), {"t": targets}).one()

    n_guidance = db.execute(text(
        "SELECT count(*) FROM earnings_guidance g JOIN earnings_events e ON e.id = g.event_id "
        "WHERE e.ticker = ANY(:t)"), {"t": targets}).scalar() or 0

    kpis = [
        {"label": "추적 종목", "value": f"{tracked}/{len(targets)}", "hint": "보유+관심 중 실적 이벤트가 있는 종목"},
        {"label": "이벤트", "value": f"{n_events}건", "hint": f"{n_ev_tickers}종목 · {lo_q}~{hi_q}" if lo_q else None},
        {"label": "결과 보유율", "value": f"{n_with_result}/{n_events}" if n_events else "—", "hint": None},
        {"label": "워치포인트", "value": f"{n_wp}건",
         "hint": f"import {n_wp_import} · LLM {n_wp_llm} · 결과 채움 {n_wp_result}"},
        {"label": "가이던스", "value": f"{n_guidance}건", "hint": None},
    ]

    quarters = [q for (q,) in db.execute(text(
        "SELECT DISTINCT quarter FROM earnings_events WHERE ticker = ANY(:t) ORDER BY 1"), {"t": targets}).all()]

    ev_rows = db.execute(text(
        "SELECT e.ticker, e.quarter, (r.event_id IS NOT NULL) AS has_result FROM earnings_events e "
        "LEFT JOIN earnings_results r ON r.event_id = e.id WHERE e.ticker = ANY(:t)"), {"t": targets}).all()
    by_ticker: dict[str, dict[str, bool]] = defaultdict(dict)
    for ticker, quarter, has_result in ev_rows:
        by_ticker[ticker][quarter] = bool(has_result)

    rows = [{
        "key": t,
        "label": t,
        "link": None,
        "cells": [
            ("결과" if by_ticker.get(t, {}).get(q) else ("이벤트" if q in by_ticker.get(t, {}) else None))
            for q in quarters
        ],
    } for t in targets]

    return {
        "kpis": kpis,
        "table": {"columns": quarters, "rows": rows},
        "anomalies": [],
        "notes": [],
    }


# ── 종목 공시 ─────────────────────────────────────────────────────────────────

_FILING_FORM_TYPES = ["4", "4/A", "13D", "13G"]


def _ticker_cik_map(db: Session, tickers: list[str]) -> dict[str, str]:
    """티커 → 발행사 CIK(가장 거래가 많이 찍힌 CIK). Form4 거래로만 안다."""
    rows = db.execute(text(
        "SELECT upper(ticker) AS t, issuer_cik, count(*) AS n FROM form4_transactions "
        "WHERE upper(ticker) = ANY(:t) AND issuer_cik IS NOT NULL GROUP BY 1, 2"), {"t": tickers}).all()
    best: dict[str, tuple[str, int]] = {}
    for t, cik, n in rows:
        if t not in best or n > best[t][1]:
            best[t] = (cik, n)
    return {t: cik for t, (cik, _n) in best.items()}


def filings_coverage(db: Session) -> dict:
    targets = held_and_watchlist_tickers(db, us_only=True)

    form_totals = {ft: r for ft, r in (
        (ft, db.execute(text(
            "SELECT count(*), count(DISTINCT issuer_cik), min(filing_date), max(filing_date) "
            "FROM sec_filings WHERE form_type = :f"), {"f": ft}).one())
        for ft in _FILING_FORM_TYPES
    )}
    n_form4_tx, n_form4_tickers = db.execute(text(
        "SELECT count(*), count(DISTINCT upper(ticker)) FROM form4_transactions")).one()
    n_ownership = db.execute(text("SELECT count(*) FROM ownership_events")).scalar() or 0
    n_future = db.execute(text(
        "SELECT count(*) FROM form4_transactions WHERE transaction_date > current_date")).scalar() or 0

    kpis = [{
        "label": f"Form {ft}" if ft in ("4", "4/A") else ft,
        "value": f"{n:,}건",
        "hint": f"발행사 {issuers}개 · {_fmt_period(lo)}~{_fmt_period(hi)}" if lo and hi else None,
    } for ft, (n, issuers, lo, hi) in form_totals.items()]
    kpis += [
        {"label": "form4_transactions", "value": f"{n_form4_tx:,}행", "hint": f"{n_form4_tickers}종목"},
        {"label": "ownership_events", "value": f"{n_ownership:,}행", "hint": None},
        {"label": "라이브 커버리지(보유+관심)", "value": f"{len(targets)}종목",
         "hint": "8-K/10-K/10-Q는 저장하지 않습니다 — 매 요청 SEC 라이브 조회"},
    ]

    cik_map = _ticker_cik_map(db, targets)
    all_ciks = list(set(cik_map.values()))
    counts: dict[tuple[str, str], int] = defaultdict(int)
    if all_ciks:
        for cik, form_type, n in db.execute(text(
            "SELECT COALESCE(issuer_cik, watch_cik), form_type, count(*) FROM sec_filings "
            "WHERE form_type = ANY(:f) AND (issuer_cik = ANY(:c) OR watch_cik = ANY(:c)) GROUP BY 1, 2"),
            {"f": _FILING_FORM_TYPES, "c": all_ciks}).all():
            counts[(cik, form_type)] += n

    no_cik = [t for t in targets if t not in cik_map]
    rows = [{
        "key": t,
        "label": t,
        "link": None,
        "cells": [counts.get((cik_map.get(t), ft), 0) if t in cik_map else None for ft in _FILING_FORM_TYPES],
    } for t in targets]

    anomalies = []
    if n_future:
        anomalies.append(f"미래 날짜 Form4 거래 {n_future}건(데이터 오류)")

    notes = []
    if no_cik:
        notes.append(
            f"{', '.join(no_cik)}: Form4 거래가 없어 발행사 CIK 를 몰라 13D/13G 열을 셀 수 없습니다(0 아님)."
        )

    return {
        "kpis": kpis,
        "table": {"columns": ["Form4", "Form4/A", "13D", "13G"], "rows": rows},
        "anomalies": anomalies,
        "notes": notes,
    }


# ── 종목 단위 리서치 ──────────────────────────────────────────────────────────


def _valuechain_labels(db: Session, tickers: list[str]) -> dict[str, str]:
    """티커 → "섹터코드·주 소속 분류코드"(예: bio·B-1-2). `storage/valuechain/*.ttl`
    전 섹터를 로드해 회사 티커로 맞춘다(`api/valuechain.py` 의 held/watch 판정과 같은 방식) —
    보유 종목은 국가까지 맞추고, 관심종목처럼 국가를 모르면 티커만으로 맞춘다.
    ★여러 섹터에 속하면 테마 라벨 먼저, 분류(generated/) 라벨 다음으로 " / " 로 최대 2개
      (예: bio·A-1 / tx-healthcare·H01)."""
    ticker_set = {t.upper() for t in tickers}
    if not ticker_set:
        return {}
    country_by_ticker = {t: c for t, c in db.execute(text(
        "SELECT DISTINCT upper(a.ticker), a.country FROM current_positions p "
        "JOIN assets a ON a.id = p.asset_id WHERE p.quantity > 0 AND upper(a.ticker) = ANY(:t)"),
        {"t": list(ticker_set)}).all()}

    sectors, _ = vc.load_all()
    candidates: dict[str, list[tuple[str | None, str, bool]]] = defaultdict(list)
    for s in sectors:
        for m in s.memberships:
            if not m.primary:
                continue
            co = s.companies.get(m.company)
            if co is None or not co.ticker:
                continue
            t = co.ticker.upper()
            if t in ticker_set:
                candidates[t].append((co.country, f"{s.code}·{m.primary}", s.kind == "taxonomy"))

    out: dict[str, str] = {}
    for t, opts in candidates.items():
        want = country_by_ticker.get(t)
        matched = [o for o in opts if o[0] == want] if want else []
        picked = sorted(matched or opts, key=lambda o: o[2])      # 안정 정렬: 테마 → 분류, 섹터 순서 유지
        out[t] = " / ".join(list(dict.fromkeys(label for _, label, _ in picked))[:2])
    return out


def stocks_coverage(db: Session) -> dict:
    universe = held_and_watchlist_tickers(db, us_only=False)

    n_events = {t: n for t, n in db.execute(text(
        "SELECT ticker, count(*) FROM earnings_events WHERE ticker = ANY(:t) GROUP BY 1"), {"t": universe}).all()}
    n_watchpoints = {t: n for t, n in db.execute(text(
        "SELECT ticker, count(*) FROM earnings_watchpoints WHERE ticker = ANY(:t) GROUP BY 1"),
        {"t": universe}).all()}
    n_form4 = {t: n for t, n in db.execute(text(
        "SELECT upper(ticker), count(*) FROM form4_transactions WHERE upper(ticker) = ANY(:t) GROUP BY 1"),
        {"t": universe}).all()}

    cik_map = _ticker_cik_map(db, universe)
    all_ciks = list(set(cik_map.values()))
    n_13dg: dict[str, int] = defaultdict(int)
    if all_ciks:
        for cik, n in db.execute(text(
            "SELECT COALESCE(issuer_cik, watch_cik), count(*) FROM sec_filings "
            "WHERE form_type IN ('13D', '13G') AND (issuer_cik = ANY(:c) OR watch_cik = ANY(:c)) GROUP BY 1"),
            {"c": all_ciks}).all():
            n_13dg[cik] += n
    cik_to_tickers: dict[str, list[str]] = defaultdict(list)
    for t, cik in cik_map.items():
        cik_to_tickers[cik].append(t)

    # 최신 분기 기준 보유 구루 수(§A5 와 같은 최신 분기 정의 — cusip_map 경유).
    latest_period = db.execute(text(
        "SELECT max(period_of_report) FROM sec_filings WHERE form_type LIKE '13F%'")).scalar()
    n_gurus: dict[str, int] = defaultdict(int)
    if latest_period is not None:
        for t, n in db.execute(text(
            "SELECT c.ticker, count(DISTINCT f.watch_cik) FROM sec_filings f "
            "JOIN holdings_13f h ON h.accession_number = f.accession_number "
            "JOIN cusip_map c ON c.cusip = h.cusip JOIN guru_roster g ON g.cik = f.watch_cik "
            "WHERE f.form_type LIKE '13F%' AND f.period_of_report = :p AND g.kind = 'guru' AND g.active "
            "AND upper(c.ticker) = ANY(:t) GROUP BY 1"), {"p": latest_period, "t": universe}).all():
            n_gurus[t] += n

    n_covered = sum(1 for t in universe if n_events.get(t) or n_watchpoints.get(t) or n_form4.get(t) or n_gurus.get(t))
    kpis = [
        {"label": "커버 종목(보유+관심)", "value": f"{len(universe)}종목", "hint": None},
        {"label": "소스별 보유 종목", "value": f"{n_covered}/{len(universe)}",
         "hint": "실적·거장·Form4 중 하나라도 있는 종목"},
    ]

    vc_labels = _valuechain_labels(db, universe)

    rows = []
    for t in universe:
        cik = cik_map.get(t)
        dg = n_13dg.get(cik, 0) if cik else None
        rows.append({
            "key": t,
            "label": t,
            "link": "/research/earnings" if n_events.get(t) else "/research/filings",
            "cells": [
                n_events.get(t, 0),
                n_watchpoints.get(t, 0),
                n_form4.get(t, 0),
                n_gurus.get(t, 0),
                dg,
                vc_labels.get(t, "—"),
            ],
        })

    return {
        "kpis": kpis,
        "table": {
            "columns": ["실적 이벤트", "워치포인트", "Form4 거래", "보유 구루", "13D/G", "밸류체인"],
            "rows": rows,
        },
        "anomalies": [],
        "notes": [],
    }


_BUILDERS = {
    "guru": guru_coverage,
    "earnings": earnings_coverage,
    "filings": filings_coverage,
    "stocks": stocks_coverage,
}


def build(kind: str, db: Session) -> dict:
    """kind(stocks|guru|earnings|filings) 의 현황판 데이터 전체."""
    builder = _BUILDERS[kind]
    result = builder(db)
    result["sources"] = source_status_rows(db, _SOURCES_BY_KIND.get(kind, []))
    return result
