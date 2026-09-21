"""FRED 시계열 — **키 없이** 받는다.

⚠️FRED **API**(`api.stlouisfed.org/fred/...`)는 `api_key` 가 없으면 400 이다
  (실측: "Variable api_key is not set"). 반면 **그래프 CSV 내보내기**
  (`fred.stlouisfed.org/graph/fredgraph.csv?id=`)는 키 없이 200 이다.
  6개 시리즈로 확인했다(2026-09-22). 그래서 이 경로를 쓴다.

CSV 형식:
    observation_date,CPIAUCSL
    1947-01-01,21.480
    ...
    2026-08-01,334.131

⚠️결측은 `.` 또는 빈 칸으로 온다(일간 시리즈의 휴장일). 0 으로 바꾸면 폭락처럼
  보이므로 **행을 버린다**.
"""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass(frozen=True)
class MacroSeries:
    """한 지표의 관측치. 오름차순이고 결측은 이미 걷어냈다."""

    series_id: str
    dates: list[date]
    values: list[Decimal]

    @property
    def latest(self) -> tuple[date, Decimal] | None:
        if not self.dates:
            return None
        return self.dates[-1], self.values[-1]

    def value_on_or_before(self, target: date) -> Decimal | None:
        """`target` 이하의 마지막 관측치.

        ⚠️보유 구간보다 앞선 시점을 물으면 None 이다. '없으면 첫 값'으로
          떨어뜨리면 기간이 통째로 틀린 값이 조용히 나온다.
        """
        if not self.dates or self.dates[0] > target:
            return None
        found: Decimal | None = None
        for day, value in zip(self.dates, self.values):
            if day <= target:
                found = value
            else:
                break
        return found

    def yoy(self, at: date | None = None) -> Decimal | None:
        """전년 대비 변화율. 지수 시리즈(CPI 등)의 본래 읽는 값이다."""
        anchor = at or (self.dates[-1] if self.dates else None)
        if anchor is None:
            return None
        current = self.value_on_or_before(anchor)
        past = self.value_on_or_before(anchor - timedelta(days=365))
        if current is None or past is None or past == 0:
            return None
        return (current - past) / past

    def mom_diff(self, at: date | None = None) -> Decimal | None:
        """전월 대비 증감(원 단위). 누적 수치(고용자 수 등)의 본래 읽는 값이다."""
        anchor = at or (self.dates[-1] if self.dates else None)
        if anchor is None:
            return None
        current = self.value_on_or_before(anchor)
        # ⚠️30일이 아니라 25일 전으로 본다. 월간 시리즈는 매월 1일에 찍히는데
        #   30일 전은 같은 달로 떨어질 수 있다(31일 달 다음).
        past = self.value_on_or_before(anchor - timedelta(days=25))
        if current is None or past is None or current == past:
            return None
        return current - past


def _parse(text: str, series_id: str) -> MacroSeries:
    dates: list[date] = []
    values: list[Decimal] = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        return MacroSeries(series_id, [], [])
    for row in reader:
        if len(row) < 2:
            continue
        raw = (row[1] or "").strip()
        # ⚠️결측(`.`/빈칸)은 버린다. 0 으로 채우면 폭락처럼 보인다.
        if not raw or raw == ".":
            continue
        try:
            value = Decimal(raw)
            day = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
        except (InvalidOperation, ValueError):
            continue
        dates.append(day)
        values.append(value)
    return MacroSeries(series_id, dates, values)


def fetch_series(
    series_ids: list[str],
    *,
    max_workers: int = 6,
    timeout: float = 20.0,
) -> dict[str, MacroSeries]:
    """시리즈별 관측치. 실패한 시리즈는 결과에서 빠진다(전체를 죽이지 않는다)."""
    wanted = [s for s in dict.fromkeys(series_ids) if s]
    if not wanted:
        return {}

    client = httpx.Client(timeout=timeout, headers={"User-Agent": _UA})

    def one(series_id: str) -> MacroSeries | None:
        try:
            response = client.get(BASE, params={"id": series_id})
            if response.status_code != 200:
                return None
            series = _parse(response.text, series_id)
        except Exception:
            return None
        return series if series.dates else None

    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(wanted))) as pool:
            found = pool.map(one, wanted)
        return {s.series_id: s for s in found if s is not None}
    finally:
        client.close()
