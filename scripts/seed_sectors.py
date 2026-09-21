#!/usr/bin/env python3
"""종목 → 섹터 분류를 DB 에 적용한다 (alembic 0006 의 SECTOR_SEED 와 같은 목록).

왜 스크립트로도 두는가: 섹터는 **증권사가 주지 않는 우리 분류**다. 동기화는 종목
마스터(assets)를 만들기만 하고 섹터는 건드리지 않으므로, 새 종목을 사면 미분류로
남는다. 마이그레이션은 한 번만 도는 반면 이 스크립트는 언제든 다시 돌릴 수 있다.

안전장치 두 가지:
  · `sector IS NULL` 인 행만 채운다 — 화면에서 직접 지정한 값(sector_source='MANUAL')을
    덮지 않는다.
  · 여러 번 돌려도 결과가 같다(두 번째부터는 0건).

사용:
    DATABASE_URL=postgresql+psycopg://... python scripts/seed_sectors.py
"""
import importlib.util
import os
import pathlib
import sys

from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "database/migrations/versions/0006_asset_sector.py"


def load_seed() -> dict:
    """분류 목록의 정본은 마이그레이션이다 — 여기 복제하지 않고 읽어 온다."""
    spec = importlib.util.spec_from_file_location("m0006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    sys.modules["m0006"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # alembic 심볼(op)이 없어 import 가 실패해도 모듈 전역은 이미 채워져 있다.
        pass
    return module.SECTOR_SEED


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 이 필요합니다", file=sys.stderr)
        return 2

    seed = load_seed()
    engine = create_engine(url, future=True)
    updated = 0
    with engine.begin() as conn:
        for ticker, (sector, industry) in seed.items():
            result = conn.execute(
                text(
                    "UPDATE assets SET sector = :sector, industry = :industry, "
                    "sector_source = 'SEED', classified_at = now(), updated_at = now() "
                    "WHERE ticker = :ticker AND sector IS NULL"
                ),
                {"sector": sector, "industry": industry, "ticker": ticker},
            )
            updated += result.rowcount

        remaining = conn.execute(
            text(
                "SELECT count(*) FROM assets a JOIN current_positions p ON p.asset_id = a.id "
                "WHERE a.sector IS NULL"
            )
        ).scalar()

    print(f"섹터 적용: {updated}종목")
    if remaining:
        print(f"⚠️보유 중인데 아직 미분류인 종목: {remaining}개 "
              f"— 화면(/portfolio/allocation)에서 직접 지정하거나 0006 시드에 추가하세요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
