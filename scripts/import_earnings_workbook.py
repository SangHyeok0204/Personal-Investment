"""어닝모니터 엑셀 → 실적 표 1회 이관 (계획 B1).

    .venv/bin/python scripts/import_earnings_workbook.py [--xlsx 보유종목정리.xlsx] [--zip 어닝모니터-….zip] [--dry-run]

- 대상 = 내 미국 보유 + 관심종목(GOOG → GOOGL). 펀드 열·시트는 버린다.
- 원본 DB(`EARNINGS_MONITOR.db`)는 회사 공유 드라이브에만 있고 zip 에 없다 — 정본인 엑셀에서 옮긴다
  (원본에서 DB 는 엑셀의 미러였다).
- 다시 돌려도 안전: (ticker, quarter) · (ticker, quarter, rank) 로 덮어쓴다. 이미 파이프라인이 채운 값
  (source ≠ 'import')은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))

import openpyxl  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.earnings_import import result_rows, watchpoint_rows  # noqa: E402

DEFAULT_ZIP = Path.home() / "Downloads" / "어닝모니터-20260926T000926Z-1-001.zip"
MEMBER = "어닝모니터/input/processed/보유종목정리.xlsx"


def _database_url() -> str:
    for line in (REPO / ".env.local").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.partition("=")[2].strip().strip('"')
    raise SystemExit("DATABASE_URL 없음")


def _load_workbook(xlsx: str | None, zpath: Path):
    if xlsx:
        return openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    z = zipfile.ZipFile(zpath)
    for info in z.infolist():
        name = info.filename
        if not info.flag_bits & 0x800:          # 한글 파일명이 cp949 로 들어 있다
            try:
                name = name.encode("cp437").decode("cp949")
            except UnicodeError:
                pass
        if name == MEMBER:
            return openpyxl.load_workbook(io.BytesIO(z.read(info)), read_only=True, data_only=True)
    raise SystemExit(f"{zpath} 안에 {MEMBER} 가 없다")


def _targets(conn) -> set[str]:
    return set(conn.execute(text(
        "SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items")).scalars())


_UPSERT_EVENT = text(
    "INSERT INTO earnings_events (ticker, quarter, company, report_date, timing, eps_forecast, revenue_forecast, "
    "revenue_forecast_status, revenue_forecast_source, market_cap, source) VALUES (:ticker, :quarter, :company, "
    ":report_date, :timing, :eps_forecast, :revenue_forecast, :revenue_forecast_status, :revenue_forecast_source, "
    ":market_cap, 'import') ON CONFLICT (ticker, quarter) DO UPDATE SET "
    "company = COALESCE(earnings_events.company, EXCLUDED.company), "
    "report_date = COALESCE(earnings_events.report_date, EXCLUDED.report_date), "
    "timing = COALESCE(earnings_events.timing, EXCLUDED.timing), "
    "eps_forecast = COALESCE(earnings_events.eps_forecast, EXCLUDED.eps_forecast), "
    "revenue_forecast = COALESCE(earnings_events.revenue_forecast, EXCLUDED.revenue_forecast), "
    "revenue_forecast_status = COALESCE(earnings_events.revenue_forecast_status, EXCLUDED.revenue_forecast_status), "
    "revenue_forecast_source = COALESCE(earnings_events.revenue_forecast_source, EXCLUDED.revenue_forecast_source), "
    "market_cap = COALESCE(earnings_events.market_cap, EXCLUDED.market_cap) RETURNING id"
)
_UPSERT_RESULT = text(
    "INSERT INTO earnings_results (event_id, eps_actual, revenue_actual, eps_surprise_pct, revenue_surprise_pct, "
    "verdict, reaction_note, source, detail) VALUES (:event_id, :eps_actual, :revenue_actual, :eps_surprise_pct, "
    ":revenue_surprise_pct, :verdict, :reaction_note, 'import', CAST(:detail AS JSONB)) "
    "ON CONFLICT (event_id) DO UPDATE SET "
    "eps_actual = COALESCE(earnings_results.eps_actual, EXCLUDED.eps_actual), "
    "revenue_actual = COALESCE(earnings_results.revenue_actual, EXCLUDED.revenue_actual), "
    "eps_surprise_pct = COALESCE(earnings_results.eps_surprise_pct, EXCLUDED.eps_surprise_pct), "
    "revenue_surprise_pct = COALESCE(earnings_results.revenue_surprise_pct, EXCLUDED.revenue_surprise_pct), "
    "verdict = COALESCE(earnings_results.verdict, EXCLUDED.verdict), "
    "reaction_note = COALESCE(earnings_results.reaction_note, EXCLUDED.reaction_note)"
)
_UPSERT_POINT = text(
    "INSERT INTO earnings_watchpoints (ticker, quarter, rank, point, result, source) "
    "VALUES (:ticker, :quarter, :rank, :point, :result, 'import') ON CONFLICT (ticker, quarter, rank) DO UPDATE SET "
    "point = COALESCE(earnings_watchpoints.point, EXCLUDED.point), "
    "result = COALESCE(earnings_watchpoints.result, EXCLUDED.result), updated_at = now() "
    "WHERE earnings_watchpoints.source = 'import'"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx")
    ap.add_argument("--zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    wb = _load_workbook(a.xlsx, Path(os.path.expanduser(a.zip)))
    eng = create_engine(_database_url())
    stats = {"events": 0, "results": 0, "upcoming": 0, "watchpoints": 0}
    with eng.begin() as c:
        targets = _targets(c)
        items = []
        for sheet in ("실적", "과거"):
            rows = list(wb[sheet].iter_rows(values_only=True))
            items += result_rows(rows[0], rows[1:], targets)
        points = watchpoint_rows(list(wb["관전포인트"].iter_rows(values_only=True))[1:], targets)
        # `관전포인트` 시트가 먼저(분기별 이력) — 실적 시트의 관전포인트1~4 는 빈 칸만 메운다
        have = {(p["ticker"], p["quarter"], p["rank"]) for p in points}
        for it in items:
            for rank, point, result in it["points"]:
                key = (it["event"]["ticker"], it["event"]["quarter"], rank)
                if (point or result) and key not in have:
                    points.append({"ticker": key[0], "quarter": key[1], "rank": rank, "point": point, "result": result})
                    have.add(key)
        for it in items:
            eid = c.execute(_UPSERT_EVENT, it["event"]).scalar()
            stats["events"] += 1
            if it["result"]:
                c.execute(_UPSERT_RESULT, {**it["result"], "event_id": eid, "detail": json.dumps(it["result"]["detail"])})
                stats["results"] += 1
            up = it["upcoming"]
            if up and (not it["event"]["report_date"] or up > it["event"]["report_date"]):
                from app.core.earnings_import import quarter_of
                c.execute(_UPSERT_EVENT, {"ticker": it["event"]["ticker"], "quarter": quarter_of(up),
                                          "company": it["event"]["company"], "report_date": up, "timing": None,
                                          "eps_forecast": None, "revenue_forecast": None,
                                          "revenue_forecast_status": None, "revenue_forecast_source": None,
                                          "market_cap": None})
                stats["upcoming"] += 1
        for p in points:
            c.execute(_UPSERT_POINT, p)
        stats["watchpoints"] = len(points)
        stats["targets"] = sorted(targets)
        stats["tickers_imported"] = sorted({it["event"]["ticker"] for it in items} | {p["ticker"] for p in points})
        if a.dry_run:
            c.rollback()
            stats["dry_run"] = True
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
