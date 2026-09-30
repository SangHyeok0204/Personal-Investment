"""계절성 C1 — 블룸버그 BDH 엑셀 두 개를 `monthly_closes` 에 한 번 적재한다.

    DATABASE_URL=... .venv/bin/python scripts/seed_seasonality_bloomberg.py \
        [--dir ~/Downloads/계절성] [--dry-run]

- `seasonality_series` 를 `database/seeds/seasonality_series.py` 로 채운다(업서트).
- 엑셀 값은 source='bloomberg' 로 넣는다(업서트 — 다시 돌려도 같은 결과).
- 끝에 **원본 통계의 n 합계와 대조**한다: 시계열마다 '연속한 두 달 쌍의 수' 가
  원본 `seasonality_stats.csv`·`sector_stats.csv` 의 전구간 n 합과 같아야 한다.
  하나라도 다르면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO / "database" / "seeds"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.seasonality_io import consecutive_pairs, parse_bdh_xlsx  # noqa: E402
from seasonality_series import SERIES  # noqa: E402

FILES = {"index": "지수_월말종가_BDH.xlsx", "sector": "섹터_월말종가_BDH.xlsx"}
STATS = {"index": "seasonality_stats.csv", "sector": "sector_stats.csv"}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def _expected_n(src: Path, grp: str) -> Counter:
    """원본 통계의 전구간 n 합 = 그 시계열의 월 수익률 수."""
    rows = list(csv.DictReader(open(src / STATS[grp], encoding="utf-8-sig")))
    key = "지수"
    total: Counter = Counter()
    for r in rows:
        if r["구간"] == "전구간":
            total[r[key]] += int(r["n"])
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Downloads" / "계절성"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    src = Path(args.dir).expanduser()

    by_ticker = {bbg: key for key, _, _, bbg, _, _ in SERIES}
    parsed: dict[str, dict[str, float]] = {}
    for grp, fn in FILES.items():
        tickers = {bbg for _, _, g, bbg, _, _ in SERIES if g == grp}
        got = parse_bdh_xlsx(src / fn, tickers)
        missing = tickers - set(got)
        if missing:
            raise SystemExit(f"{fn}: 블록 없음 {sorted(missing)}")
        for bbg, months in got.items():
            parsed[by_ticker[bbg]] = months

    ok = True
    print(f"{'series':8} {'months':>6} {'first':>8} {'last':>8} {'pairs':>6} {'원본 n':>7}")
    for grp in FILES:
        expected = _expected_n(src, grp)
        for key, _, g, *_ in SERIES:
            if g != grp:
                continue
            months = parsed[key]
            pairs = consecutive_pairs(list(months))
            exp = expected.get(key)
            mark = "✓" if pairs == exp else "✗"
            ok &= pairs == exp
            print(f"{key:8} {len(months):6} {min(months):>8} {max(months):>8} {pairs:6} {exp!s:>7} {mark}")

    if not ok:
        print("원본 n 과 어긋남 — 적재하지 않는다.")
        return 1
    if args.dry_run:
        print("dry-run: DB 는 건드리지 않았다.")
        return 0

    engine = create_engine(_database_url())
    with engine.begin() as conn:
        for i, (key, label, grp, bbg, yahoo, cont) in enumerate(SERIES):
            conn.execute(
                text(
                    "INSERT INTO seasonality_series (key, label, grp, bbg_ticker, yahoo_symbol, "
                    "continuation, sort) VALUES (:k,:l,:g,:b,:y,:c,:s) ON CONFLICT (key) DO UPDATE SET "
                    "label=EXCLUDED.label, grp=EXCLUDED.grp, bbg_ticker=EXCLUDED.bbg_ticker, "
                    "yahoo_symbol=EXCLUDED.yahoo_symbol, continuation=EXCLUDED.continuation, sort=EXCLUDED.sort"
                ),
                {"k": key, "l": label, "g": grp, "b": bbg, "y": yahoo, "c": cont, "s": i},
            )
        n = 0
        for key, months in parsed.items():
            for month, close in months.items():
                conn.execute(
                    text(
                        "INSERT INTO monthly_closes (series, month, close, source) "
                        "VALUES (:s,:m,:c,'bloomberg') ON CONFLICT (series, month, source) DO UPDATE SET "
                        "close=EXCLUDED.close, loaded_at=now()"
                    ),
                    {"s": key, "m": month, "c": close},
                )
                n += 1
    print(f"적재 완료: 시계열 {len(SERIES)} · 월말 종가 {n}행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
