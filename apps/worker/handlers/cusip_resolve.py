"""CUSIP_RESOLVE — 13F 보유 CUSIP 중 티커가 없는 것을 OpenFIGI → SEC 이름 일치로 채운다 (계획 A4).
이어서 티커가 붙은 CUSIP 의 섹터를 SEC SIC 로 채운다(`fill_sectors`, 계획 A5).

큐: sec_crawl. API 캐치업 루프가 하루 한 번 넣는다 — 새로 찾을 게 없으면 바로 끝난다.
대상 = 보유행에 나온 CUSIP 중 ① `cusip_map` 에 없거나 ② 티커가 없고 OpenFIGI 를 아직 안 물어본 것
(`figi IS NULL`). 최근 분기 · 큰 금액부터 — 한 회차 상한(`max_cusips`)에 걸려도 중요한 것부터 채워진다.
"""
from __future__ import annotations

import httpx
from sqlalchemy import text

from sec.client import sec_client, sec_get
from sec.cusip import BATCH, norm_name, openfigi_lookup, unique_name_map
from sec.ownership import cik10
from sec.sic import sic_to_sector
from source_health import classify_error, record_error, record_ok

TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_MAX = 3000          # 분당 250건 → 약 12분

_TARGETS = text(
    "SELECT h.cusip, max(h.name_of_issuer) AS name FROM holdings_13f h "
    "JOIN sec_filings f ON f.accession_number = h.accession_number AND f.form_type LIKE '13F%' "
    "LEFT JOIN cusip_map m ON m.cusip = h.cusip "
    "WHERE h.cusip IS NOT NULL AND length(h.cusip) = 9 "
    "AND (m.cusip IS NULL OR (m.ticker IS NULL AND m.figi IS NULL)) "
    "GROUP BY h.cusip ORDER BY max(f.period_of_report) DESC, sum(h.value) DESC NULLS LAST LIMIT :n"
)
_UPSERT = text(
    "INSERT INTO cusip_map (cusip, name, ticker, confidence, figi, updated_at) "
    "VALUES (:cusip, :name, :ticker, :confidence, :figi, now()) "
    "ON CONFLICT (cusip) DO UPDATE SET ticker = EXCLUDED.ticker, confidence = EXCLUDED.confidence, "
    "figi = EXCLUDED.figi, name = COALESCE(cusip_map.name, EXCLUDED.name), updated_at = now() "
    # 사람이 고친 것(manual)과 이미 붙은 티커는 덮지 않는다
    "WHERE cusip_map.confidence <> 'manual' AND cusip_map.ticker IS NULL"
)


def _figi_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers={"Content-Type": "application/json"})


def resolve(engine, figi_client, sec, max_cusips: int = DEFAULT_MAX) -> dict:
    with engine.begin() as c:
        targets = c.execute(_TARGETS, {"n": max_cusips}).all()
    if not targets:
        return {"targets": 0}
    names: dict[str, str] | None = None
    stats = {"targets": len(targets), "openfigi": 0, "exact": 0, "none": 0}
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        hits = openfigi_lookup(figi_client, [t.cusip for t in chunk])
        rows = []
        for t, hit in zip(chunk, hits):
            if hit:
                rows.append({"cusip": t.cusip, "name": t.name or hit["name"], "ticker": hit["ticker"],
                             "confidence": "openfigi", "figi": hit["figi"]})
                stats["openfigi"] += 1
                continue
            if names is None:        # OpenFIGI 가 못 찾은 게 나올 때만 SEC 목록을 받는다
                resp = sec_get(sec, TICKERS)
                names = unique_name_map(resp.json()) if resp.status_code == 200 else {}
            tk = names.get(norm_name(t.name or ""))
            conf = "exact" if tk else "none"
            stats[conf] += 1
            # figi '' = OpenFIGI 에 물어봤지만 없음 → 다음 회차에 다시 묻지 않는다
            rows.append({"cusip": t.cusip, "name": t.name, "ticker": tk, "confidence": conf, "figi": ""})
        with engine.begin() as c:
            c.execute(_UPSERT, rows)
    return stats


_SECTOR_TARGETS = text(
    "SELECT m.cusip, m.ticker FROM cusip_map m JOIN holdings_13f h ON h.cusip = m.cusip "
    "WHERE m.ticker IS NOT NULL AND m.sic IS NULL "
    "GROUP BY m.cusip, m.ticker ORDER BY sum(h.value) DESC NULLS LAST LIMIT :n"
)


def fill_sectors(engine, sec, max_cusips: int = DEFAULT_MAX) -> dict:
    """티커는 있는데 SIC 를 아직 안 찾아본 CUSIP → SEC submissions 의 SIC → 섹터 (계획 A5).

    회사(CIK)당 요청 1번. 티커가 SEC 목록에 없거나(ETF·외국 상장 등) SIC 가 없으면 sic='' 로 남겨
    다시 묻지 않는다.
    """
    with engine.begin() as c:
        targets = c.execute(_SECTOR_TARGETS, {"n": max_cusips}).all()
    if not targets:
        return {"sector_targets": 0}
    resp = sec_get(sec, TICKERS)
    by_ticker = {str(v["ticker"]).upper(): cik10(v["cik_str"]) for v in resp.json().values()} \
        if resp.status_code == 200 else {}
    sic_by_cik: dict[str, tuple[str, str | None]] = {}
    filled = 0
    for i in range(0, len(targets), 50):
        rows = []
        for t in targets[i:i + 50]:
            cik = by_ticker.get(t.ticker.upper()) or by_ticker.get(t.ticker.upper().replace("-", "."))
            if cik and cik not in sic_by_cik:
                r = sec_get(sec, SUBMISSIONS.format(cik=cik))
                sic = str((r.json().get("sic") or "") if r.status_code == 200 else "").strip()
                sic_by_cik[cik] = (sic, sic_to_sector(sic))
            sic, sector = sic_by_cik.get(cik, ("", None)) if cik else ("", None)
            filled += sector is not None
            rows.append({"c": t.cusip, "sic": sic, "sector": sector})
        with engine.begin() as c:
            c.execute(text("UPDATE cusip_map SET sic = :sic, sector = :sector, updated_at = now() "
                           "WHERE cusip = :c"), rows)
    return {"sector_targets": len(targets), "sector_filled": filled, "companies": len(sic_by_cik)}


def run(engine, job_id, payload, storage_dir, log_job):
    try:
        with _figi_client() as fc, sec_client(require_ua=True) as sec:
            n = int((payload or {}).get("max_cusips", DEFAULT_MAX))
            result = resolve(engine, fc, sec, n)
            result.update(fill_sectors(engine, sec, n))
    except httpx.HTTPError as exc:
        record_error(engine, "openfigi", classify_error(exc), str(exc))
        raise
    record_ok(engine, "openfigi", detail=result)
    log_job(engine, job_id, "INFO", "done", f"cusip: {result}")
    return result
