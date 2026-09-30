"""내부자 거래 API (계획 A6) — `/research/insiders` 화면이 쓴다. 대상 = 내 미국 보유 + 관심종목.

★순매수는 **판단이 담긴 거래만** 센다(계획 §A · 와이어프레임 A-2):
  비파생(`is_derivative=false`) · 코드 P(장내 매수)/S(장내 매도) · 계획매매 아님(`is_planned_trade=false`)
  · 정정으로 대체되지 않음(`superseded_by IS NULL`) · 거래일이 미래가 아님.
  - A(보상)·M(옵션 행사)·F(세금 원천징수)·G(증여)는 경영진의 판단이 아니다.
  - 장내 매도의 73% 가 10b5-1 **계획매도**(몇 달 전에 정해 둔 자동 매도) — 섞으면 매도가 3배 넘게 부푼다.
  - 제외한 거래도 버리지 않는다 — 월 상세에서 회색 + 제외 이유로 보여 준다.
⚠️수집 시작이 종목마다 다르다 — 원본 추적 22곳은 수년치, A3b 에서 새로 붙은 종목은 180일치.
  시작 전 달이 '조용했다'로 읽히지 않게 종목별 `data_from` 을 준다.
⚠️거래 없는 달은 0 이 아니라 **막대 없음**(매수=매도인 0원 순매수와 다르다 — 계획 §D).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/research/insiders", tags=["insiders"])

WINDOW_DAYS = 90
MONTHS = 24
# 같은 회사의 다른 클래스 티커(내 GOOGL ↔ 신고서의 GOOG)
_ALIASES = {"GOOGL": {"GOOG"}, "GOOG": {"GOOGL"}, "BRK-B": {"BRK.B", "BRK-A"}}
CODE_LABEL = {"P": "장내 매수", "S": "장내 매도", "A": "보상 부여", "M": "옵션 행사", "F": "세금 원천징수",
              "G": "증여", "C": "전환", "D": "발행사 반환", "J": "기타", "X": "옵션 행사"}

COUNTED_SQL = ("f.transaction_code IN ('P', 'S') AND NOT f.is_derivative AND NOT f.is_planned_trade "
               "AND f.superseded_by IS NULL AND f.transaction_date <= :today")


def _targets(db: Session) -> dict[str, str]:
    """{티커(별칭 포함): 화면에 보일 티커}. 내 미국 보유 + 관심종목."""
    rows = db.execute(text(
        "SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items")).scalars().all()
    out: dict[str, str] = {}
    for t in rows:
        out[t] = t
        for alias in _ALIASES.get(t, ()):
            out.setdefault(alias, t)
    return out


def exclusion_reason(r) -> str | None:
    """센다면 None, 안 센다면 이유."""
    if r.superseded_by:
        return "정정으로 대체"
    if r.transaction_date and r.transaction_date > date.today():
        return "미래 날짜(데이터 오류)"
    if r.is_derivative:
        return "파생(옵션 등)"
    if r.transaction_code not in ("P", "S"):
        return CODE_LABEL.get(r.transaction_code or "", f"코드 {r.transaction_code}")
    if r.is_planned_trade:
        return "10b5-1 계획매매"
    return None


def _signed(r) -> float:
    v = float(r.transaction_value or 0)
    return v if r.transaction_code == "P" else -v


def _first_word(name: str | None) -> str:
    w = "".join(ch if ch.isalnum() else " " for ch in (name or "").upper()).split()
    return w[0] if w else ""


def _month_keys(today: date, n: int) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    today = date.today()
    targets = _targets(db)
    tickers = list(targets)
    since = today - timedelta(days=WINDOW_DAYS)
    months = _month_keys(today, MONTHS)
    start = date.fromisoformat(months[0] + "-01")

    counted = db.execute(text(
        "SELECT upper(f.ticker) AS ticker, f.transaction_date, f.transaction_code, f.transaction_value, "
        "f.insider_cik, f.insider_name FROM form4_transactions f "
        f"WHERE upper(f.ticker) = ANY(:t) AND f.transaction_date >= :start AND {COUNTED_SQL}"),
        {"t": tickers, "start": start, "today": today}).all()

    # 월별 · 종목별 순매수(달러). 거래 없는 (달, 종목)은 조각이 없다.
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    n_by_month: dict[str, int] = defaultdict(int)
    for r in counted:
        mk = r.transaction_date.strftime("%Y-%m")
        by_month[mk][targets[r.ticker]] += _signed(r)
        n_by_month[mk] += 1
    monthly = [{"month": m, "n_trades": n_by_month.get(m, 0),
                "net_value": round(sum(by_month[m].values()), 2) if m in by_month else None,
                "by_ticker": [{"ticker": t, "net_value": round(v, 2)} for t, v in
                              sorted(by_month[m].items(), key=lambda x: -abs(x[1]))] if m in by_month else []}
               for m in months]

    recent = [r for r in counted if r.transaction_date >= since]
    buys = [r for r in recent if r.transaction_code == "P"]
    multi: dict[str, set] = defaultdict(set)
    for r in buys:
        multi[targets[r.ticker]].add(r.insider_cik or r.insider_name)

    # 종목별 수집 시작(모든 코드 기준) · 발행사 CIK(13D 매칭용)
    cover = db.execute(text(
        "SELECT upper(ticker), min(transaction_date), max(transaction_date), "
        "(array_agg(issuer_cik ORDER BY transaction_date DESC))[1] FROM form4_transactions "
        "WHERE upper(ticker) = ANY(:t) AND transaction_date <= :today GROUP BY 1"),
        {"t": tickers, "today": today}).all()
    data_from: dict[str, dict] = {}
    ciks: set[str] = set()
    for t, lo, hi, cik in cover:
        shown = targets[t]
        cur = data_from.get(shown)
        data_from[shown] = {"ticker": shown, "from": min(lo, date.fromisoformat(cur["from"])).isoformat() if cur else lo.isoformat(),
                            "to": max(hi, date.fromisoformat(cur["to"])).isoformat() if cur else hi.isoformat()}
        if cik:
            ciks.add(cik)
    future = db.execute(text(
        "SELECT count(*) FROM form4_transactions WHERE upper(ticker) = ANY(:t) AND transaction_date > :today"),
        {"t": tickers, "today": today}).scalar()
    # 13D 는 **내 종목이 대상(subject)인 것**만. 내 종목이 다른 회사 지분을 신고한 것(예: 템퍼스 → 퍼스널리스)은 뺀다.
    # ⚠️백필(A2) 행은 issuer_cik 에 제출자 CIK 가 들어 있다(issuer_name 은 대상) → 이름 첫 단어로도 맞춘다.
    d13 = [r for r in db.execute(text(
        "SELECT filing_date, watch_name, issuer_name, issuer_cik, watch_cik, headline, source_url FROM sec_filings "
        "WHERE form_type = '13D' AND filing_date >= :since AND (watch_cik = ANY(:c) OR issuer_cik = ANY(:c)) "
        "ORDER BY filing_date DESC"), {"since": since, "c": list(ciks)}).mappings().all()
        if r["issuer_cik"] in ciks or _first_word(r["issuer_name"]) == _first_word(r["watch_name"])]
    d13 = [{k: r[k] for k in ("filing_date", "watch_name", "issuer_name", "headline", "source_url")} for r in d13]

    shown_targets = sorted(set(targets.values()))
    return {
        "window_days": WINDOW_DAYS,
        "rule": "비파생 · 코드 P/S · 10b5-1 계획매매 제외 · 정정 대체분 제외",
        "targets": shown_targets,
        "no_data": [t for t in shown_targets if t not in data_from],   # ETF 등 Form 4 가 없는 종목
        "data_from": sorted(data_from.values(), key=lambda x: x["from"]),
        "net_value_window": round(sum(_signed(r) for r in recent), 2),
        "buy_count_window": len(buys),
        "sell_count_window": len(recent) - len(buys),
        "multi_insider_buys": sorted(({"ticker": t, "n_insiders": len(s)} for t, s in multi.items() if len(s) >= 2),
                                     key=lambda x: -x["n_insiders"]),
        "recent_13d": [dict(r, filing_date=r["filing_date"].isoformat()) for r in d13],
        "monthly": monthly,
        "future_dated": future,
    }


@router.get("/month")
def month(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db)):
    """그 달 대상 종목의 **모든** Form 4 거래 — 센 것과 안 센 것(이유 포함)."""
    targets = _targets(db)
    start = date.fromisoformat(month + "-01")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = db.execute(text(
        "SELECT upper(f.ticker) AS ticker, f.accession_number, f.transaction_date, f.transaction_code, "
        "f.transaction_value, f.shares, f.price, f.insider_name, f.insider_role, f.is_derivative, "
        "f.is_planned_trade, f.superseded_by, f.buy_sell FROM form4_transactions f "
        "WHERE upper(f.ticker) = ANY(:t) AND f.transaction_date >= :s AND f.transaction_date < :e "
        "ORDER BY f.transaction_date DESC, f.accession_number, f.seq"),
        {"t": list(targets), "s": start, "e": end}).all()
    if not rows and not targets:
        raise AppError(404, "INSIDER_NO_TARGETS", "보유·관심종목이 없습니다")
    out = []
    for r in rows:
        reason = exclusion_reason(r)
        out.append({"ticker": targets[r.ticker], "date": r.transaction_date.isoformat(), "code": r.transaction_code,
                    "code_label": CODE_LABEL.get(r.transaction_code or "", r.transaction_code),
                    "insider": r.insider_name, "role": r.insider_role,
                    "shares": float(r.shares) if r.shares is not None else None,
                    "price": float(r.price) if r.price is not None else None,
                    "value": float(r.transaction_value) if r.transaction_value is not None else None,
                    "signed_value": _signed(r) if reason is None else None,
                    "planned": bool(r.is_planned_trade), "counted": reason is None, "excluded_reason": reason,
                    "accession": r.accession_number})
    counted = [x for x in out if x["counted"]]
    return {"month": month, "net_value": round(sum(x["signed_value"] for x in counted), 2) if counted else None,
            "n_counted": len(counted), "n_excluded": len(out) - len(counted), "trades": out}
