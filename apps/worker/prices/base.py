"""시세 소스 추상 — 보유 종목의 **현재가**를 어디서 받아올지.

★2026-09-21 정정(사용자): 토스는 계좌가 아니다. 키움 계좌의 보유 종목에 대해
  실시간 가격을 받아오는 **시세 소스**다. 이전 커밋에서 토스를 계좌 목록에 섞어
  두었는데, 그러면 "토스 계좌 잔고"라는 존재하지 않는 것을 화면이 약속하게 된다.

왜 증권사 잔고의 현재가를 그대로 안 쓰나:
  키움 잔고 조회(kt00018)는 조회 시점의 현재가를 같이 주지만, 잔고 TR 은 무거워서
  자주 부를 수 없다(유량제한·응답크기). 보유 종목 목록은 자주 바뀌지 않으므로
  **종목 목록은 증권사에서, 가격은 가벼운 시세 소스에서** 따로 받는 편이 낫다.

계약은 하나다 — 심볼 목록을 주면 {symbol: Quote} 를 돌려준다.
소스를 늘릴 때(야후·KRX·증권사 시세) 이 계약만 구현하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Quote:
    """한 종목의 시세 한 점."""

    symbol: str
    price: Decimal
    currency: str = "KRW"
    # 전일 종가 — 당일 등락 계산용. 없으면 등락을 그리지 않는다(0으로 두지 않는다).
    previous_close: Decimal | None = None
    as_of: datetime | None = None
    source: str = ""

    @property
    def change(self) -> Decimal | None:
        if self.previous_close is None:
            return None
        return self.price - self.previous_close

    @property
    def change_rate(self) -> Decimal | None:
        if self.previous_close in (None, 0):
            return None
        return (self.price - self.previous_close) / self.previous_close


class PriceSource:
    """심볼 → 현재가.

    구현체는 자격증명을 받아 생성된다. 실패는 **부분 실패를 허용**한다 —
    한 종목을 못 받았다고 전체가 죽으면 대시보드가 통째로 빈다. 못 받은 심볼은
    결과 dict 에서 빠지고, 호출부는 그 종목만 "—" 로 그린다.
    """

    name: str = ""
    #: 이 소스가 다룰 수 있는 시장. 라우터가 심볼을 나눠 보낼 때 쓴다.
    markets: tuple[str, ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """네트워크 자원 정리."""

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        raise NotImplementedError


class CompositePriceSource(PriceSource):
    """여러 소스를 순서대로 시도한다 — 앞의 소스가 못 준 심볼만 뒤로 넘긴다.

    DailyPriceAgent 의 universe.yaml 이 쓰던 방식(yahoo 우선, toss 폴백)과 같은
    생각이다. 한 소스가 막혀도(예: IP 허용목록) 화면이 통째로 비지 않는다.
    """

    name = "composite"

    def __init__(self, sources: list[PriceSource]):
        self._sources = sources

    def close(self):
        for s in self._sources:
            s.close()

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        remaining = list(symbols)
        out: dict[str, Quote] = {}
        for source in self._sources:
            if not remaining:
                break
            try:
                got = source.quotes(remaining)
            except Exception:
                # 소스 하나가 통째로 실패해도 다음 소스로 넘어간다.
                continue
            out.update(got)
            remaining = [s for s in remaining if s not in out]
        return out
