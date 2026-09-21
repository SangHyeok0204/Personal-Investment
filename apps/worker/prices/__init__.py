"""시세 소스 — 보유 종목의 현재가를 받아오는 갈래.

증권사 어댑터(brokers/)가 "무엇을 얼마나 들고 있나"를 답한다면, 여기는
"그게 지금 얼마인가"를 답한다. 두 관심사를 분리해 두면 시세 소스를 갈아끼워도
계좌 연동을 건드리지 않는다.
"""
from .base import CompositePriceSource, PriceSource, Quote  # noqa: F401
from .yahoo import YahooPriceSource  # noqa: F401
from . import fred  # noqa: F401
