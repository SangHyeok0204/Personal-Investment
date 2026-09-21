"""AI 생태계 지표 — Epoch AI + npm. **키 없이**.

이 화면이 원래 쓰던 collector 는 이 환경에 없다(503). 공개 데이터로 다시 세웠다.

★출처
  · Epoch AI `ml_hardware.csv`  — AI 가속기 176종의 성능·메모리·TDP·출시가.
    NVIDIA 91종. 보유한 NVDA·AMD 와 직결된다.
  · npm `api.npmjs.org/downloads` — AI SDK 다운로드. "모델을 실제로 쓰고 있나"의
    대리 지표다. 매출은 분기에 한 번 나오지만 이건 매일 나온다.

⚠️Epoch CSV 는 **빈 칸이 흔하다**(가격·성능 미공개). 0 으로 채우면 "무료" 나
  "성능 0" 이 된다 — None 으로 둔다.
⚠️npm 은 스코프 패키지(`@anthropic-ai/sdk`)도 경로에 그대로 넣는다. URL 인코딩
  하면 404 다(실측).
"""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

EPOCH_HARDWARE = "https://epoch.ai/data/ml_hardware.csv"
NPM_BASE = "https://api.npmjs.org/downloads/range/last-month"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _dec(value) -> Decimal | None:
    """빈 칸·'N/A' 는 None. **0 으로 만들지 않는다** — 미공개와 0 은 다르다."""
    text = str(value or "").strip().replace(",", "")
    if not text or text.upper() in {"N/A", "NA", "-", "--"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _day(value) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class Accelerator:
    """AI 가속기 한 종."""

    name: str
    manufacturer: str
    kind: str
    release_date: date | None
    price_usd: Decimal | None
    fp16_flops: Decimal | None
    fp8_flops: Decimal | None
    memory_bytes: Decimal | None
    bandwidth_bytes: Decimal | None
    tdp_watts: Decimal | None

    @property
    def flops_per_watt(self) -> Decimal | None:
        """FP16 성능 ÷ 소비전력. 데이터센터에서 실제로 따지는 값이다."""
        if self.fp16_flops is None or not self.tdp_watts:
            return None
        return self.fp16_flops / self.tdp_watts


@dataclass(frozen=True)
class PackageDownloads:
    """npm 패키지 다운로드 추이."""

    package: str
    label: str
    days: list[date]
    counts: list[int]

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def last_week(self) -> int:
        return sum(self.counts[-7:])

    @property
    def prior_week(self) -> int:
        return sum(self.counts[-14:-7])

    @property
    def week_over_week(self) -> Decimal | None:
        """주간 증감률. 직전 주가 0 이면 나눌 수 없다."""
        prior = self.prior_week
        if prior <= 0:
            return None
        return (Decimal(self.last_week) - Decimal(prior)) / Decimal(prior)


def fetch_accelerators(*, timeout: float = 30.0) -> list[Accelerator]:
    """Epoch AI 가속기 목록. 실패하면 빈 목록."""
    try:
        response = httpx.get(
            EPOCH_HARDWARE,
            headers={"User-Agent": _UA},
            timeout=timeout,
            follow_redirects=True,
        )
        if response.status_code != 200:
            return []
        rows = list(csv.DictReader(io.StringIO(response.text)))
    except Exception:
        return []

    out: list[Accelerator] = []
    for row in rows:
        name = (row.get("Hardware name") or "").strip()
        if not name:
            continue
        out.append(
            Accelerator(
                name=name,
                manufacturer=(row.get("Manufacturer") or "미상").strip(),
                kind=(row.get("Type") or "").strip(),
                release_date=_day(row.get("Release date")),
                price_usd=_dec(row.get("Release price (USD)")),
                fp16_flops=_dec(row.get("Tensor-FP16/BF16 performance (FLOP/s)")),
                fp8_flops=_dec(row.get("FP8 performance (FLOP/s)")),
                memory_bytes=_dec(row.get("Memory (bytes)")),
                bandwidth_bytes=_dec(row.get("Memory bandwidth (byte/s)")),
                tdp_watts=_dec(row.get("TDP (W)")),
            )
        )
    return out


def fetch_downloads(
    packages: list[tuple[str, str]],
    *,
    max_workers: int = 6,
    timeout: float = 20.0,
) -> list[PackageDownloads]:
    """npm 일별 다운로드. `packages` 는 (패키지명, 표시이름) 목록."""
    if not packages:
        return []
    client = httpx.Client(timeout=timeout, headers={"User-Agent": _UA})

    def one(entry: tuple[str, str]) -> PackageDownloads | None:
        package, label = entry
        try:
            # ⚠️스코프 패키지도 경로에 **그대로** 넣는다. 인코딩하면 404 다.
            response = client.get(f"{NPM_BASE}/{package}")
            if response.status_code != 200:
                return None
            rows = (response.json() or {}).get("downloads") or []
        except Exception:
            return None

        days: list[date] = []
        counts: list[int] = []
        for row in rows:
            day = _day(row.get("day"))
            if day is None:
                continue
            days.append(day)
            counts.append(int(row.get("downloads") or 0))
        if not counts:
            return None
        return PackageDownloads(package=package, label=label, days=days, counts=counts)

    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(packages))) as pool:
            found = pool.map(one, packages)
        return [p for p in found if p is not None]
    finally:
        client.close()
