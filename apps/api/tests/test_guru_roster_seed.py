"""계획 A1 — 거장 명단 시드가 원본과 맞는지(23 + 12)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "database" / "seeds"))

from guru_roster import ROSTER  # noqa: E402


def test_roster_counts_and_shape():
    gurus = [r for r in ROSTER if r[4] == "guru"]
    index = [r for r in ROSTER if r[4] == "index"]
    assert len(gurus) == 23 and len(index) == 12
    ciks = [r[0] for r in ROSTER]
    assert len(set(ciks)) == len(ciks)                          # 중복 없음
    assert all(len(c) == 10 and c.isdigit() for c in ciks)      # SEC 10자리 CIK
    assert all(r[1] for r in gurus) and not any(r[1] for r in index)
    names = {r[1] for r in gurus}
    assert {"Warren Buffett", "Michael Burry", "Li Lu", "Bill Ackman"} <= names
