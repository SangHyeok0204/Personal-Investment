"""52주 위치 계산 규칙 고정."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.base import Quote  # noqa: E402


def q(price: str, low: str | None = None, high: str | None = None) -> Quote:
    return Quote(
        symbol="AAA",
        price=Decimal(price),
        fifty_two_week_low=None if low is None else Decimal(low),
        fifty_two_week_high=None if high is None else Decimal(high),
    )


def test_position_between_low_and_high() -> None:
    assert q("150", "100", "200").fifty_two_week_position == Decimal("0.5")
    assert q("100", "100", "200").fifty_two_week_position == Decimal("0")
    assert q("200", "100", "200").fifty_two_week_position == Decimal("1")


def test_missing_range_gives_none() -> None:
    """토스 일봉에는 52주 범위가 없다. 없으면 None — 0.5 를 지어내지 않는다."""
    assert q("150").fifty_two_week_position is None
    assert q("150", "100", None).fifty_two_week_position is None
    assert q("150", None, "200").fifty_two_week_position is None


def test_degenerate_range_gives_none() -> None:
    """고저가 같으면(상장 직후 등) 나눌 수 없다."""
    assert q("100", "100", "100").fifty_two_week_position is None
    # 데이터가 뒤집혀 오는 경우도 계산하지 않는다.
    assert q("100", "200", "100").fifty_two_week_position is None


def test_price_outside_the_range_is_not_clamped() -> None:
    """범위 밖이면 그대로 내보낸다 — 화면이 판단한다(신고가는 신고가로 보여야).

    캐시된 52주 범위가 잠깐 낡으면 1을 넘을 수 있다. 서버가 1로 깎아 두면
    '신고가 경신'이 '정확히 고점'으로 뭉개진다.
    """
    assert q("220", "100", "200").fifty_two_week_position == Decimal("1.2")
