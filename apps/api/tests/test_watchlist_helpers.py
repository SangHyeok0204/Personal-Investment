"""관심종목 보조 규칙 — DB 를 타지 않는 부분만."""

from __future__ import annotations

from app.api.watchlist import _normalize


def test_ticker_is_upper_cased() -> None:
    """⚠️안 하면 "nvda" 와 "NVDA" 가 다른 행이 되어 unique 제약을 우회한다."""
    assert _normalize("nvda") == "NVDA"
    assert _normalize("Nvda") == "NVDA"


def test_surrounding_space_is_stripped() -> None:
    assert _normalize("  soxl \n") == "SOXL"


def test_empty_stays_empty_for_the_caller_to_reject() -> None:
    """빈 값을 여기서 막지 않는다 — 라우터가 400 으로 답한다."""
    assert _normalize("   ") == ""


def test_naver_name_needs_exact_code_match() -> None:
    from app.core.naming import parse_naver_ac

    body = {
        "items": [
            {"code": "BRK B", "name": "Berkshire Hathaway Inc Class B"},
            {"code": "BE", "name": "블룸 에너지"},
        ]
    }
    assert parse_naver_ac(body, "be") == "블룸 에너지"
    assert parse_naver_ac(body, "BRK") is None
    assert parse_naver_ac({"items": []}, "XYZ") is None
