"""SEC_13F · SEC_FORM4 · SEC_13DG — 새 공시를 받아 쌓는다 (계획 A3b).

큐: sec_crawl. API 의 캐치업 루프(`app/core/sec_sync.py`)가 주기표대로 넣는다.
원본 `13F기관내부자/src/collectors/{thirteen_f, form4, thirteen_dg}.py` 의 순서를 따른다 —
감시 CIK 의 `submissions` 최근 목록 → DB 에 없는 접수번호만 → 원문 XML → 파싱 → 적재.

- **13F**: 거장(`guru_roster.kind='guru'`, active). 13F-HR/A 는 표지의 `amendmentType` 을 적는다
  (RESTATEMENT 대체 / NEW HOLDINGS 합산 — 합치는 규칙은 API `core/guru13f.effective_accessions`).
- **Form 4**: 발행사 = 이미 추적하던 곳(기존 Form 4 의 watch_cik) + 내 보유 미국 종목 + 관심종목
  (티커 → CIK 는 SEC `company_tickers.json`). 4/A 는 같은 (발행사·내부자·거래일·코드)의 앞선
  거래에 `superseded_by` 를 적어 **이중 집계를 막는다**(A2 백필과 같은 규칙).
- **13D/G**: 위 발행사 + 거장. 표지 XML(2024-12 이후 구조화 서식)만 읽는다 — 구형 텍스트 공시는
  공시 색인만 남기고 `summary_json.parsed=false`.
- 신선도는 `source_status` 의 sec_13f · sec_form4 · sec_13dg 에(→ /data-operations).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from sec.client import SecBlocked, SecConfigError, sec_client, sec_get
from sec.ownership import cik10, parse_13dg, parse_form4
from sec.parsers import parse_cover_amendment, parse_infotable, pick_infotable, submissions_rows
from source_health import classify_error, record_error, record_ok

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
PAGE = "https://data.sec.gov/submissions/{name}"
TICKERS = "https://www.sec.gov/files/company_tickers.json"

# 처음 보는 발행사도 이만큼 거슬러 받는다 — 내부자 화면의 "최근 90일"을 채우고도 남게.
LOOKBACK_DAYS = int(os.environ.get("SEC_LOOKBACK_DAYS", "180"))
FORM4_FORMS = {"4", "4/A"}
DG_FORMS = {"SC 13D": "13D", "SC 13D/A": "13D", "SC 13G": "13G", "SC 13G/A": "13G",
            "SCHEDULE 13D": "13D", "SCHEDULE 13D/A": "13D", "SCHEDULE 13G": "13G", "SCHEDULE 13G/A": "13G"}


def _client():
    return sec_client(require_ua=True)


def _d(v) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _nodash(acc: str) -> str:
    return acc.replace("-", "")


def _recent(client, cik: str) -> tuple[list[dict], str]:
    resp = sec_get(client, SUBMISSIONS.format(cik=cik))
    if resp.status_code != 200:          # 404 = 그 CIK 의 제출 목록이 없다(상장폐지 등)
        return [], ""
    j = resp.json()
    return submissions_rows(j["filings"]["recent"]), j.get("name") or ""


def _known(engine, accs: list[str]) -> set[str]:
    if not accs:
        return set()
    with engine.begin() as c:
        return {a for (a,) in c.execute(text(
            "SELECT DISTINCT accession_number FROM sec_filings WHERE accession_number = ANY(:a)"), {"a": accs})}


def _new(engine, rows: list[dict], forms, since: date) -> list[dict]:
    rows = [r for r in rows if r["form"] in forms and (_d(r["filingDate"]) or date.min) >= since]
    have = _known(engine, [r["accessionNumber"] for r in rows])
    # 오래된 것부터 — 목록은 최신순이라 그대로 넣으면 4/A 가 원 공시보다 먼저 들어가 대체가 안 걸린다.
    return sorted((r for r in rows if r["accessionNumber"] not in have),
                  key=lambda r: (r["filingDate"], r["accessionNumber"]))


def _insert_filing(c, **f) -> None:
    c.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, filing_date, period_of_report, issuer_name, "
        "issuer_cik, filer_name, filer_cik, watch_cik, watch_name, amendment_type, headline, summary_json, "
        "source_url) VALUES (:form_type, :accession_number, :filing_date, :period_of_report, :issuer_name, "
        ":issuer_cik, :filer_name, :filer_cik, :watch_cik, :watch_name, :amendment_type, :headline, "
        "CAST(:summary_json AS JSONB), :source_url) ON CONFLICT (accession_number, form_type) DO NOTHING"),
        {"period_of_report": None, "issuer_name": None, "issuer_cik": None, "filer_name": None, "filer_cik": None,
         "amendment_type": None, "headline": None, "summary_json": None, **f})


def _guarded(engine, source: str, job_log, fn):
    """차단·설정 오류를 원천 상태에 종류대로 적고 작업은 실패로 끝낸다(재시도는 다음 주기)."""
    try:
        result = fn()
    except SecConfigError as exc:
        record_error(engine, source, "config", str(exc))
        raise
    except SecBlocked as exc:
        record_error(engine, source, "403", str(exc))
        raise
    except httpx.HTTPError as exc:
        record_error(engine, source, classify_error(exc), str(exc))
        raise
    record_ok(engine, source, detail=result)
    job_log("INFO", f"{source}: {result}")
    return result


# ── 13F ───────────────────────────────────────────────────────────────────────


def _infotable(client, cik: str, acc: str) -> list[dict] | None:
    idx = sec_get(client, INDEX.format(cik=int(cik), acc=_nodash(acc)))
    if idx.status_code != 200:
        return None
    name = pick_infotable(idx.json())
    if not name:
        return None
    doc = sec_get(client, ARCHIVE.format(cik=int(cik), acc=_nodash(acc), doc=name))
    return parse_infotable(doc.text) if doc.status_code == 200 else None


def store_13f(engine, client, cik: str, name: str, r: dict) -> tuple[str, str | None, int | None]:
    """13F 공시 한 건: (/A 면 표지의 정정 종류) + 정보표 → 적재. 돌려줌 = (접수번호, 정정 종류, 보유행 수 | None=정보표 없음)."""
    acc = r["accessionNumber"]
    amend = None
    if r["form"] == "13F-HR/A":
        doc = r["primaryDocument"].split("/")[-1] or "primary_doc.xml"
        cover = sec_get(client, ARCHIVE.format(cik=int(cik), acc=_nodash(acc), doc=doc))
        _, amend = parse_cover_amendment(cover.text) if cover.status_code == 200 else (True, None)
    holdings = _infotable(client, cik, acc)
    if holdings is None:
        # 정보표를 못 받았으면 색인도 넣지 않는다 — 넣으면 "받은 공시"로 보여 다음 주기에 다시 안 받는다.
        return acc, amend, None
    with engine.begin() as c:
        _insert_filing(c, form_type=r["form"], accession_number=acc, filing_date=_d(r["filingDate"]),
                       period_of_report=_d(r["reportDate"]), filer_cik=cik, filer_name=name,
                       watch_cik=cik, watch_name=name, amendment_type=amend,
                       headline=f"{r['form']} · {name} · {r['reportDate']} · {len(holdings)}종목",
                       source_url=ARCHIVE.format(cik=int(cik), acc=_nodash(acc), doc=""))
        c.execute(text("DELETE FROM holdings_13f WHERE accession_number = :a"), {"a": acc})
        if holdings:
            c.execute(text(
                "INSERT INTO holdings_13f (accession_number, seq, name_of_issuer, title_of_class, cusip, "
                "value, shares, shr_type, put_call, investment_discretion, vote_sole, vote_shared, "
                "vote_none) VALUES (:acc, :seq, :name_of_issuer, :title_of_class, :cusip, :value, :shares, "
                ":shr_type, :put_call, :investment_discretion, :vote_sole, :vote_shared, :vote_none)"),
                [dict(h, acc=acc, seq=i, cusip=(h["cusip"] or None) and h["cusip"][:9],
                      put_call=h["put_call"] or None, shr_type=h["shr_type"] or None)
                 for i, h in enumerate(holdings)])
    return acc, amend, len(holdings)


def collect_13f(engine, client) -> dict:
    with engine.begin() as c:
        roster = c.execute(text(
            "SELECT cik, COALESCE(guru_name, firm), backfill_from FROM guru_roster "
            "WHERE kind = 'guru' AND active ORDER BY cik")).all()
    added, amendments, empty = [], {}, []
    for cik, name, backfill_from in roster:
        rows, _ = _recent(client, cik)
        rows = [r for r in rows if (r["reportDate"] or "") >= str(backfill_from)]
        for r in _new(engine, rows, {"13F-HR", "13F-HR/A"}, backfill_from):
            acc, amend, n = store_13f(engine, client, cik, name, r)
            if r["form"] == "13F-HR/A":
                amendments[amend or "unknown"] = amendments.get(amend or "unknown", 0) + 1
            if n is None:
                empty.append(acc)
            else:
                added.append(acc)
    return {"gurus": len(roster), "added": len(added), "amendments": amendments, "no_infotable": empty}


def _all_submissions(client, cik: str) -> list[dict]:
    """최근 목록 + 과거 페이지 전부(13F 는 2013 년부터 — 최근 목록 1,000건만으론 모자랄 수 있다)."""
    resp = sec_get(client, SUBMISSIONS.format(cik=cik))
    if resp.status_code != 200:
        return []
    j = resp.json()
    rows = submissions_rows(j["filings"]["recent"])
    for f in j["filings"].get("files") or []:
        page = sec_get(client, PAGE.format(name=f["name"]))
        if page.status_code == 200:
            rows += submissions_rows(page.json())
    return rows


def backfill_guru(engine, client, cik: str) -> dict:
    """새 거장의 13F 이력을 SEC 에서 직접 채운다(계획 A7). 원본 DB 가 아니라 SEC — 새 거장은 원본에 없다.

    `backfill_from`(기본 2013-04-01 — 그 전 13F 는 XML 이 아닌 텍스트라 파서가 못 읽는다)부터,
    13F-HR/A 는 A3b 와 같은 규칙(표지 amendmentType: RESTATEMENT 대체 / NEW HOLDINGS 합산 — 합치기는 API).
    상태: pending → running → done | failed(note 에 이유). 다시 돌려도 이미 받은 접수번호는 건너뛴다.
    """
    with engine.begin() as c:
        row = c.execute(text("SELECT COALESCE(guru_name, firm), backfill_from FROM guru_roster WHERE cik = :c"),
                        {"c": cik}).one_or_none()
        if row is None:
            return {"cik": cik, "error": "명단에 없음"}
        c.execute(text("UPDATE guru_roster SET backfill_status = 'running', note = NULL WHERE cik = :c"), {"c": cik})
    name, backfill_from = row
    try:
        rows = [r for r in _all_submissions(client, cik) if (r["reportDate"] or "") >= str(backfill_from)]
        todo = _new(engine, rows, {"13F-HR", "13F-HR/A"}, backfill_from)
        added = empty = 0
        amendments: dict[str, int] = {}
        for r in todo:
            _, amend, n = store_13f(engine, client, cik, name, r)
            if r["form"] == "13F-HR/A":
                amendments[amend or "unknown"] = amendments.get(amend or "unknown", 0) + 1
            added += n is not None
            empty += n is None
        periods = len({r["reportDate"] for r in rows if r["form"] in ("13F-HR", "13F-HR/A")})
    except Exception as exc:
        with engine.begin() as c:
            c.execute(text("UPDATE guru_roster SET backfill_status = 'failed', note = :n WHERE cik = :c"),
                      {"c": cik, "n": f"{type(exc).__name__}: {exc}"[:500]})
        raise
    result = {"cik": cik, "periods": periods, "added": added, "no_infotable": empty, "amendments": amendments}
    with engine.begin() as c:
        c.execute(text("UPDATE guru_roster SET backfill_status = 'done', note = :n WHERE cik = :c"),
                  {"c": cik, "n": f"SEC 백필 {periods}분기 · 새 공시 {added}건 · 정보표 없음 {empty}건"})
        # 새 CUSIP 의 티커·섹터를 바로 채운다(하루 1회 주기를 기다리지 않게)
        c.execute(text(
            "INSERT INTO jobs (id, job_type, status, queue, payload) SELECT gen_random_uuid(), 'CUSIP_RESOLVE', "
            "'PENDING', 'sec_crawl', CAST(:p AS JSONB) WHERE NOT EXISTS (SELECT 1 FROM jobs "
            "WHERE job_type = 'CUSIP_RESOLVE' AND status IN ('PENDING', 'RUNNING'))"),
            {"p": json.dumps({"after_backfill": cik})})
    return result


def run_backfill(engine, job_id, payload, storage_dir, log_job):
    """SEC_13F_BACKFILL — payload.cik 가 있으면 그 거장, 없으면 pending 인 거장 전부."""
    def go():
        with _client() as client:
            if (payload or {}).get("cik"):
                ciks = [payload["cik"]]
            else:
                with engine.begin() as c:
                    ciks = [k for (k,) in c.execute(text(
                        "SELECT cik FROM guru_roster WHERE kind = 'guru' AND active AND backfill_status = 'pending'"))]
            return {"gurus": [backfill_guru(engine, client, c) for c in ciks]}

    return _guarded(engine, "sec_13f", lambda lv, m: log_job(engine, job_id, lv, "done", m), go)


# ── Form 4 ────────────────────────────────────────────────────────────────────


def _ticker_ciks(client, tickers: set[str]) -> dict[str, str]:
    if not tickers:
        return {}
    data = sec_get(client, TICKERS).json()
    by = {str(v["ticker"]).upper(): cik10(v["cik_str"]) for v in data.values()}
    return {t: by[t] for t in tickers if t in by}


def watch_issuers(engine, client) -> dict[str, str]:
    """{CIK: 이름} — 이미 추적하던 발행사 + 내 미국 보유 + 관심종목."""
    with engine.begin() as c:
        tracked = dict(c.execute(text(
            "SELECT DISTINCT ON (watch_cik) watch_cik, watch_name FROM sec_filings "
            "WHERE form_type IN ('4', '4/A') AND watch_cik IS NOT NULL ORDER BY watch_cik, filing_date DESC")).all())
        tickers = {t.upper() for (t,) in c.execute(text(
            "SELECT a.ticker FROM current_positions p JOIN assets a ON a.id = p.asset_id "
            "WHERE a.country = 'US' AND p.quantity > 0 UNION SELECT ticker FROM watchlist_items"))}
    for t, cik in _ticker_ciks(client, tickers).items():
        tracked.setdefault(cik, t)
    return tracked


def _form4_headline(rows: list[dict]) -> tuple[str, dict]:
    first = rows[0] if rows else {}
    buy = sum(r["shares"] or 0 for r in rows if r["buy_sell"] == "BUY" and not r["is_derivative"])
    sell = sum(r["shares"] or 0 for r in rows if r["buy_sell"] == "SELL" and not r["is_derivative"])
    net = sum((r["transaction_value"] or 0) * (1 if r["buy_sell"] == "BUY" else -1)
              for r in rows if r["buy_sell"] in ("BUY", "SELL") and not r["is_derivative"])
    action = f"BUY {buy:,.0f}" if buy and not sell else f"SELL {sell:,.0f}" if sell and not buy else \
        f"BUY {buy:,.0f} / SELL {sell:,.0f}" if buy else "보유변동"
    headline = (f"{first.get('insider_name')} ({first.get('insider_role')}) [{first.get('ticker')}] "
                f"{action} · {first.get('issuer_name')}")
    summary = {"n_tx": len(rows), "codes": sorted({r["transaction_code"] for r in rows if r["transaction_code"]}),
               "ticker": first.get("ticker"), "planned": any(r["is_planned_trade"] for r in rows),
               "net_value": net, "buy_shares": buy, "sell_shares": sell,
               "issuer_name": first.get("issuer_name"), "insider_name": first.get("insider_name"),
               "insider_role": first.get("insider_role")}
    return headline, summary


def store_form4(engine, *, acc: str, form: str, filing_date, url: str, watch_cik: str, watch_name: str,
                rows: list[dict], owners: list[dict]) -> int:
    """Form 4 한 건 적재. 4/A 면 앞선 같은 거래를 대체 표시하고 대체한 행 수를 돌려준다."""
    headline, summary = _form4_headline(rows)
    summary["owners"] = owners
    first = rows[0] if rows else {}
    with engine.begin() as c:
        _insert_filing(c, form_type=form, accession_number=acc, filing_date=filing_date,
                       period_of_report=first.get("transaction_date"),
                       issuer_name=first.get("issuer_name"), issuer_cik=first.get("issuer_cik") or watch_cik,
                       filer_name=first.get("insider_name"), filer_cik=first.get("insider_cik"),
                       watch_cik=watch_cik, watch_name=watch_name, headline=headline[:1000],
                       summary_json=json.dumps(summary, default=str), source_url=url)
        c.execute(text("DELETE FROM form4_transactions WHERE accession_number = :a"), {"a": acc})
        if rows:
            c.execute(text(
                "INSERT INTO form4_transactions (accession_number, seq, issuer_name, issuer_cik, ticker, "
                "insider_name, insider_cik, insider_role, transaction_date, transaction_code, "
                "transaction_description, buy_sell, shares, price, transaction_value, shares_owned_after, "
                "ownership_type, acquired_disposed, is_derivative, is_open_market, is_option_exercise, "
                "is_planned_trade) VALUES (:acc, :seq, :issuer_name, :issuer_cik, :ticker, :insider_name, "
                ":insider_cik, :insider_role, :transaction_date, :transaction_code, :transaction_description, "
                ":buy_sell, :shares, :price, :transaction_value, :shares_owned_after, :ownership_type, "
                ":acquired_disposed, :is_derivative, :is_open_market, :is_option_exercise, :is_planned_trade)"),
                [dict(r, acc=acc, seq=i) for i, r in enumerate(rows)])
        if form == "4/A":
            # 정정본이 같은 (발행사·내부자·거래일·코드)의 다른 행을 대체한다.
            return c.execute(text(
                "UPDATE form4_transactions o SET superseded_by = :a FROM form4_transactions n "
                "WHERE n.accession_number = :a AND o.accession_number <> :a AND o.superseded_by IS NULL "
                "AND o.issuer_cik = n.issuer_cik AND o.insider_cik = n.insider_cik "
                "AND o.transaction_date = n.transaction_date AND o.transaction_code = n.transaction_code"),
                {"a": acc}).rowcount
        # 순서가 뒤집힌 경우 — 정정본이 먼저 들어와 있으면 새 원 공시 행이 대체된다
        # (실측: 같은 날 4/A 가 원 공시보다 앞 접수번호로 먼저 접수된 사례, ONTO 2026-09-04).
        return c.execute(text(
            "UPDATE form4_transactions n SET superseded_by = a.accession_number "
            "FROM form4_transactions a JOIN sec_filings fa ON fa.accession_number = a.accession_number "
            "AND fa.form_type = '4/A' "
            "WHERE n.accession_number = :a AND a.accession_number <> :a AND n.superseded_by IS NULL "
            "AND a.superseded_by IS NULL AND n.issuer_cik = a.issuer_cik AND n.insider_cik = a.insider_cik "
            "AND n.transaction_date = a.transaction_date AND n.transaction_code = a.transaction_code"),
            {"a": acc}).rowcount


def collect_form4(engine, client, now: datetime | None = None) -> dict:
    since = (now or datetime.now(timezone.utc)).date() - timedelta(days=LOOKBACK_DAYS)
    issuers = watch_issuers(engine, client)
    added = superseded = failed = 0
    latest = None
    for cik, watch_name in sorted(issuers.items()):
        rows, sec_name = _recent(client, cik)
        for r in _new(engine, rows, FORM4_FORMS, since):
            acc = r["accessionNumber"]
            doc = r["primaryDocument"].split("/")[-1]      # 'xslF345X05/form4.xml' → 사람이 보는 HTML 말고 XML
            url = ARCHIVE.format(cik=int(cik), acc=_nodash(acc), doc=doc)
            resp = sec_get(client, url)
            try:
                tx, owners = parse_form4(resp.text) if resp.status_code == 200 else (None, None)
            except Exception:
                tx = None
            if tx is None:
                failed += 1
                continue
            superseded += store_form4(engine, acc=acc, form=r["form"], filing_date=_d(r["filingDate"]), url=url,
                                      watch_cik=cik, watch_name=sec_name or watch_name, rows=tx, owners=owners)
            added += 1
            latest = max(latest or r["filingDate"], r["filingDate"])
    return {"issuers": len(issuers), "added": added, "superseded": superseded, "failed": failed,
            "latest_filing": latest}


# ── 13D/G ─────────────────────────────────────────────────────────────────────


def collect_13dg(engine, client, now: datetime | None = None) -> dict:
    since = (now or datetime.now(timezone.utc)).date() - timedelta(days=LOOKBACK_DAYS)
    watch = watch_issuers(engine, client)
    with engine.begin() as c:
        for cik, name in c.execute(text("SELECT cik, COALESCE(guru_name, firm) FROM guru_roster "
                                        "WHERE kind = 'guru' AND active")):
            watch.setdefault(cik, name)
    added = parsed = 0
    for cik, watch_name in sorted(watch.items()):
        rows, sec_name = _recent(client, cik)
        for r in _new(engine, rows, DG_FORMS, since):
            acc = r["accessionNumber"]
            form = DG_FORMS[r["form"]]
            url = ARCHIVE.format(cik=int(cik), acc=_nodash(acc), doc="primary_doc.xml")
            resp = sec_get(client, url)
            ev = parse_13dg(resp.text) if resp.status_code == 200 else None
            amend = r["form"].endswith("/A")
            summary = {"parsed": ev is not None, "amendment": amend, "activist": form == "13D",
                       **({"subject": ev["subject_name"], "cusip": ev["cusip"], "percent": ev["percent"],
                           "shares": ev["shares"], "event_date": str(ev["event_date"] or "")} if ev else {})}
            pct = f" · {ev['percent']:g}%" if ev and ev["percent"] is not None else ""
            subject = (ev or {}).get("subject_name") or sec_name or watch_name
            with engine.begin() as c:
                _insert_filing(c, form_type=form, accession_number=acc, filing_date=_d(r["filingDate"]),
                               issuer_name=subject, issuer_cik=(ev or {}).get("subject_cik"),
                               watch_cik=cik, watch_name=sec_name or watch_name,
                               headline=f"{form}{'/A' if amend else ''} · {subject}{pct}",
                               summary_json=json.dumps(summary), source_url=url)
                if ev:
                    c.execute(text(
                        "INSERT INTO ownership_events (accession_number, seq, subject_name, subject_cik, cusip, "
                        "percent, shares, event_date, is_amendment, is_activist) VALUES (:acc, 0, :subject_name, "
                        ":subject_cik, :cusip, :percent, :shares, :event_date, :amend, :activist)"),
                        dict(ev, acc=acc, amend=amend, activist=form == "13D"))
                    parsed += 1
            added += 1
    return {"watch": len(watch), "added": added, "parsed": parsed}


# ── 작업 진입점 ──────────────────────────────────────────────────────────────


def _run(source: str, collect):
    def run(engine, job_id, payload, storage_dir, log_job):
        def job_log(level, msg):
            log_job(engine, job_id, level, "done", msg)

        def go():
            with _client() as client:
                return collect(engine, client)

        return _guarded(engine, source, job_log, go)
    return run


run_13f = _run("sec_13f", collect_13f)
run_form4 = _run("sec_form4", collect_form4)
run_13dg = _run("sec_13dg", collect_13dg)
