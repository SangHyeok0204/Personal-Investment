"""ETF 대표 노출 매핑 규칙 고정.

이 파일이 지키는 것은 **설계 결정**이다. 나중에 누가 "SCHD 도 섹터 넣어 두자" 고
손대면 여기서 막힌다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.core.etf_exposure import ETF_EXPOSURE

_SEED = Path(__file__).resolve().parents[3] / "database" / "seeds" / "etf_exposure.py"
_spec = importlib.util.spec_from_file_location("_etf_exposure_seed_test", _SEED)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_etf_exposure_seed_test"] = _mod
_spec.loader.exec_module(_mod)
exposure_of = _mod.exposure_of
reason_of = _mod.reason_of


def test_seed_is_loaded_not_duplicated() -> None:
    """API 는 database/seeds 를 읽어 온다 — 표를 복제해 두지 않는다."""
    assert len(ETF_EXPOSURE) > 0
    assert ETF_EXPOSURE["SOXL"][0] == "컴퓨팅 인프라"


def test_leveraged_etf_follows_its_underlying() -> None:
    """SOXL 은 반도체 3배다. 배수와 무관하게 노출은 반도체(=컴퓨팅 인프라)다."""
    assert exposure_of("SOXL") == "컴퓨팅 인프라"
    # TSL 은 TSLA 2배 — 엑셀의 TSLA 분류(하드웨어 활용)를 그대로 따른다.
    assert exposure_of("TSL") == "하드웨어 활용"


def test_broad_etf_is_not_forced_into_a_sector() -> None:
    """광범위 ETF 에 섹터 이름을 붙이지 않는다.

    SCHD 는 100종목에 걸쳐 있다. 어느 한 섹터로 적으면 그 숫자가 거짓이 된다.
    투과 배분 없이는 쪼갤 수 없다는 사실이 화면에 남아야 한다.
    """
    for ticker in ("SCHD", "QLD", "SPY", "QQQ"):
        assert exposure_of(ticker) == "분산 (다중 섹터)", ticker


def test_unknown_ticker_is_not_guessed() -> None:
    """표에 없는 ETF 는 None. 비슷해 보인다고 아무 섹터에나 넣지 않는다."""
    assert exposure_of("ZZZZ") is None
    assert reason_of("ZZZZ") is None


def test_every_entry_has_a_reason() -> None:
    """근거 없는 매핑을 남기지 않는다 — 나중에 왜 그렇게 넣었는지 못 찾는다."""
    for ticker, (label, reason) in ETF_EXPOSURE.items():
        assert label and label.strip(), ticker
        assert reason and reason.strip(), ticker


def test_lookup_is_case_insensitive() -> None:
    assert exposure_of("soxl") == exposure_of("SOXL")
