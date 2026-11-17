"""야후 일별 종가 시계열 — 기간 변화 계산용.

`yahoo.py` 는 "지금 얼마인가"를 답하고, 여기는 "지난 1년 어떻게 움직였나"를
답한다. 한 번 호출로 1년치가 오므로 기간별 변화를 전부 이 한 응답에서 뽑는다.

⚠️`close` 배열에는 **null 이 섞여 온다**(휴장·데이터 누락). 그대로 인덱싱하면
  None 으로 나눗셈을 하게 된다. 날짜와 짝지어 null 을 걷어낸 뒤 쓴다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Series:
    """한 심볼의 일별 종가. 오름차순이고 결측은 이미 걷어냈다."""

    symbol: str
    dates: list[date]
    closes: list[Decimal]
    currency: str
    latest: Decimal | None

    def close_on_or_before(self, target: date) -> Decimal | None:
        """`target` 이하의 마지막 종가. 그 날이 휴장이어도 직전 값을 쓴다.

        ⚠️'없으면 첫 값'으로 떨어뜨리지 않는다. 1년치밖에 없는데 3년 전을 물으면
          기간이 통째로 틀린 값이 나온다 — 그럴 땐 None 이 맞다.
        """
        found: Decimal | None = None
        for day, close in zip(self.dates, self.closes):
            if day <= target:
                found = close
            else:
                break
        if found is None:
            return None
        # 요청한 시점이 보유 구간보다 앞서면 비교 대상이 없다.
        return found if self.dates and self.dates[0] <= target else None


def fetch_series(
    symbols: list[str],
    *,
    range_: str = "1y",
    max_workers: int = 8,
    timeout: float = 12.0,
) -> dict[str, Series]:
    """심볼별 일별 종가. 실패한 심볼은 결과에서 빠진다(전체를 죽이지 않는다)."""
    wanted = [s for s in dict.fromkeys(symbols) if s]
    if not wanted:
        return {}

    client = httpx.Client(timeout=timeout, headers={"User-Agent": _UA})

    def one(symbol: str) -> Series | None:
        try:
            response = client.get(
                f"{BASE}/{symbol}", params={"range": range_, "interval": "1d"}
            )
            if response.status_code != 200:
                return None
            result = (response.json().get("chart") or {}).get("result") or []
            if not result:
                return None
            node = result[0]
            stamps = node.get("timestamp") or []
            quote = (node.get("indicators") or {}).get("quote") or [{}]
            raw = quote[0].get("close") or []
            meta = node.get("meta") or {}
        except Exception:
            return None

        dates: list[date] = []
        closes: list[Decimal] = []
        for stamp, close in zip(stamps, raw):
            value = _dec(close)
            if value is None:
                continue  # ⚠️휴장·누락 — 건너뛴다. 0 으로 채우면 폭락처럼 보인다.
            dates.append(datetime.fromtimestamp(stamp, tz=timezone.utc).date())
            closes.append(value)

        if not closes:
            return None
        return Series(
            symbol=symbol,
            dates=dates,
            closes=closes,
            currency=meta.get("currency") or "",
            latest=_dec(meta.get("regularMarketPrice")) or closes[-1],
        )

    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(wanted))) as pool:
            found = pool.map(one, wanted)
        return {s.symbol: s for s in found if s is not None}
    finally:
        client.close()


@dataclass(frozen=True)
class Candles:
    """한 심볼의 일봉 OHLCV — **열 단위** 배열(같은 인덱스가 같은 날). 오름차순, 결측 봉은 뺐다.

    ★열 단위로 둔다 — 봉마다 객체를 만들면 10년치(≈2,500봉)가 JSON 에서 키 이름만 수만 번 반복된다.
    """

    symbol: str
    currency: str
    time: list[str]          # YYYY-MM-DD (거래소 현지 날짜)
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[int]


def fetch_candles(symbol: str, *, years: int = 10, timeout: float = 12.0) -> Candles | None:
    """최근 `years` 년 일봉 OHLCV. 못 받으면 None(예외를 내지 않는다).

    ⚠️`range=10y` 처럼 긴 range 를 주면 야후가 일봉을 월봉으로 바꿔 줄 때가 있다
      (`scripts/ohlcv_collect.py` 실측) — period1/period2 로 구간을 직접 준다.
    ⚠️날짜는 `gmtoffset` 으로 **거래소 현지** 날짜로 바꾼다. UTC 로 자르면 아시아 종목이 하루 밀린다.
    ⚠️OHLC 중 하나라도 null 인 봉은 뺀다(휴장·누락). 0 으로 채우면 폭락 봉이 그려진다.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - int(years * 365.25 * 86400)
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}) as client:
            response = client.get(
                f"{BASE}/{symbol}",
                params={"period1": start, "period2": now, "interval": "1d", "events": "history"},
            )
        if response.status_code != 200:
            return None
        result = (response.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        node = result[0]
        meta = node.get("meta") or {}
        stamps = node.get("timestamp") or []
        q = ((node.get("indicators") or {}).get("quote") or [{}])[0]
    except Exception:
        return None

    offset = int(meta.get("gmtoffset") or 0)
    out = Candles(symbol=symbol, currency=meta.get("currency") or "",
                  time=[], open=[], high=[], low=[], close=[], volume=[])
    rows = zip(stamps, q.get("open") or [], q.get("high") or [], q.get("low") or [],
               q.get("close") or [], q.get("volume") or [])
    last_day = None
    for stamp, o, h, low, c, v in rows:
        if None in (o, h, low, c):
            continue
        day = datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date().isoformat()
        if day == last_day:      # 같은 날 봉이 두 번 오면(장중 마지막 봉) 뒤의 것으로
            for col in (out.time, out.open, out.high, out.low, out.close, out.volume):
                col.pop()
        last_day = day
        out.time.append(day)
        out.open.append(round(float(o), 4))
        out.high.append(round(float(h), 4))
        out.low.append(round(float(low), 4))
        out.close.append(round(float(c), 4))
        out.volume.append(int(v or 0))
    return out if out.time else None


# 화면에 세울 기간. (라벨, 달력일수). YTD 는 일수가 아니라 따로 계산한다.
PERIODS: list[tuple[str, int]] = [
    ("1D", 1),
    ("1W", 7),
    ("1M", 30),
    ("3M", 91),
    ("6M", 182),
    ("1Y", 365),
]


def changes(series: Series, today: date | None = None) -> dict[str, Decimal | None]:
    """기간별 **변화량**(비율이 아니라 원값 차이).

    비율로 바꿀지 bp 로 바꿀지는 호출부가 `kind` 를 보고 정한다 — 금리는
    퍼센트 수익률이 의미가 없어서 여기서 미리 나누지 않는다.
    """
    anchor = today or (series.dates[-1] if series.dates else date.today())
    latest = series.latest if series.latest is not None else series.closes[-1]

    out: dict[str, Decimal | None] = {}
    for label, days in PERIODS:
        past = series.close_on_or_before(anchor - timedelta(days=days))
        out[label] = None if past is None else latest - past

    # YTD — 올해 첫 거래일 **직전**(= 작년 마지막 종가)이 기준이다.
    year_start = series.close_on_or_before(date(anchor.year, 1, 1) - timedelta(days=1))
    out["YTD"] = None if year_start is None else latest - year_start
    return out


def base_values(series: Series, today: date | None = None) -> dict[str, Decimal | None]:
    """기간별 **기준 시점의 값**. 비율을 내려면 분모가 필요하다."""
    anchor = today or (series.dates[-1] if series.dates else date.today())
    out: dict[str, Decimal | None] = {}
    for label, days in PERIODS:
        out[label] = series.close_on_or_before(anchor - timedelta(days=days))
    out["YTD"] = series.close_on_or_before(
        date(anchor.year, 1, 1) - timedelta(days=1)
    )
    return out
