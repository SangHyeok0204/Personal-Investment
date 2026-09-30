"""계절성 C2 — 이식한 계산이 원본 산출물을 **한 글자도 다르지 않게** 재현하는지 대조한다.

    .venv/bin/python scripts/verify_seasonality_port.py [--dir ~/Downloads/계절성]

DB 의 `monthly_closes`(source='bloomberg', C1 에서 적재)로 `app.core.seasonality` 를 돌려
원본과 같은 방식으로 CSV 를 만들고, 원본 파일 4개와 줄 단위로 비교한다:
  seasonality_stats.csv · signals_history.csv (지수 8) / sector_stats.csv · sector_signals.csv (섹터 11)
하나라도 다르면 첫 차이를 보여 주고 종료 코드 1.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))

import pandas as pd  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core import seasonality as sea  # noqa: E402

OUT = {
    "index": ("seasonality_stats.csv", "signals_history.csv"),
    "sector": ("sector_stats.csv", "sector_signals.csv"),
}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def _closes(conn, grp: str) -> dict[str, dict[str, float]]:
    rows = conn.execute(
        text(
            "SELECT s.key, c.month, c.close FROM seasonality_series s "
            "JOIN monthly_closes c ON c.series = s.key "
            "WHERE s.grp = :g AND c.source = 'bloomberg' ORDER BY s.sort, c.month"
        ),
        {"g": grp},
    ).all()
    out: dict[str, dict[str, float]] = {}
    for key, month, close in rows:
        out.setdefault(key, {})[month] = float(close)
    return out


def _csv(df: pd.DataFrame) -> list[str]:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().splitlines()


def _compare(name: str, ours: list[str], path: Path) -> bool:
    theirs = path.read_text(encoding="utf-8-sig").splitlines()
    if ours == theirs:
        print(f"✓ {name}: {len(theirs) - 1}행 일치")
        return True
    for i, (a, b) in enumerate(zip(ours, theirs)):
        if a != b:
            print(f"✗ {name}: {i}행째 다름\n   이식: {a}\n   원본: {b}")
            break
    else:
        print(f"✗ {name}: 행 수 다름 — 이식 {len(ours)} / 원본 {len(theirs)}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Downloads" / "계절성"))
    src = Path(ap.parse_args().dir).expanduser()

    engine = create_engine(_database_url())
    ok = True
    with engine.connect() as conn:
        for grp, (stats_fn, sig_fn) in OUT.items():
            rets = sea.monthly_returns(_closes(conn, grp))
            proofs, sigs = [], []
            for _, w in sea.WINDOWS:
                proof = sea.proof_table(rets, w)
                proofs.append(proof)
                sigs += [
                    sea.walk_forward(rets, w),
                    # 원본은 '검증셀' 을 빼고 이어 붙였다. '근거' 는 이식에서 더한 열.
                    sea.next_month_signals(rets, proof, w).drop(columns=["검증셀", "근거"]),
                ]
            ok &= _compare(stats_fn, _csv(pd.concat(proofs)), src / stats_fn)
            ok &= _compare(sig_fn, _csv(pd.concat(sigs)), src / sig_fn)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
