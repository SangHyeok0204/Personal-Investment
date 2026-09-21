"""증권사 코드 → 어댑터 클래스.

동기화 핸들러가 `from brokers.kiwoom import ...` 처럼 특정 증권사를 직접 import
하지 않게 하는 지점. 증권사를 늘릴 때 고치는 곳이 여기 하나가 된다.
"""
from __future__ import annotations

from .base import BrokerAdapter

_ADAPTERS: dict[str, type[BrokerAdapter]] = {}


def register(broker_code: str):
    """어댑터 클래스를 등록하는 데코레이터."""

    def _wrap(cls: type[BrokerAdapter]) -> type[BrokerAdapter]:
        _ADAPTERS[broker_code.upper()] = cls
        cls.broker_code = broker_code.upper()
        return cls

    return _wrap


def get_adapter_class(broker_code: str) -> type[BrokerAdapter]:
    code = (broker_code or "").upper()
    # import 시점에 등록되므로 여기서 한 번 당겨 온다(순환 import 회피).
    from . import kiwoom  # noqa: F401

    try:
        return _ADAPTERS[code]
    except KeyError:
        raise LookupError(
            f"'{code}' 증권사 어댑터가 없습니다. 등록된 것: {sorted(_ADAPTERS) or '없음'}"
        ) from None


def supported_brokers() -> list[str]:
    from . import kiwoom  # noqa: F401

    return sorted(_ADAPTERS)
