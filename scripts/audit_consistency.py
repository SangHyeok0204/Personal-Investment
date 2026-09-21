#!/usr/bin/env python3
"""화면 간 숫자 정합성 대조.

같은 값을 여러 화면이 각자 계산한다. 한 곳이 어긋나면 대시보드 전체를 못 믿게
되므로, 같은 뜻의 숫자를 엔드포인트별로 뽑아 맞는지 본다.

실행:
    .venv/bin/python scripts/audit_consistency.py [--base http://localhost:8000]

⚠️서버가 떠 있고 계좌 데이터가 적재돼 있어야 한다. 데이터가 없으면 비교할 게
  없으므로 '건너뜀'으로 끝난다(실패가 아니다).

★**의도적으로 다른 값**도 여기 적어 둔다. 다르다고 전부 버그가 아니다 —
  왜 다른지 모르면 다음 사람이 '고치다가' 맞는 걸 깨뜨린다.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

import httpx

TIMEOUT = 90.0
# 원 단위 비교 허용치. 서버가 소수 2자리로 반올림해 내보내므로 1원이면 넉넉하다.
MONEY_TOL = Decimal("1")


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def money(value) -> str:
    """금액은 원 단위로, **비율은 비율답게** 찍는다.

    ⚠️처음엔 전부 `:,.0f` 로 찍었더니 기여도 0.0854 가 "0" 으로 보였다 —
      맞는 값인데 틀린 것처럼 읽힌다.
    """
    if value is None:
        return "—"
    number = float(value)
    if number != 0 and abs(number) < 1:
        return f"{number:.8f}"
    return f"{number:,.0f}"


class Audit:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.client = httpx.Client(timeout=TIMEOUT)
        self.failures: list[str] = []
        self.checked = 0

    def get(self, path: str):
        response = self.client.get(f"{self.base}/api/v1{path}")
        response.raise_for_status()
        return response.json()

    def same(self, name: str, left, right, la: str, lb: str, tol=MONEY_TOL) -> None:
        self.checked += 1
        a, b = dec(left), dec(right)
        if a is None or b is None:
            print(f"  ?  {name}: {la}={money(a)} / {lb}={money(b)} — 한쪽이 비어 있다")
            return
        diff = abs(a - b)
        if diff <= tol:
            print(f"  OK {name}: {money(a)}")
        else:
            print(f"  X  {name}: {la}={money(a)}  {lb}={money(b)}  차이 {money(diff)}")
            self.failures.append(f"{name} ({la}={money(a)} vs {lb}={money(b)})")

    def same_set(self, name: str, left: set[str], right: set[str], la: str, lb: str) -> None:
        self.checked += 1
        if left == right:
            print(f"  OK {name}: {len(left)}종목 일치")
            return
        print(f"  X  {name}: {la}에만 {sorted(left - right)} / {lb}에만 {sorted(right - left)}")
        self.failures.append(name)

    def run(self) -> int:
        summary = self.get("/portfolio/summary")
        # ⚠️`connected` 는 /portfolio/accounts 에만 있고 summary 에는 없다.
        #   summary.get("connected") 로 막았더니 항상 None → 전부 건너뛰었다.
        #   데이터 유무는 **보유 종목 수**로 판정한다.
        if not summary.get("position_count"):
            print("보유 종목이 없다 — 비교할 데이터가 없어 건너뛴다.")
            return 0

        holdings = self.get("/portfolio/holdings")
        quotes = self.get("/portfolio/quotes")
        analytics = self.get("/portfolio/performance/analytics?days=1095")
        inclusion = self.get("/portfolio/inclusion")
        cashflow = self.get("/portfolio/cashflow?days=1095")
        performance = self.get("/portfolio/performance?days=1095")
        realized = self.get("/portfolio/realized?days=1095")
        dividends = self.get("/portfolio/dividends?days=1095")
        monthly = self.get("/portfolio/monthly-cashflow?days=1095")
        tax_years = self.get("/portfolio/tax")["years"]
        taxes = [self.get(f"/portfolio/tax?year={y}")["current"] for y in tax_years]

        print("\n[평가금액·손익]")
        self.same(
            "보유종목 평가액",
            summary["securities_value_krw"],
            holdings["total_market_value_krw"],
            "summary", "holdings",
        )
        self.same(
            "평가손익",
            summary["unrealized_pnl_krw"],
            analytics["total_unrealized_pnl_krw"],
            "summary", "analytics",
        )

        print("\n[보유 종목 집합]")
        self.same_set(
            "holdings vs quotes",
            {x["ticker"] for x in holdings["items"]},
            {x["ticker"] for x in quotes["items"]},
            "holdings", "quotes",
        )
        self.same_set(
            "holdings vs inclusion(OPEN)",
            {x["ticker"] for x in holdings["items"]},
            {x["ticker"] for x in inclusion["holdings"] if x["status"] == "OPEN"},
            "holdings", "inclusion",
        )

        print("\n[기여도 검산]")
        total = sum(
            Decimal(str(c["contribution"]))
            for c in analytics["contributions"]
            if c["contribution"] is not None
        )
        # ⚠️"정확히" 같지는 않다. 종목마다 반올림해 더하므로 마지막 자리가 남는다.
        #   표시 정밀도(소수 2자리 %)보다 한참 아래면 정상이다.
        self.same(
            "기여도 합 = 평가수익률",
            total,
            analytics["total_return"],
            "기여도합", "total_return",
            tol=Decimal("0.00001"),
        )

        print("\n[입출금·증감]")
        # ★두 화면의 '순입금'은 **의도적으로 다르다**:
        #   · performance — 조회 구간 시작일 **이후**만(시작 자산에 이미 반영된
        #     첫날 입금은 제외). 그래야 gain = 끝 − 시작 − 순입금이 성립한다.
        #   · cashflow — 계좌 개설 이후 **전부**. "내가 넣은 돈"이 그 화면의 질문이다.
        #   차이는 정확히 첫날 입금액이어야 하고, **증감은 같아야 한다**.
        self.same(
            "증감 (cashflow vs performance)",
            cashflow["gain_krw"],
            performance["gain_krw"],
            "cashflow", "performance",
        )
        gap = dec(cashflow["net_deposit_krw"]) - dec(performance["net_deposit_krw"])
        print(f"  ·  순입금 차이 {money(gap)} — 첫날 입금분(의도된 차이)")

        print("\n[실현손익·배당]")
        self.same(
            "실현손익", realized["pnl_krw"], analytics["realized_pnl_krw"],
            "realized", "analytics",
        )
        self.same(
            "배당", dividends["total_amount_krw"], analytics["dividend_krw"],
            "dividends", "analytics",
        )

        # ── 월별 현금흐름 ──────────────────────────────────────────────
        # ⚠️두 화면의 원천이 **다르다**: 배당 화면은 dividends 테이블,
        #   월별 현금흐름은 account_daily_performance 다. 같은 사실을 증권사가
        #   두 군데에 적어 둔 것이므로 값이 갈리면 적재 어딘가가 틀린 것이다.
        print("\n[월별 현금흐름]")
        self.same(
            "배당 총계", dividends["total_amount_krw"], monthly["total_dividend_krw"],
            "dividends", "monthly-cashflow",
        )
        # 순납입도 같은 원천(일별성과)이라 입출금 화면과 정확히 같아야 한다.
        self.same(
            "순납입",
            Decimal(cashflow["total_deposit_krw"] or 0)
            - Decimal(cashflow["total_withdrawal_krw"] or 0),
            Decimal(monthly["total_deposit_krw"]) - Decimal(monthly["total_withdrawal_krw"]),
            "cashflow", "monthly-cashflow",
        )

        # ── 세금 ───────────────────────────────────────────────────────
        # ⚠️연도별로 나눠 본 값의 합이 전체와 같아야 한다. 연도 경계에서
        #   빠지거나 겹치는 건이 있으면 여기서 걸린다.
        print("\n[세금]")
        if taxes:
            self.same(
                "배당 (연도 합)",
                dividends["total_amount_krw"],
                sum(Decimal(t["dividend_krw"]) for t in taxes),
                "dividends", "tax",
            )
            self.same(
                "실현 건수 (연도 합)",
                Decimal(len(realized["items"])),
                Decimal(sum(t["sale_count"] for t in taxes)),
                "realized", "tax",
            )
        else:
            print("  ·  세금: 실현 내역이 없어 건너뜀")

        print(f"\n{'=' * 56}")
        if self.failures:
            print(f"불일치 {len(self.failures)}건 / 검사 {self.checked}건")
            for item in self.failures:
                print(f"  X {item}")
            return 1
        print(f"전부 일치 — 검사 {self.checked}건")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()

    audit = Audit(args.base)
    try:
        return audit.run()
    except httpx.HTTPError as exc:
        print(f"API 호출 실패: {exc}", file=sys.stderr)
        return 2
    finally:
        audit.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
