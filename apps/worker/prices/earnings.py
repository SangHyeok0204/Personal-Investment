"""미국 실적 발표 일정 — Nasdaq 공개 API, **키 없이**.

★야후는 막혔다(2026-09-22 실측): v7 quote 는 401 "User is unable to access this
  feature", v10 quoteSummary 는 401 "Invalid Crumb". 반면 Nasdaq 의
  `api.nasdaq.com/api/calendar/earnings?date=` 는 키 없이 200 이다.

★쓰는 엔드포인트
  · /api/calendar/earnings?date=YYYY-MM-DD   그 날 발표하는 종목들
  · /api/quote/{symbol}/eps                  분기별 컨센서스 vs 실제

⚠️브라우저 UA 가 없으면 거부당한다. 실측으로 필요했다.
⚠️캘린더는 **날짜마다 한 번씩** 불러야 한다. 기간 조회가 없다 — 동시에 던지되
  호출부가 캐시를 오래 잡아야 한다(실적 일정은 초 단위로 바뀌지 않는다).
⚠️응답의 숫자는 "$1.35", "N/A", "" 처럼 온다. 그대로 Decimal 에 넣으면 죽는다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx

BASE = "https://api.nasdaq.com/api"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 발표 시각 코드 → 사람이 읽는 말.
_TIME_LABEL = {
    "time-pre-market": "장전",
    "time-after-hours": "장후",
    "time-not-supplied": "미정",
}


def _money(value) -> Decimal | None:
    """"$1.35" · "N/A" · "" → Decimal | None. 못 읽으면 None(0 이 아니다)."""
    if value is None:
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text or text.upper() in {"N/A", "NA", "--"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return -result if negative else result


def _int(value) -> int | None:
    text = str(value or "").strip().replace(",", "")
    return int(text) if text.isdigit() else None


@dataclass(frozen=True)
class EarningsEvent:
    """실적 발표 예정 한 건."""

    report_date: date
    ticker: str
    company: str
    # 장전 / 장후 / 미정
    timing: str
    eps_forecast: Decimal | None
    estimate_count: int | None
    last_year_eps: Decimal | None
    market_cap: Decimal | None


@dataclass(frozen=True)
class EpsRow:
    """분기별 컨센서스 대비 실제."""

    period: str
    kind: str
    consensus: Decimal | None
    actual: Decimal | None

    @property
    def surprise(self) -> Decimal | None:
        """실제 − 컨센서스. 둘 중 하나라도 없으면 None."""
        if self.consensus is None or self.actual is None:
            return None
        return self.actual - self.consensus


def _client(timeout: float) -> httpx.Client:
    # ⚠️UA 가 없으면 Nasdaq 이 거부한다.
    return httpx.Client(timeout=timeout, headers={"User-Agent": _UA})


def fetch_calendar(
    start: date,
    days: int,
    *,
    max_workers: int = 6,
    timeout: float = 15.0,
) -> list[EarningsEvent]:
    """`start` 부터 `days` 일간의 발표 일정.

    주말은 아예 부르지 않는다 — 미국 실적은 주말에 발표하지 않는다.
    실패한 날짜는 결과에서 빠진다(전체를 죽이지 않는다).
    """
    targets = [
        start + timedelta(days=offset)
        for offset in range(days)
        if (start + timedelta(days=offset)).weekday() < 5
    ]
    if not targets:
        return []

    client = _client(timeout)

    def one(day: date) -> list[EarningsEvent]:
        try:
            response = client.get(
                f"{BASE}/calendar/earnings", params={"date": day.isoformat()}
            )
            if response.status_code != 200:
                return []
            rows = ((response.json() or {}).get("data") or {}).get("rows") or []
        except Exception:
            return []

        out: list[EarningsEvent] = []
        for row in rows:
            ticker = (row.get("symbol") or "").strip().upper()
            if not ticker:
                continue
            out.append(
                EarningsEvent(
                    report_date=day,
                    ticker=ticker,
                    company=(row.get("name") or "").strip(),
                    timing=_TIME_LABEL.get((row.get("time") or "").strip(), "미정"),
                    eps_forecast=_money(row.get("epsForecast")),
                    estimate_count=_int(row.get("noOfEsts")),
                    last_year_eps=_money(row.get("lastYearEPS")),
                    market_cap=_money(row.get("marketCap")),
                )
            )
        return out

    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
            batches = pool.map(one, targets)
        events = [event for batch in batches for event in batch]
    finally:
        client.close()

    events.sort(key=lambda e: (e.report_date, e.ticker))
    return events


def fetch_eps_history(symbol: str, *, timeout: float = 15.0) -> list[EpsRow]:
    """종목의 분기별 컨센서스 vs 실제. 실패하면 빈 목록."""
    client = _client(timeout)
    try:
        response = client.get(f"{BASE}/quote/{symbol.upper()}/eps")
        if response.status_code != 200:
            return []
        rows = ((response.json() or {}).get("data") or {}).get("earningsPerShare") or []
    except Exception:
        return []
    finally:
        client.close()

    out: list[EpsRow] = []
    for row in rows:
        period = (row.get("period") or "").strip()
        if not period:
            continue
        kind = (row.get("type") or "").strip()
        # ⚠️아직 발표 전인 분기는 실제 EPS 가 **0.0 으로 온다.** 그대로 읽으면
        #   "컨센서스 2.47 vs 실제 0" → 서프라이즈 -2.47 이라는 가짜 숫자가 나온다
        #   (실측: NVDA Oct 2026). 값이 아니라 **구분(type)** 으로 판정한다 —
        #   과거 분기가 정말 EPS 0.00 일 수도 있으므로 0 으로 거르면 안 된다.
        upcoming = "upcoming" in kind.lower()
        out.append(
            EpsRow(
                period=period,
                kind=kind,
                consensus=_money(row.get("consensus")),
                actual=None if upcoming else _money(row.get("earnings")),
            )
        )
    return out
