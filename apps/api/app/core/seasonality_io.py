"""계절성 원자료 입출력 — 블룸버그 BDH 엑셀 파싱과 월 수익률 계산.

원본 `Downloads/계절성/seasonality.py::load_prices` 를 옮겼다. 엑셀 한 장에 3열씩
(날짜 · 값 · 빈칸) 블록이 이어지고, 첫 행에 티커가 적혀 있다.

⚠️각 블록의 첫 날짜 칸에는 캐시된 문자열 "#N/A Requesting Data..." 가 남아 있다
  (BDH 가 계산 중이던 흔적). 날짜가 아닌 행은 건너뛴다 — 원본도 그렇게 해서 첫 달을 잃는다.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


def month_key(d: date | datetime) -> str:
    """월초(Yahoo)든 월말(블룸버그)이든 같은 달이면 같은 키."""
    return f"{d.year:04d}-{d.month:02d}"


def parse_bdh_xlsx(path: str | Path, tickers: set[str]) -> dict[str, dict[str, float]]:
    """{티커: {'YYYY-MM': 종가}}. `tickers` 에 없는 블록은 무시한다."""
    import openpyxl  # 시드 때만 쓴다 — API 기동에 필요 없다

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    ncols = max(len(r) for r in rows)
    out: dict[str, dict[str, float]] = {}
    for i in range(0, ncols, 3):
        ticker = rows[0][i] if i < len(rows[0]) else None
        if ticker not in tickers:
            continue
        series: dict[str, float] = {}
        for r in rows[1:]:
            d = r[i] if i < len(r) else None
            v = r[i + 1] if i + 1 < len(r) else None
            if hasattr(d, "year") and isinstance(v, (int, float)):
                series[month_key(d)] = float(v)
        out[ticker] = series
    return out


def consecutive_pairs(months: list[str]) -> int:
    """연속한 두 달 쌍의 수 = 계산 가능한 월 수익률의 수.

    ⚠️빈 달(항셍 1964~69 등) 건너편끼리는 **쌍이 아니다** — 두세 달 변화를 한 달
    수익률로 세지 않는다(계획 §D-0). 원본 통계의 n 합계와 대조하는 데 쓴다.
    """
    def idx(m: str) -> int:
        y, mm = m.split("-")
        return int(y) * 12 + int(mm)

    ordered = sorted(idx(m) for m in months)
    return sum(1 for a, b in zip(ordered, ordered[1:]) if b - a == 1)
