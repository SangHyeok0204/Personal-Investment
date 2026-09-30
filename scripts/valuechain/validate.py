"""storage/valuechain/*.ttl 검증 (계획 §5.1) — ttl 을 고친 뒤 돌린다.

    .venv/bin/python scripts/valuechain/validate.py [디렉터리]

검사: 파싱, 파일마다 vc:Sector 1개, 분류 코드 유일, 고아·순환 분류 없음, feedsInto 대상 존재,
모든 멤버십이 분류 ≥1 에 소속, primaryCategory ∈ belongsTo, 출처 대상 존재.
문제가 있으면 목록을 찍고 1 로 끝난다. 규칙 본체는 apps/api/app/core/valuechain.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.core import valuechain as vc  # noqa: E402


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    sectors, _ = vc.load_all(directory)
    for s in sectors:
        print(f"{s.file}: {s.code} {s.name} — 분류 {len(s.categories)} · 기업 {len(s.memberships)} · 흐름 {len(s.flows)}")
    problems = vc.validate(directory)
    for p in problems:
        print("✗ " + p)
    print("OK" if not problems else f"문제 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
