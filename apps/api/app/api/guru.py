"""거장 13F API (계획 A5) — `/research/guru` 화면이 쓴다. collector 프록시(`/guru-13f/*`)를 대신한다.

⚠️기술 도구다 — 예측이 아니다(`app/core/guru_flows.py` 머리말). 응답마다 `disclaimer` 를 같이 준다.

불러오기: 명단(`guru_roster` kind='guru' · active)의 최근 12개 보고 분기.
  - 분기마다 **유효 공시 묶음**(`effective_accessions` — RESTATEMENT 대체 / NEW HOLDINGS 합산)
  - 공시마다 금액 단위 보정(천 달러 → ×1000) 뒤 합쳐 비중(bp)으로
  - 옵션(put/call)·채권(PRN) 제외, 주식 클래스 합침(GOOG→GOOGL · BRK.B→BRK.A)
캐시 키 = (13F 공시 최대 id, cusip_map 최종 갱신) — 새 공시·새 티커가 들어올 때만 다시 계산한다.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import date

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import guru_flows as gf
from app.core import valuechain as vc
from app.core.config import settings
from app.core.errors import AppError
from app.core.guru13f import Filing13F, effective_accessions
from app.core.sec_search import pad_cik, search_13f_filers
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/research/guru", tags=["guru"])

N_PERIODS = 12
HISTORY_PAIRS = 8
DISCLAIMER = ("무슨 일이 있었나를 보는 화면입니다 — 예측이 아닙니다. 같은 데이터로 만든 시그널 24조합을 "
              "검증했을 때 통과 0(난수 시그널과 구분되지 않음). 13F 는 분기말 +45일 공시 · 롱 온리입니다.")

_lock = threading.Lock()
_cache: dict[tuple, tuple] = {}


def load_guru_data(db: Session, n_periods: int = N_PERIODS) -> gf.GuruData:
    roster = db.execute(text(
        "SELECT cik, COALESCE(guru_name, firm), firm FROM guru_roster WHERE kind = 'guru' AND active")).all()
    gurus = {cik: {"guru": name, "firm": firm} for cik, name, firm in roster}
    if not gurus:
        return gf.GuruData(gurus={}, mat={})
    periods = [p for (p,) in db.execute(text(
        "SELECT DISTINCT period_of_report FROM sec_filings WHERE form_type LIKE '13F%' "
        "AND watch_cik = ANY(:c) AND period_of_report IS NOT NULL ORDER BY 1 DESC LIMIT :n"),
        {"c": list(gurus), "n": n_periods})]
    filings = db.execute(text(
        "SELECT watch_cik, period_of_report, accession_number, filing_date, form_type, amendment_type "
        "FROM sec_filings WHERE form_type LIKE '13F%' AND watch_cik = ANY(:c) AND period_of_report = ANY(:p)"),
        {"c": list(gurus), "p": periods}).all()
    groups: dict[tuple, list[Filing13F]] = defaultdict(list)
    for cik, p, acc, fd, form, amend in filings:
        groups[(p, cik)].append(Filing13F(acc, fd or date.min, form, amend))
    acc_key: dict[str, tuple] = {}
    warnings: list[str] = []
    for key, fs in groups.items():
        accs, w = effective_accessions(fs)
        warnings += w
        for a in accs:
            acc_key[a] = key
    rows = db.execute(text(
        "SELECT h.accession_number, upper(h.cusip), h.name_of_issuer, h.value, h.shares, m.ticker, m.sector "
        "FROM holdings_13f h LEFT JOIN cusip_map m ON m.cusip = h.cusip "
        "WHERE h.accession_number = ANY(:a) AND h.put_call IS NULL AND COALESCE(h.shr_type, 'SH') = 'SH' "
        "AND h.cusip IS NOT NULL"), {"a": list(acc_key)}).all()
    by_acc: dict[str, list] = defaultdict(list)
    for r in rows:
        by_acc[r[0]].append(r)
    books: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    label: dict[str, dict] = {}
    for acc, rs in by_acc.items():
        scale = gf.value_scale([(float(r[3] or 0), float(r[4] or 0)) for r in rs])
        for _, cusip, name, value, _shares, ticker, sector in rs:
            k = gf.SHARE_CLASS_MERGE.get(cusip, cusip)
            books[acc_key[acc]][k] += float(value or 0) * scale
            lb = label.get(k)
            if lb is None or (not lb["ticker"] and ticker):
                label[k] = {"cusip": k, "name": name, "ticker": ticker, "sector": sector}
    return gf.GuruData(gurus=gurus, mat=gf.normalize(books), label=label, warnings=warnings,
                       usd={k: dict(b) for k, b in books.items() if sum(b.values()) > 0})   # mat 과 같은 묶음


def _data(db: Session) -> gf.GuruData:
    version = tuple(db.execute(text(
        "SELECT (SELECT max(id) FROM sec_filings WHERE form_type LIKE '13F%'), "
        "(SELECT max(updated_at) FROM cusip_map), (SELECT count(*) FROM guru_roster WHERE active)")).one())
    with _lock:
        hit = _cache.get("data")
        if hit and hit[0] == version:
            return hit[1]
    data = load_guru_data(db)
    with _lock:
        _cache["data"] = (version, data)
    return data


def _my_tickers(db: Session) -> list[tuple[str, str | None]]:
    return [(t, n) for t, n in db.execute(text(
        "SELECT DISTINCT a.ticker, a.name FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "WHERE p.quantity > 0 AND a.country = 'US' ORDER BY 1"))]


def _pair(usable: list[date], curr: date | None) -> tuple[date | None, date | None]:
    if curr is None:
        return (usable[0] if usable else None), (usable[1] if len(usable) > 1 else None)
    if curr not in usable:
        raise AppError(404, "GURU_PERIOD", f"정족수를 넘긴 분기가 아닙니다: {curr}")
    i = usable.index(curr)
    return curr, (usable[i + 1] if i + 1 < len(usable) else None)


def _q(p: date | None) -> dict | None:
    return {"period": p.isoformat(), "label": gf.quarter_label(p)} if p else None


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    data = _data(db)
    meta = gf.period_meta(data)
    usable = gf.usable_periods(data)
    curr, prev = _pair(usable, None)
    latest = meta[0] if meta else None
    last_filed = {}
    for (p, k) in data.mat:
        last_filed[k] = max(last_filed.get(k, p), p)
    latest_p = date.fromisoformat(latest["period"]) if latest else None
    roster = sorted(({**data.gurus[k], "cik": k, "last_period": _q(last_filed.get(k)),
                      "filed_latest": last_filed.get(k) == latest_p} for k in data.gurus),
                    key=lambda r: (not r["filed_latest"], r["guru"]))
    ee = gf.entries_exits(data, curr, prev) if curr and prev else {"n_participants": 0, "entries": [], "exits": []}
    smap = gf.load_sector_map()
    history = []
    for i in range(min(HISTORY_PAIRS, max(len(usable) - 1, 0))):
        c, p = usable[i], usable[i + 1]
        sf = gf.sector_flows(data, c, p, smap)
        history.append({**_q(c), "prev": _q(p), **sf})
    history.reverse()
    mine = gf.my_holdings(data, curr, prev, _my_tickers(db)) if curr else []
    return {
        "disclaimer": DISCLAIMER,
        "n_gurus": len(data.gurus),
        "latest": latest,                      # 가장 최근 보고 분기(정족수 미달일 수 있다)
        "quorum": gf.QUORUM,
        "curr": _q(curr), "prev": _q(prev),    # 비교에 쓴 분기쌍(정족수 통과)
        "period_meta": meta,
        "roster": roster,
        "n_participants": ee["n_participants"],
        "multi_entries": [r for r in ee["entries"] if r["n_gurus"] >= 2],
        "multi_exits": [r for r in ee["exits"] if r["n_gurus"] >= 2],
        "my_holdings": mine,
        "sector_history": history,
        "warnings": data.warnings,
    }


@router.get("/quarter")
def quarter(period: date = Query(..., description="비교할 분기말(정족수 통과 분기)"), db: Session = Depends(get_db)):
    data = _data(db)
    curr, prev = _pair(gf.usable_periods(data), period)
    if prev is None:
        raise AppError(404, "GURU_PERIOD", "직전 비교 분기가 없습니다")
    ee = gf.entries_exits(data, curr, prev)
    return {"disclaimer": DISCLAIMER, "curr": _q(curr), "prev": _q(prev),
            "n_participants": ee["n_participants"],
            "entries": ee["entries"][:50], "exits": ee["exits"][:50],
            "total_entries": len(ee["entries"]), "total_exits": len(ee["exits"]),
            "rebalance": gf.rebalance(data, curr, prev)[:40],
            "sector": gf.sector_flows(data, curr, prev, gf.load_sector_map())}


@router.get("/quarterly-l1")
def quarterly_l1(db: Session = Depends(get_db)):
    """★2026-10-04 분기별 총 투자금액(USD, 명단 거장 13F 보유 합) × 밸류체인 L1 몫 — 막대 = 금액, 조각 = L1.

    분기 = 정족수 통과 최근 HISTORY_PAIRS 개(오래된 것부터). 13F 데이터(`_data`)·L1 표(`ticker_l1_map`)
    객체가 그대로면 지난 결과를 그대로 준다 — 분기 데이터는 거의 바뀌지 않는다.
    """
    data = _data(db)
    tmap = vc.ticker_l1_map()
    with _lock:
        hit = _cache.get("l1")
        if hit and hit[0] is data and hit[1] is tmap:
            return hit[2]
    palette = vc.l1_palette()
    usable = gf.usable_periods(data)
    periods = usable[:HISTORY_PAIRS]
    rows = gf.quarter_l1(data, list(reversed(periods)), tmap, palette)
    for r in rows:                                   # 직전 분기가 있어야 종목 변동 창을 연다
        i = usable.index(date.fromisoformat(r["period"]))
        r["has_prev"] = i + 1 < len(usable)
    out = {"disclaimer": DISCLAIMER, "n_gurus": len(data.gurus), "unclassified": gf.UNCLASSIFIED,
           "legend": [{"l1": n, "color": c} for n, c in palette], "quarters": rows}
    with _lock:
        _cache["l1"] = (data, tmap, out)
    return out


@router.get("/stock")
def stock(ticker: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    data = _data(db)
    periods = list(reversed(gf.usable_periods(data)[:HISTORY_PAIRS]))
    return {"disclaimer": DISCLAIMER, "ticker": ticker.upper(), "periods": [_q(p) for p in periods],
            "gurus": gf.stock_trend(data, ticker, periods)}


# ── 거장 명단 관리 (계획 A7) ──────────────────────────────────────────────────
# 추가 = 이름 검색(EDGAR, 13F-HR 제출자만) → CIK → 명단에 pending → SEC_13F_BACKFILL 작업(2013Q2~).
# 비활성화하면 과거 데이터는 남기고 분석에서만 뺀다(분석은 active 만 센다 — 거장 수도 명단에서).


class GuruAdd(BaseModel):
    cik: str = Field(..., min_length=1, max_length=10)
    filer_name: str = Field(..., min_length=1)
    guru_name: str | None = None
    firm: str | None = None


class GuruPatch(BaseModel):
    active: bool


def _enqueue_backfill(db: Session, cik: str) -> None:
    db.execute(text(
        "INSERT INTO jobs (id, job_type, status, queue, payload, created_at, updated_at) "
        "VALUES (gen_random_uuid(), 'SEC_13F_BACKFILL', 'PENDING', 'sec_crawl', CAST(:p AS JSONB), now(), now())"),
        {"p": f'{{"cik": "{cik}"}}'})


@router.get("/roster")
def roster(db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT g.cik, g.guru_name, g.firm, g.filer_name, g.kind, g.active, g.backfill_status, g.backfill_from, "
        "g.added_at, g.note, (SELECT count(DISTINCT period_of_report) FROM sec_filings f "
        "WHERE f.watch_cik = g.cik AND f.form_type LIKE '13F%') AS n_periods, "
        "(SELECT max(period_of_report) FROM sec_filings f WHERE f.watch_cik = g.cik AND f.form_type LIKE '13F%') "
        "AS last_period FROM guru_roster g ORDER BY g.kind, g.active DESC, COALESCE(g.guru_name, g.firm)")).mappings().all()
    return {"items": [dict(r, backfill_from=r["backfill_from"].isoformat(), added_at=r["added_at"].isoformat(),
                           last_period=r["last_period"].isoformat() if r["last_period"] else None) for r in rows]}


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=80), db: Session = Depends(get_db)):
    if not settings.SEC_USER_AGENT.strip():
        raise AppError(503, "SEC_UA_MISSING", "SEC_USER_AGENT 미설정 — .env.local 에 연락처 UA 가 있어야 검색합니다")
    try:
        hits = search_13f_filers(q, settings.SEC_USER_AGENT.strip())
    except httpx.HTTPStatusError as exc:
        raise AppError(502, "SEC_SEARCH_FAILED", f"SEC 검색 실패 ({exc.response.status_code})") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "SEC_SEARCH_FAILED", f"SEC 검색 실패 ({type(exc).__name__})") from exc
    have = {c: (k, a) for c, k, a in db.execute(text("SELECT cik, kind, active FROM guru_roster"))}
    return {"query": q, "items": [dict(h, in_roster=h["cik"] in have,
                                       kind=have.get(h["cik"], (None, None))[0],
                                       active=have.get(h["cik"], (None, None))[1]) for h in hits]}


@router.post("/roster", status_code=201)
def add_guru(body: GuruAdd, db: Session = Depends(get_db)):
    cik = pad_cik(body.cik)
    existing = db.execute(text("SELECT kind, active, backfill_status FROM guru_roster WHERE cik = :c"),
                          {"c": cik}).one_or_none()
    if existing is not None:
        if existing.kind == "guru" and existing.active:
            raise AppError(409, "GURU_EXISTS", "이미 명단에 있는 거장입니다")
        # 비활성 거장 · 인덱스(퀀트) 기관을 거장으로 켠다 — 백필이 안 됐으면 백필도
        db.execute(text("UPDATE guru_roster SET kind = 'guru', active = true, "
                        "guru_name = COALESCE(:g, guru_name), firm = COALESCE(:f, firm) WHERE cik = :c"),
                   {"c": cik, "g": body.guru_name, "f": body.firm})
        if existing.backfill_status != "done":
            db.execute(text("UPDATE guru_roster SET backfill_status = 'pending' WHERE cik = :c"), {"c": cik})
            _enqueue_backfill(db, cik)
    else:
        db.execute(text(
            "INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind, active, backfill_status) "
            "VALUES (:c, :g, :f, :fn, 'guru', true, 'pending')"),
            {"c": cik, "g": body.guru_name, "f": body.firm or body.filer_name, "fn": body.filer_name})
        _enqueue_backfill(db, cik)
    db.commit()
    return next(r for r in roster(db)["items"] if r["cik"] == cik)


@router.patch("/roster/{cik}")
def patch_guru(cik: str, body: GuruPatch, db: Session = Depends(get_db)):
    n = db.execute(text("UPDATE guru_roster SET active = :a WHERE cik = :c"),
                   {"a": body.active, "c": pad_cik(cik)}).rowcount
    if not n:
        raise AppError(404, "GURU_NOT_FOUND", "명단에 없습니다")
    db.commit()
    return next(r for r in roster(db)["items"] if r["cik"] == pad_cik(cik))
