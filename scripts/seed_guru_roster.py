"""계획 A1 — `guru_roster` 를 `database/seeds/guru_roster.py` 로 채운다(업서트, 다시 돌려도 같음).

    .venv/bin/python scripts/seed_guru_roster.py

- kind='guru'  → active=true,  backfill_status='pending'(A2 가 채우면 'done')
- kind='index' → active=false, backfill_status='skip'   (사용자 결정 1 — 필요하면 화면에서 켠다)
⚠️이미 있는 행의 active·backfill_status 는 **덮지 않는다** — 사용자가 화면에서 바꾼 값이 이긴다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "database" / "seeds"))

from sqlalchemy import create_engine, text  # noqa: E402

from guru_roster import ROSTER  # noqa: E402


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def main() -> int:
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        for cik, guru, firm, filer, kind in ROSTER:
            conn.execute(
                text(
                    "INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind, active, backfill_status) "
                    "VALUES (:cik, :g, :f, :fn, :k, :a, :b) ON CONFLICT (cik) DO UPDATE SET "
                    "guru_name = EXCLUDED.guru_name, firm = EXCLUDED.firm, "
                    "filer_name = EXCLUDED.filer_name, kind = EXCLUDED.kind"
                ),
                {"cik": cik, "g": guru, "f": firm, "fn": filer, "k": kind,
                 "a": kind == "guru", "b": "pending" if kind == "guru" else "skip"},
            )
        counts = conn.execute(
            text("SELECT kind, active, count(*) FROM guru_roster GROUP BY 1, 2 ORDER BY 1, 2")
        ).all()
    print("guru_roster:", [tuple(r) for r in counts])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
