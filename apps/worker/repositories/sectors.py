"""종목 기본 섹터 분류 적용.

동기화가 종목 마스터(assets)를 만들 때 섹터는 비어 있다. 증권사가 주지 않기
때문이다. 그대로 두면 **새로 산 종목이 영영 미분류로 남고**, 사용자가 매번 손으로
스크립트를 돌려야 한다(실제로 동기화할 때마다 섹터가 비어 그렇게 됐다).

동기화 끝에 이걸 한 번 부르면 기본 분류가 붙는다.

⚠️`sector IS NULL` 인 행만 채운다 — 화면에서 지정한 MANUAL 값은 절대 덮지 않는다.
⚠️목록의 정본은 `database/seeds/sectors.py` 다. 여기 복제하지 않고 읽어 온다.
"""
import importlib.util
import sys
from pathlib import Path

from sqlalchemy import text

_SEED_PATH = Path(__file__).resolve().parents[3] / "database" / "seeds" / "sectors.py"

_UPDATE = text(
    "UPDATE assets SET sector = :sector, industry = :industry, "
    "sector_source = 'SEED', classified_at = now(), updated_at = now() "
    "WHERE ticker = :ticker AND sector IS NULL"
)


def _load_seed() -> dict:
    if not _SEED_PATH.exists():
        return {}
    spec = importlib.util.spec_from_file_location("_sector_seed", _SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_sector_seed"] = module
    spec.loader.exec_module(module)
    return module.SECTOR_SEED


def apply_sector_seed(conn) -> int:
    """미분류 종목에 기본 섹터를 채운다. 채운 종목 수를 돌려준다."""
    updated = 0
    for ticker, (sector, industry) in _load_seed().items():
        result = conn.execute(
            _UPDATE, {"sector": sector, "industry": industry, "ticker": ticker}
        )
        updated += result.rowcount
    return updated


def unclassified_held_count(conn) -> int:
    """보유 중인데 아직 분류가 없는 종목 수 — 로그로 알려 주기 위한 것."""
    return conn.execute(
        text(
            "SELECT count(DISTINCT a.ticker) FROM assets a "
            "JOIN current_positions p ON p.asset_id = a.id WHERE a.sector IS NULL"
        )
    ).scalar() or 0
