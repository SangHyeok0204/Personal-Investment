"""Epoch/npm 파싱 규칙 고정."""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.ai_data import Accelerator, PackageDownloads, _day, _dec  # noqa: E402


@pytest.mark.parametrize("raw", ["", "  ", "N/A", "-", None])
def test_blank_is_none_not_zero(raw) -> None:
    """⚠️미공개와 0 은 다르다. 0 으로 채우면 "무료"·"성능 0"이 된다."""
    assert _dec(raw) is None


def test_numbers_with_commas_parse() -> None:
    assert _dec("12,000.0") == Decimal("12000.0")


def test_day_accepts_partial_dates() -> None:
    """Epoch 는 'YYYY-MM' 이나 'YYYY' 만 있는 행도 있다."""
    assert _day("2025-11-06") == date(2025, 11, 6)
    assert _day("2025-11") == date(2025, 11, 1)
    assert _day("2025") == date(2025, 1, 1)
    assert _day("언젠가") is None


def accelerator(fp16: str | None, tdp: str | None) -> Accelerator:
    return Accelerator(
        name="X", manufacturer="Y", kind="", release_date=None, price_usd=None,
        fp16_flops=None if fp16 is None else Decimal(fp16),
        fp8_flops=None, memory_bytes=None, bandwidth_bytes=None,
        tdp_watts=None if tdp is None else Decimal(tdp),
    )


def test_flops_per_watt() -> None:
    assert accelerator("1000", "500").flops_per_watt == Decimal("2")


@pytest.mark.parametrize("fp16,tdp", [(None, "500"), ("1000", None), ("1000", "0")])
def test_flops_per_watt_needs_both_and_nonzero_tdp(fp16, tdp) -> None:
    """TDP 0 으로 나누면 터진다 — 미공개도 0 도 계산하지 않는다."""
    assert accelerator(fp16, tdp).flops_per_watt is None


def downloads(counts: list[int]) -> PackageDownloads:
    return PackageDownloads(
        package="p", label="L",
        days=[date(2026, 1, 1)] * len(counts), counts=counts,
    )


def test_week_over_week_compares_last_two_weeks() -> None:
    d = downloads([10] * 7 + [20] * 7)  # 직전주 70 → 최근주 140
    assert d.last_week == 140
    assert d.prior_week == 70
    assert d.week_over_week == Decimal("1")


def test_week_over_week_none_when_prior_week_is_zero() -> None:
    """0 으로 나눌 수 없다. '무한 증가'로 적으면 안 된다."""
    assert downloads([0] * 7 + [5] * 7).week_over_week is None
