"""키움 REST 연동.

`broker` 를 import 하는 것만으로 KiwoomAdapter 가 레지스트리에 등록된다
(brokers.registry.get_adapter_class 가 이 패키지를 당긴다).
"""
from .broker import KiwoomAdapter  # noqa: F401
