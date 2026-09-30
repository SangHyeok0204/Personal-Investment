"""거장 최근 분기 금액 기준 CUSIP→티커 매핑률 (계획 A4 완료 기준 ≥ 95%).

    .venv/bin/python scripts/cusip_coverage.py [--top 15]

- 거장마다 가장 최근 보고 분기 하나, 정정 규칙(`effective_accessions` — RESTATEMENT 대체 / NEW HOLDINGS 합산).
- 비중과 같은 기준: 주식(SH)만, 옵션(put/call)·채권(PRN) 제외.
- ⚠️금액 단위가 섞여 있다(천 달러/달러) — 공시별로 value/shares 중앙값 < 1 이면 ×1000(원본 규칙).
  보정 없이 합치면 천 달러 단위 거장의 비중이 1/1000 로 눌린다.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))

from app.core.guru13f import Filing13F, effective_accessions  # noqa: E402


def _database_url() -> str:
    for line in (REPO / ".env.local").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.partition("=")[2].strip().strip('"')
    raise SystemExit("DATABASE_URL 없음")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15, help="매핑 안 된 금액 상위 몇 개를 보일지")
    args = ap.parse_args()
    eng = create_engine(_database_url())
    with eng.begin() as c:
        gurus = c.execute(text("SELECT cik, COALESCE(guru_name, firm) FROM guru_roster "
                               "WHERE kind = 'guru' AND active ORDER BY 2")).all()
        total = mapped = 0.0
        missing: dict[tuple, float] = defaultdict(float)
        worst = []
        for cik, name in gurus:
            period = c.execute(text("SELECT max(period_of_report) FROM sec_filings WHERE watch_cik = :w "
                                    "AND form_type LIKE '13F%'"), {"w": cik}).scalar()
            filings = c.execute(text("SELECT accession_number, filing_date, form_type, amendment_type "
                                     "FROM sec_filings WHERE watch_cik = :w AND form_type LIKE '13F%' "
                                     "AND period_of_report = :p"), {"w": cik, "p": period}).all()
            accs, _ = effective_accessions([Filing13F(*f) for f in filings])
            g_total = g_mapped = 0.0
            for acc in accs:
                rows = c.execute(text(
                    "SELECT h.cusip, h.name_of_issuer, h.value, h.shares, m.ticker FROM holdings_13f h "
                    "LEFT JOIN cusip_map m ON m.cusip = h.cusip WHERE h.accession_number = :a "
                    "AND COALESCE(h.shr_type, 'SH') = 'SH' AND h.put_call IS NULL"), {"a": acc}).all()
                ratios = [float(r.value) / float(r.shares) for r in rows if r.value and r.shares]
                scale = 1000.0 if ratios and statistics.median(ratios) < 1 else 1.0
                for r in rows:
                    v = float(r.value or 0) * scale
                    g_total += v
                    if r.ticker:
                        g_mapped += v
                    else:
                        missing[(r.cusip, r.name_of_issuer)] += v
            total += g_total
            mapped += g_mapped
            worst.append((g_mapped / g_total * 100 if g_total else 100.0, name, str(period)))
    print(f"거장 {len(gurus)}명 최근 분기 금액 기준 매핑률: {mapped / total * 100:.2f}%  "
          f"(미매핑 ${(total - mapped) / 1e9:,.1f}B / ${total / 1e9:,.1f}B)")
    print("거장별 하위 5:", ", ".join(f"{n} {p} {pct:.1f}%" for pct, n, p in sorted(worst)[:5]))
    print(f"미매핑 금액 상위 {args.top}:")
    for (cusip, nm), v in sorted(missing.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  {cusip}  {nm:<40}  ${v / 1e6:,.0f}M  ({v / total * 100:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
