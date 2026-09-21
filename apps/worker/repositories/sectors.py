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
_TECH_PATH = (
    Path(__file__).resolve().parents[3] / "database" / "seeds" / "ai_tech_classification.json"
)

# ETF 는 개별 종목 분류표에 없다. 그대로 두면 보유 17종목 중 7개가 미분류가 되어
# 비중의 절반이 '모름'으로 보인다. 상품 성격으로 따로 세운다 —
# 투과(look-through) 배분은 사용자가 원하지 않는다고 밝혔다.
ETF_TECH = {
    "SOXL": ("ETF", "레버리지", "반도체 3배"),
    "SCHD": ("ETF", "배당주", "미국 배당"),
    "TSL": ("ETF", "레버리지", "개별종목 레버리지"),
    "GLD": ("ETF", "원자재", "금"),
    "XLB": ("ETF", "섹터", "원자재 섹터"),
    "SGOV": ("ETF", "채권", "초단기 국채"),
    "QLD": ("ETF", "레버리지", "지수 2배"),
    "EETH": ("ETF", "가상자산", "이더리움"),
    "BITO": ("ETF", "가상자산", "비트코인 선물"),
}

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


_TECH_UPDATE = text(
    "UPDATE assets SET tech_l1 = :l1, tech_l2 = :l2, tech_l3 = :l3, "
    "tech_source = :src, updated_at = now() "
    "WHERE ticker = :ticker AND tech_l1 IS NULL"
)


def _load_tech() -> dict:
    """AI/Tech 분류표(4,646종목). 크기가 있어 한 번만 읽는다."""
    if not _TECH_PATH.exists():
        return {}
    import json

    return json.loads(_TECH_PATH.read_text())


_TECH_CACHE: dict | None = None


def apply_tech_classification(conn) -> dict:
    """미분류 종목에 AI/Tech 3단계 분류를 붙인다.

    ⚠️`tech_l1 IS NULL` 인 행만 채운다 — 화면에서 지정한 MANUAL 값은 덮지 않는다.
    ⚠️ETF 가 먼저다. 분류표에 우연히 같은 티커가 있어도 ETF 성격이 우선이다.
    """
    global _TECH_CACHE
    if _TECH_CACHE is None:
        _TECH_CACHE = _load_tech()

    # 조회 대상은 **DB 에 있는 종목만**. 4,646개를 전부 UPDATE 하면 쓸데없이 느리다.
    tickers = [r[0] for r in conn.execute(text("SELECT ticker FROM assets")).all()]
    applied = {"etf": 0, "seed": 0, "missing": []}
    for ticker in tickers:
        etf = ETF_TECH.get(ticker)
        if etf:
            result = conn.execute(
                _TECH_UPDATE,
                {"l1": etf[0], "l2": etf[1], "l3": etf[2], "src": "ETF", "ticker": ticker},
            )
            applied["etf"] += result.rowcount
            continue
        found = _TECH_CACHE.get(ticker)
        if found:
            result = conn.execute(
                _TECH_UPDATE,
                {
                    "l1": found[0], "l2": found[1] or None, "l3": found[2] or None,
                    "src": "SEED", "ticker": ticker,
                },
            )
            applied["seed"] += result.rowcount
        else:
            applied["missing"].append(ticker)
    return applied


def unclassified_tech_held(conn) -> list[str]:
    """보유 중인데 AI/Tech 분류가 없는 종목 — 로그로 알려 주기 위한 것."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT a.ticker FROM assets a "
            "JOIN current_positions p ON p.asset_id = a.id "
            "WHERE a.tech_l1 IS NULL ORDER BY 1"
        )
    ).all()
    return [r[0] for r in rows]
