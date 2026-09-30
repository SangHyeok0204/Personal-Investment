"""AI Key Data — 드라이브 데몬이 쌓은 VS Code·PyPI 스냅샷 CSV 를 `ai_metric_snapshot` 에 한 번 적재한다.

    DATABASE_URL=... .venv/bin/python scripts/import_ai_snapshots.py \
        [--vscode path/to/vscode_installs_long.csv] [--pypi path/to/pypi_downloads_long.csv] [--dry-run]

★VS Code 는 과거를 다시 받을 수 없다(누적치만 준다) — 이 적재가 유일한 과거 이력이다.
  npm·OpenRouter 는 라이브로 다시 받으므로 임포트하지 않는다(계획 §12-3).

헤더(드라이브 원본):
  vscode: snapshot_date,snapshot_utc,extension,install,update_count,download_count,version,last_updated,avg_rating,rating_count
  pypi:   snapshot_date,package,last_day,last_week,last_month

- 업서트 — 다시 돌려도 같은 결과. 같은 날 여러 행이면 **마지막 행**(데몬의 재실행 덮어쓰기와 같다).
- 음수 델타·이상치도 원값 그대로 적는다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))

VSCODE_HEADER = ("snapshot_date", "snapshot_utc", "extension", "install", "update_count",
                 "download_count", "version", "last_updated", "avg_rating", "rating_count")
PYPI_HEADER = ("snapshot_date", "package", "last_day", "last_week", "last_month")


def _num(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        f = float(text)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def read_rows(path: Path, source: str) -> list[tuple[str, date, float, dict]]:
    """CSV → (series, date, value, extra). 헤더가 다르면 SystemExit — 엉뚱한 파일을 적지 않는다."""
    need = VSCODE_HEADER if source == "vscode" else PYPI_HEADER
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in need if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{path}: {source} 헤더 아님 — 없는 열 {missing}")
        latest: dict[tuple[str, date], tuple[str, date, float, dict]] = {}
        for row in reader:
            try:
                day = date.fromisoformat(row["snapshot_date"].strip()[:10])
            except ValueError:
                continue
            if source == "vscode":
                series, value = row["extension"].strip(), _num(row["install"])
                extra = {
                    "update_count": _num(row["update_count"]),
                    "download_count": _num(row["download_count"]),
                    "version": row["version"] or None,
                    "last_updated": row["last_updated"] or None,
                    "avg_rating": _num(row["avg_rating"]),
                    "rating_count": _num(row["rating_count"]),
                    "snapshot_utc": row["snapshot_utc"] or None,
                }
            else:
                series, value = row["package"].strip(), _num(row["last_day"])
                extra = {"last_week": _num(row["last_week"]), "last_month": _num(row["last_month"])}
            if not series or value is None:
                continue
            latest[(series, day)] = (series, day, value, extra)
    return list(latest.values())


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vscode", type=Path, help="vscode_installs_long.csv")
    ap.add_argument("--pypi", type=Path, help="pypi_downloads_long.csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.vscode and not args.pypi:
        ap.error("--vscode 나 --pypi 중 하나는 필요합니다")

    jobs = [(s, p) for s, p in (("vscode", args.vscode), ("pypi", args.pypi)) if p]
    parsed = {s: read_rows(p, s) for s, p in jobs}
    for source, rows in parsed.items():
        days = sorted({d for _, d, _, _ in rows})
        span = f"{days[0]}~{days[-1]}" if days else "-"
        print(f"{source}: {len(rows)}행, 계열 {len({s for s, *_ in rows})}개, {span}")
    if args.dry_run:
        return 0

    os.environ.setdefault("DATABASE_URL", _database_url())
    from app.core.ai_snapshot_sync import upsert  # noqa: E402 — DATABASE_URL 을 먼저 정한다
    from app.db.session import SessionLocal  # noqa: E402

    with SessionLocal() as db:
        for source, rows in parsed.items():
            for i in range(0, len(rows), 1000):
                upsert(db, source, rows[i:i + 1000])
            print(f"{source}: 업서트 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
