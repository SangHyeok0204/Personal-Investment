"""매매일지 입력 검증 — DB 를 타지 않는 부분만."""

from __future__ import annotations

import pytest

from app.api.journal import VALID_KINDS, _normalize, _validate
from app.core.errors import AppError


def test_ticker_is_upper_cased_and_trimmed() -> None:
    assert _normalize(" soxl ") == "SOXL"


def test_blank_ticker_becomes_none() -> None:
    """종목 무관 메모를 허용한다 — 빈 문자열이 아니라 None 이어야 한다.

    빈 문자열로 저장되면 "ticker 가 ''인 종목"이라는 존재하지 않는 것이 생긴다.
    """
    assert _normalize("   ") is None
    assert _normalize(None) is None


def test_known_kinds_pass() -> None:
    for kind in VALID_KINDS:
        _validate(kind, "제목", None)


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(AppError) as err:
        _validate("NOPE", "제목", None)
    assert err.value.status_code == 400


def test_blank_title_is_rejected() -> None:
    """제목 없는 일지는 목록에서 아무것도 알려주지 않는다."""
    with pytest.raises(AppError):
        _validate("ENTRY", "   ", None)


@pytest.mark.parametrize("value", [0, 6, -1, 99])
def test_conviction_out_of_range_is_rejected(value: int) -> None:
    with pytest.raises(AppError):
        _validate("ENTRY", "제목", value)


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_conviction_in_range_passes(value: int) -> None:
    _validate("ENTRY", "제목", value)


def test_conviction_may_be_omitted() -> None:
    """강제하면 아무 숫자나 찍는다 — 비워 두는 것이 정상이어야 한다."""
    _validate("ENTRY", "제목", None)
