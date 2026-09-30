"""계획 A2 — 원본 `13F기관내부자/db/filings.db` → Postgres 백필 + SEC 대조 보정.

    .venv/bin/python scripts/backfill_sec_from_filings_db.py [--db PATH] [--reset] [--offline]

단계
  1. 원본 이관(네트워크 없음)
     - 거장 23명(`guru_roster.kind='guru'`)의 13F 공시·보유행 — 퀀트·인덱스 12곳(보유행의 92%)은 제외(사용자 결정 1)
     - Form 4 거래 · 13D/13G · 그 공시 색인, `cusip_ref` → `cusip_map`
  2. 거장 SEC 대조 (`--offline` 이면 건너뜀)
     - 원본은 13F-HR 과 13F-HR/A 를 모두 '13F' 로만 적었다 → 제출 목록으로 **양식을 되살리고**,
       /A 는 표지를 받아 **RESTATEMENT / NEW HOLDINGS** 를 적는다(계획 §A — 버크셔 1종목 버그).
     - SEC 에는 있는데 원본에 없는 분기(실측 30개: 버핏·Gayner 각 12, Icahn 6)를 **새로 받는다**.
     - 보유행 0개인 공시(실측 2건)의 정보표를 다시 받는다.
  3. Form 4/A 대체 (`--offline` 이면 건너뜀)
     - 원본은 4/A 도 '4' 로 적어 **이중 집계**했다. 추적 기업 22곳의 제출 목록으로 4/A 를 찾아,
       같은 (발행사, 내부자, 거래일, 거래코드)의 **앞선 Form 4 거래**에 `superseded_by` 를 단다.
     - ⚠️원본 파서는 **첫 보고자만** 읽었다 — 공동 신고의 나머지 보고자는 과거분에 없다(알려진 공백,
       새로 들어오는 공시는 A3b 파서가 전부 읽는다). 원문 재파싱은 하지 않는다.
  4. 대조 보고 — 거장 × 분기가 SEC 와 같은지, 정정 종류를 모르는 /A 가 남았는지, 버크셔 2023Q3.
     통과하면 `guru_roster.backfill_status='done'`.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "worker"))
sys.path.insert(0, str(REPO / "apps" / "api"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.guru13f import Filing13F, effective_accessions  # noqa: E402
from sec.client import SecBlocked, sec_client, sec_get  # noqa: E402
from sec.parsers import parse_cover_amendment, parse_infotable, pick_infotable, submissions_rows  # noqa: E402
from source_health import record_error, record_ok  # noqa: E402

DEFAULT_DB = Path.home() / "Downloads" / "13F기관내부자" / "db" / "filings.db"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
PAGE = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
SEC_TABLES = ("holdings_13f", "form4_transactions", "ownership_events", "sec_filings", "cusip_map")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def _env_local(name: str) -> None:
    if os.environ.get(name):
        return
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            os.environ[name] = line.split("=", 1)[1].strip().strip('"').strip("'")


def _d(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _cik(v):
    v = (v or "").strip()
    return v.zfill(10) if v.isdigit() else (v or None)


def _json(v):
    if not v:
        return None
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


# ── 1. 원본 이관 ──────────────────────────────────────────────────────────────


def stage_import(src: sqlite3.Connection, eng, gurus: set[str]) -> dict:
    s = src.cursor()
    stats = {}
    guru_filings = [
        r for r in s.execute(
            "SELECT form_type, accession_number, filing_date, period_of_report, issuer_name, issuer_cik, "
            "filer_name, filer_cik, watch_cik, watch_name, headline, summary_json, source_url, crawled_at "
            "FROM filings WHERE form_type = '13F'"
        )
        if _cik(r[8]) in gurus
    ]
    other_filings = list(s.execute(
        "SELECT form_type, accession_number, filing_date, period_of_report, issuer_name, issuer_cik, "
        "filer_name, filer_cik, watch_cik, watch_name, headline, summary_json, source_url, crawled_at "
        "FROM filings WHERE form_type IN ('4', '13D', '13G')"
    ))
    ins_filing = text(
        "INSERT INTO sec_filings (form_type, accession_number, filing_date, period_of_report, issuer_name, "
        "issuer_cik, filer_name, filer_cik, watch_cik, watch_name, headline, summary_json, source_url, crawled_at) "
        "VALUES (:form, :acc, :fd, :pd, :iname, :icik, :fname, :fcik, :wcik, :wname, :head, CAST(:sj AS JSONB), "
        ":url, :crawled) ON CONFLICT (accession_number, form_type) DO NOTHING"
    )

    def filing_params(r, form):
        return {
            "form": form, "acc": r[1], "fd": _d(r[2]), "pd": _d(r[3]), "iname": r[4] or None,
            "icik": _cik(r[5]), "fname": r[6] or None, "fcik": _cik(r[7]), "wcik": _cik(r[8]),
            "wname": r[9] or None, "head": r[10] or None,
            "sj": json.dumps(_json(r[11])) if _json(r[11]) is not None else None,
            "url": r[12] or None, "crawled": r[13] or datetime.now(timezone.utc).isoformat(),
        }

    with eng.begin() as c:
        # 13F 양식(원본 HR / 정정 HR/A)은 2단계에서 SEC 로 되살린다 — 우선 '13F-HR' 로 둔다.
        c.execute(ins_filing, [filing_params(r, "13F-HR") for r in guru_filings])
        c.execute(ins_filing, [filing_params(r, r[0]) for r in other_filings])
    stats["filings_13f"] = len(guru_filings)
    stats["filings_other"] = len(other_filings)

    accs = [r[1] for r in guru_filings]
    rows = []
    for i in range(0, len(accs), 500):
        chunk = accs[i:i + 500]
        rows += list(s.execute(
            f"SELECT accession_number, seq, name_of_issuer, title_of_class, cusip, value, shares, shr_type, "
            f"put_call, investment_discretion, vote_sole, vote_shared, vote_none FROM holdings_13f "
            f"WHERE accession_number IN ({','.join('?' * len(chunk))})", chunk,
        ))
    cols = ("acc", "seq", "name", "cls", "cusip", "value", "shares", "shr", "pc", "disc", "vs", "vsh", "vn")
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO holdings_13f (accession_number, seq, name_of_issuer, title_of_class, cusip, value, shares, "
            "shr_type, put_call, investment_discretion, vote_sole, vote_shared, vote_none) VALUES "
            "(:acc, :seq, :name, :cls, :cusip, :value, :shares, :shr, :pc, :disc, :vs, :vsh, :vn)"
        ), [dict(zip(cols, [x if x != "" else None for x in r])) for r in rows])
    stats["holdings_13f"] = len(rows)

    f4 = list(s.execute(
        "SELECT accession_number, seq, issuer_name, issuer_cik, ticker, insider_name, insider_cik, insider_role, "
        "transaction_date, transaction_code, transaction_description, buy_sell, shares, price, transaction_value, "
        "shares_owned_after, ownership_type, acquired_disposed, is_derivative, is_open_market, "
        "is_option_exercise, is_planned_trade FROM form4_transactions"
    ))
    today = date.today()
    future = [r for r in f4 if _d(r[8]) and _d(r[8]) > today]
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO form4_transactions (accession_number, seq, issuer_name, issuer_cik, ticker, insider_name, "
            "insider_cik, insider_role, transaction_date, transaction_code, transaction_description, buy_sell, shares, "
            "price, transaction_value, shares_owned_after, ownership_type, acquired_disposed, is_derivative, "
            "is_open_market, is_option_exercise, is_planned_trade) VALUES (:a, :seq, :iname, :icik, :tk, :ins, :inscik, "
            ":role, :td, :code, :desc, :bs, :sh, :px, :val, :after, :own, :ad, :der, :om, :opt, :plan)"
        ), [
            {"a": r[0], "seq": r[1] or 0, "iname": r[2] or None, "icik": _cik(r[3]), "tk": r[4] or None,
             "ins": r[5] or None, "inscik": _cik(r[6]), "role": r[7] or None, "td": _d(r[8]),
             "code": r[9] or None, "desc": r[10] or None, "bs": r[11] or None, "sh": r[12], "px": r[13],
             "val": r[14], "after": r[15], "own": r[16] or None, "ad": (r[17] or None) and r[17][:1],
             "der": bool(r[18]), "om": bool(r[19]), "opt": bool(r[20]), "plan": bool(r[21])}
            for r in f4
        ])
    stats["form4_transactions"] = len(f4)
    stats["form4_future_dated"] = [(r[0], r[4], r[8]) for r in future]

    oe = list(s.execute(
        "SELECT accession_number, seq, subject_name, subject_cik, cusip, filer_name, percent, shares, event_date, "
        "is_amendment, is_activist FROM ownership_events"
    ))
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO ownership_events (accession_number, seq, subject_name, subject_cik, cusip, filer_name, "
            "percent, shares, event_date, is_amendment, is_activist) VALUES (:a, :seq, :sn, :sc, :cu, :fn, :pct, "
            ":sh, :ed, :am, :act)"
        ), [
            {"a": r[0], "seq": r[1] or 0, "sn": r[2] or None, "sc": _cik(r[3]), "cu": (r[4] or None) and r[4][:9],
             "fn": r[5] or None, "pct": r[6], "sh": r[7], "ed": _d(r[8]), "am": bool(r[9]), "act": bool(r[10])}
            for r in oe
        ])
    stats["ownership_events"] = len(oe)

    cr = list(s.execute("SELECT cusip, name, ticker, ticker_confidence FROM cusip_ref"))
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO cusip_map (cusip, name, ticker, confidence) VALUES (:c, :n, :t, :conf) "
            "ON CONFLICT (cusip) DO NOTHING"
        ), [{"c": r[0][:9], "n": r[1] or None, "t": r[2] or None, "conf": r[3] or "none"} for r in cr if r[0]])
    stats["cusip_map"] = len(cr)
    return stats


# ── 2·3. SEC 대조 ─────────────────────────────────────────────────────────────


def fetch_all_submissions(client, cik: str) -> tuple[list[dict], str]:
    j = sec_get(client, SUBMISSIONS.format(cik=cik)).json()
    rows = submissions_rows(j["filings"]["recent"])
    for f in j["filings"].get("files") or []:
        rows += submissions_rows(sec_get(client, PAGE.format(name=f["name"])).json())
    return rows, j.get("name") or ""


def _fetch_infotable(client, cik: str, acc: str) -> list[dict] | None:
    nodash = acc.replace("-", "")
    idx = sec_get(client, INDEX.format(cik=int(cik), acc=nodash))
    if idx.status_code != 200:
        return None
    name = pick_infotable(idx.json())
    if not name:
        return None
    doc = sec_get(client, ARCHIVE.format(cik=int(cik), acc=nodash, doc=name))
    return parse_infotable(doc.text) if doc.status_code == 200 else None


def _insert_holdings(c, acc: str, rows: list[dict]) -> None:
    c.execute(text("DELETE FROM holdings_13f WHERE accession_number = :a"), {"a": acc})
    if rows:
        c.execute(text(
            "INSERT INTO holdings_13f (accession_number, seq, name_of_issuer, title_of_class, cusip, value, shares, "
            "shr_type, put_call, investment_discretion, vote_sole, vote_shared, vote_none) VALUES "
            "(:acc, :seq, :name_of_issuer, :title_of_class, :cusip, :value, :shares, :shr_type, :put_call, "
            ":investment_discretion, :vote_sole, :vote_shared, :vote_none)"
        ), [dict(r, acc=acc, seq=i, cusip=(r["cusip"] or None) and r["cusip"][:9],
                 put_call=r["put_call"] or None, shr_type=r["shr_type"] or None) for i, r in enumerate(rows)])


def stage_gurus(eng, client, roster: list[tuple]) -> dict:
    report = {"forms_fixed": 0, "amendments": defaultdict(int), "added_periods": [], "refetched_empty": [],
              "unknown_amend": [], "per_guru": {}}
    for cik, guru, backfill_from in roster:
        subs, _name = fetch_all_submissions(client, cik)
        f13 = [r for r in subs if r["form"] in ("13F-HR", "13F-HR/A") and (r["reportDate"] or "") >= str(backfill_from)]
        with eng.begin() as c:
            have = {a: (fd, pd) for a, fd, pd in c.execute(text(
                "SELECT accession_number, filing_date, period_of_report FROM sec_filings "
                "WHERE watch_cik = :w AND form_type LIKE '13F%'"), {"w": cik})}
        for r in f13:
            acc = r["accessionNumber"]
            amend_type = None
            if r["form"] == "13F-HR/A":
                doc = r["primaryDocument"].split("/")[-1] or "primary_doc.xml"
                cover = sec_get(client, ARCHIVE.format(cik=int(cik), acc=acc.replace("-", ""), doc=doc))
                _, amend_type = parse_cover_amendment(cover.text) if cover.status_code == 200 else (True, None)
                report["amendments"][amend_type or "unknown"] += 1
            with eng.begin() as c:
                if acc in have:
                    c.execute(text(
                        "UPDATE sec_filings SET form_type = :f, amendment_type = :t WHERE accession_number = :a "
                        "AND form_type LIKE '13F%'"), {"f": r["form"], "t": amend_type, "a": acc})
                    report["forms_fixed"] += r["form"] == "13F-HR/A"
                else:
                    c.execute(text(
                        "INSERT INTO sec_filings (form_type, accession_number, filing_date, period_of_report, "
                        "filer_cik, filer_name, watch_cik, watch_name, amendment_type, source_url, headline) "
                        "VALUES (:f, :a, :fd, :pd, :w, :wn, :w, :wn, :t, :url, 'SEC 대조로 새로 받음(A2)') "
                        "ON CONFLICT (accession_number, form_type) DO NOTHING"),
                        {"f": r["form"], "a": acc, "fd": _d(r["filingDate"]), "pd": _d(r["reportDate"]), "w": cik,
                         "wn": guru, "t": amend_type,
                         "url": ARCHIVE.format(cik=int(cik), acc=acc.replace("-", ""), doc="")})
                    holdings = _fetch_infotable(client, cik, acc) or []
                    _insert_holdings(c, acc, holdings)
                    report["added_periods"].append((guru, r["reportDate"], acc, len(holdings)))
        # 원본에서 보유행이 0개였던 공시 다시 받기
        with eng.begin() as c:
            empty = [a for (a,) in c.execute(text(
                "SELECT f.accession_number FROM sec_filings f WHERE f.watch_cik = :w AND f.form_type LIKE '13F%' "
                "AND NOT EXISTS (SELECT 1 FROM holdings_13f h WHERE h.accession_number = f.accession_number)"),
                {"w": cik})]
        for acc in empty:
            holdings = _fetch_infotable(client, cik, acc)
            with eng.begin() as c:
                if holdings:
                    _insert_holdings(c, acc, holdings)
            report["refetched_empty"].append((guru, acc, len(holdings or [])))
        sec_periods = {r["reportDate"] for r in f13 if r["form"] == "13F-HR"}
        with eng.begin() as c:
            db_periods = {str(p) for (p,) in c.execute(text(
                "SELECT DISTINCT period_of_report FROM sec_filings WHERE watch_cik = :w AND form_type LIKE '13F%' "
                "AND period_of_report >= :bf"), {"w": cik, "bf": backfill_from})}
        report["per_guru"][guru] = {"sec": len(sec_periods), "db": len(db_periods),
                                    "missing": sorted(sec_periods - db_periods)}
    return report


def stage_form4_amendments(eng, client, issuers: list[str]) -> dict:
    amended = []
    for cik in issuers:
        subs, _ = fetch_all_submissions(client, cik)
        amended += [r["accessionNumber"] for r in subs if r["form"] == "4/A"]
    with eng.begin() as c:
        present = [a for (a,) in c.execute(text(
            "SELECT DISTINCT accession_number FROM sec_filings WHERE form_type = '4' "
            "AND accession_number = ANY(:a)"), {"a": amended})]
        c.execute(text("UPDATE sec_filings SET form_type = '4/A' WHERE form_type = '4' AND accession_number = ANY(:a)"),
                  {"a": present})
        # 같은 (발행사, 내부자, 거래일, 거래코드)의 앞선 Form 4 거래를 정정본이 대체한다.
        superseded = c.execute(text(
            "UPDATE form4_transactions o SET superseded_by = a.accession_number "
            "FROM form4_transactions a "
            "WHERE a.accession_number = ANY(:a) AND o.accession_number <> a.accession_number "
            "AND NOT (o.accession_number = ANY(:a)) "
            "AND o.issuer_cik = a.issuer_cik AND o.insider_cik = a.insider_cik "
            "AND o.transaction_date = a.transaction_date AND o.transaction_code = a.transaction_code "
            "AND o.superseded_by IS NULL"), {"a": present}).rowcount
    return {"amendments_on_sec": len(amended), "amendments_in_db": len(present), "superseded_rows": superseded}


# ── 4. 대조 보고 ──────────────────────────────────────────────────────────────


def berkshire_check(eng) -> dict:
    with eng.begin() as c:
        rows = c.execute(text(
            "SELECT f.accession_number, f.filing_date, f.form_type, f.amendment_type, "
            "(SELECT count(*) FROM holdings_13f h WHERE h.accession_number = f.accession_number) "
            "FROM sec_filings f WHERE f.watch_cik = '0001067983' AND f.period_of_report = '2023-09-30' "
            "AND f.form_type LIKE '13F%'")).all()
    eff, warnings = effective_accessions([Filing13F(r[0], r[1], r[2], r[3]) for r in rows])
    counts = {r[0]: r[4] for r in rows}
    return {"filings": [tuple(r) for r in rows], "effective": eff, "rows": sum(counts[a] for a in eff),
            "warnings": warnings}


def unknown_amendments(eng) -> int:
    with eng.begin() as c:
        return c.execute(text(
            "SELECT count(*) FROM sec_filings WHERE form_type = '13F-HR/A' AND amendment_type IS NULL")).scalar()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--reset", action="store_true", help="SEC 표를 비우고 다시 싣는다(guru_roster 는 유지)")
    ap.add_argument("--offline", action="store_true", help="1단계(원본 이관)만")
    args = ap.parse_args()
    _env_local("SEC_USER_AGENT")

    eng = create_engine(_database_url())
    src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    with eng.begin() as c:
        if args.reset:
            c.execute(text(f"TRUNCATE {', '.join(SEC_TABLES)} RESTART IDENTITY"))
        roster = [tuple(r) for r in c.execute(text(
            "SELECT cik, guru_name, backfill_from FROM guru_roster WHERE kind = 'guru' AND active ORDER BY guru_name"))]
    gurus = {r[0] for r in roster}

    print("1) 원본 이관 …")
    s1 = stage_import(src, eng, gurus)
    print(json.dumps({k: v for k, v in s1.items()}, ensure_ascii=False, default=str))
    if args.offline:
        return 0

    watch = json.load(open(Path(args.db).parents[1] / "state" / "watchlist.json"))
    watch = watch if isinstance(watch, list) else watch.get("items", [])
    issuers = [x["cik"].zfill(10) for x in watch if x.get("role") == "issuer"]

    try:
        with sec_client(timeout=30, require_ua=True) as client:
            print("2) 거장 SEC 대조 …")
            s2 = stage_gurus(eng, client, roster)
            print("3) Form 4/A …")
            s3 = stage_form4_amendments(eng, client, issuers)
        record_ok(eng, "sec", detail={"backfill": "A2"})
    except SecBlocked as exc:
        record_error(eng, "sec", "403", str(exc))
        raise

    print(json.dumps({
        "forms_fixed_to_HR/A": s2["forms_fixed"], "amendment_types": dict(s2["amendments"]),
        "added_periods": len(s2["added_periods"]), "added_detail": s2["added_periods"],
        "refetched_empty": s2["refetched_empty"],
        "per_guru_mismatch": {g: v for g, v in s2["per_guru"].items() if v["missing"]},
        "form4": s3,
    }, ensure_ascii=False, default=str, indent=1))
    brk = berkshire_check(eng)
    unknown = unknown_amendments(eng)
    print("버크셔 2023Q3:", json.dumps(brk, ensure_ascii=False, default=str))
    print("정정 종류 모름:", unknown)
    ok = not any(v["missing"] for v in s2["per_guru"].values()) and unknown == 0 and brk["rows"] == 153
    if ok:
        with eng.begin() as c:
            c.execute(text("UPDATE guru_roster SET backfill_status = 'done' WHERE kind = 'guru' AND active"))
    print("완료 조건:", "통과 → backfill_status=done" if ok else "미통과 — 위 내역 확인")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
