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
from datetime import date
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
        self.warnings: list[str] = []
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

    def not_stale(self, name: str, subject: str, ref: str, days: int = 1) -> None:
        """원장끼리 **최신일이 벌어졌는지**. 실패가 아니라 경고로 낸다 —
        증권사 피드 상태이지 우리 계산의 불일치가 아니다.

        ⚠️이게 왜 필요한가: 체결 원장이 2일 뒤처져 있는데 아무도 말해 주지
          않으면, 수수료/세금·편입비·매매일지가 **조용히 옛날 것**을 보여 준다.
          실측(2026-09-22): trades 최신 09-16, orders·realized 최신 09-18 —
          9/18 체결 4건이 체결 원장에 통째로 없었다.
        """
        self.checked += 1
        if not subject or not ref:
            print(f"  ?  {name}: 한쪽이 비어 있다")
            return
        gap = (date.fromisoformat(ref) - date.fromisoformat(subject)).days
        if gap <= days:
            print(f"  OK {name}: {subject} (기준 {ref})")
            return
        print(
            f"  !  {name}: {subject} — 기준 {ref} 보다 {gap}일 뒤처짐."
            f" 이 원장을 쓰는 화면은 그만큼 옛 것을 보여 준다"
        )
        self.warnings.append(f"{name} ({subject} vs {ref}, {gap}일)")

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
        trades = self.get("/portfolio/trades?days=1095")
        orders_payload = self.get("/portfolio/orders?days=365")
        orders_last = max(
            (o["order_date"] for o in orders_payload.get("items", [])),
            default=None,
        )
        tax_years = self.get("/portfolio/tax")["years"]
        rebalance = self.get("/portfolio/rebalance")
        benchmark = self.get("/portfolio/benchmark?days=1095")
        report_year = self.get("/portfolio/report?period=2026")
        report_months = [
            self.get(f"/portfolio/report?period={m}")
            for m in ("2026-06", "2026-07", "2026-08", "2026-09")
        ]
        allocation = self.get("/portfolio/allocation")
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
        # ★두 화면의 '순입금'은 **같은 기준**을 쓴다 — 투자 시작일(2026-06-04)
        #   이후만 세고, 시작 잔고에 이미 반영된 첫날 입금은 양쪽 다 제외한다.
        #   예전에는 cashflow 가 계좌 개설 이후 전부를 세서 차이가 첫날 입금액
        #   만큼 났다. 지금은 0 이 정상이고, 0 이 아니면 한쪽이 기준을 벗어난 것이다.
        self.same(
            "증감 (cashflow vs performance)",
            cashflow["gain_krw"],
            performance["gain_krw"],
            "cashflow", "performance",
        )
        self.same(
            "순입금 (같은 기준을 쓰는가)",
            cashflow["net_deposit_krw"], performance["net_deposit_krw"],
            "cashflow", "performance",
        )

        # ⚠️수익률 추이 화면의 타일 넷은 **왼쪽에서 오른쪽으로 더해진다.**
        #   주가 손익 + 환율 등(잔차) = 원화 증감. 이 등식이 깨지면 화면이
        #   서로 반대되는 말을 하게 된다 — 실제로 그런 적이 있다(타일은
        #   −₩722,749, 월별 표의 합은 +₩2,469,456).
        bridge = performance["bridge"]
        self.same(
            "다리 (주가 손익 + 환율 등 = 원화 증감)",
            dec(bridge["price_pnl_krw"]) + dec(bridge["fx_effect_krw"]),
            dec(bridge["asset_change_krw"]),
            "bridge", "bridge",
        )
        self.same(
            "다리의 원화 증감 (타일과 같은 값인가)",
            bridge["asset_change_krw"], performance["gain_krw"],
            "bridge", "performance",
        )
        # 못 잰 날을 **0 으로 치지 않았는지** 눈으로 확인할 수 있게 적는다.
        print(
            f"  ·  연쇄 수익률 {dec(bridge['twr']) * 100:.2f}% "
            f"({bridge['twr_days']}일 · 못 센 날 {bridge['unmeasured_days']} · "
            f"손익 빈 날 {bridge['missing_pnl_days']}) — **주가 기준**이라 "
            f"성과분석의 원화 기준 수익률과 값이 다르다"
        )

        # ── 기간 수익률 ────────────────────────────────────────────────
        # ⚠️같은 '내 계좌 수익률'을 두 화면이 각자 계산한다. 기준일이 하루만
        #   어긋나도 값이 갈린다 — 실측: 벤치마크 화면이 첫 수익률일의 지수를
        #   기준으로 삼아 첫날치가 빠지는 바람에 전체가 −1.21%, 성과 분석은
        #   −1.98% 였다. 같은 구간·같은 관측일수라 버그로 보이지도 않았다.
        print("\n[기간 수익률]")
        bench_by_label = {p["label"]: p for p in benchmark["periods"]}
        ana_by_label = {p["label"]: p for p in analytics["periods"]}
        for bench_label, ana_label in [("1M", "1개월"), ("3M", "3개월"), ("전체", "전체")]:
            b = bench_by_label.get(bench_label)
            a = ana_by_label.get(ana_label)
            if b is None or a is None:
                continue
            self.same(
                f"{ana_label} 수익률 (벤치마크 vs 성과분석)",
                b["portfolio"], a["return_ratio"],
                "benchmark", "analytics",
            )

        # ⚠️기간 리포트도 같은 계좌의 같은 수익률을 낸다. 세 화면이 다 맞아야
        #   한다 — 여기에 같은 기준일 실수가 있어 2026-09 가 +11.33% 로 나왔다
        #   (같은 화면의 자산 변화는 순납입 0 에 +9.02% 였다).
        self.same(
            "전체 수익률 (기간 리포트 2026 vs 성과분석)",
            report_year["twr"], ana_by_label["전체"]["return_ratio"],
            "report", "analytics",
        )

        # ★순납입이 0 인 달은 TWR 이 (끝−시작)÷시작 과 **정확히 같아야 한다.**
        #   흐름이 없으면 연쇄가 단순 비율로 무너지기 때문이다. 이 검사 하나면
        #   기준일이 하루 어긋나도 바로 걸린다.
        for r in report_months:
            if dec(r["net_flow_krw"]) != 0 or r["opening_assets_krw"] is None:
                continue
            opening = dec(r["opening_assets_krw"])
            if opening == 0:
                continue
            simple = (dec(r["closing_assets_krw"]) - opening) / opening
            self.same(
                f'{r["period"]["label"]} TWR (순납입 0 → 단순 비율과 같아야)',
                r["twr"], simple.quantize(Decimal("0.000001")),
                "report.twr", "report.assets",
            )

        # ★수익률 추이의 '다리'와 기간 리포트(2026)의 '자산 분해'는 **같은 값**을
        #   다르게 보여 주는 것이다. 어긋나면 둘 중 하나가 기준을 벗어난 것이다.
        bridge = performance["bridge"]
        self.same(
            "주가 손익 (수익률 추이 vs 기간 리포트 2026)",
            bridge["price_pnl_krw"], report_year["pnl_krw"],
            "performance.bridge", "report",
        )
        self.same(
            "환율 등 (수익률 추이 vs 기간 리포트 2026)",
            bridge["fx_effect_krw"], report_year["unexplained_krw"],
            "performance.bridge", "report",
        )

        # ⚠️'그 외' 분해는 넷을 더하면 합이 되어야 한다. 남는 것을 0 으로
        #   맞추지 않으므로, 이 검사는 **모형이 맞는지가 아니라 산수가 맞는지**를 본다.
        res = report_year["residual"]
        if res["fx_estimate_krw"] is not None:
            self.same(
                "'그 외' 분해 (환율+배당-수수료+남는것 = 합)",
                dec(res["fx_estimate_krw"]) + dec(res["dividend_krw"])
                - dec(res["cost_krw"]) + dec(res["leftover_krw"]),
                dec(res["total_krw"]),
                "residual", "residual",
            )
            share = abs(dec(res["leftover_krw"])) / abs(dec(res["total_krw"])) * 100
            print(f"  ·  설명 안 되는 몫 {share:.1f}% — 모형(환율 추정)의 한계다")

        # ── 보유 종목 산수 ─────────────────────────────────────────────
        # ⚠️증권사 평가손익은 **제비용을 뺀 값**이라 매입 + 손익 ≠ 평가액이다.
        #   화면에서 칸을 더해 보면 174,262 모자랐다. 그 몫을 실측 잔차로 내보내
        #   산수가 닫히게 했으니, 닫히는지 계속 본다.
        print("\n[보유 종목 산수]")
        self.same(
            "매입 + 평가손익 + 제비용 = 평가금액",
            dec(summary["purchase_amount_krw"]) + dec(summary["unrealized_pnl_krw"])
            + dec(summary["fee_reserve_krw"]),
            dec(summary["securities_value_krw"]),
            "summary", "summary",
        )
        # 제비용이 정말 제비용인지 — 모형(0.25% × (매입+평가))과 견준다.
        # ★검사가 아니라 **관찰**이다. 모형이 어긋나기 시작하면 수수료율이
        #   바뀌었거나 증권사 정의가 바뀐 것이다.
        gap = abs(dec(summary["fee_reserve_krw"]) - dec(summary["fee_reserve_modelled_krw"]))
        share = gap / abs(dec(summary["fee_reserve_krw"])) * 100
        print(
            f"  ·  제비용 {money(dec(summary['fee_reserve_krw']))} vs "
            f"모형 {money(dec(summary['fee_reserve_modelled_krw']))} "
            f"— 차이 {money(gap)} ({share:.1f}%). 0.25% × (매입+평가) 로 설명된다"
        )

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
        # ⚠️두 화면의 '순납입'은 **범위가 다르다.** 입출금 화면은 기간 첫날의
        #   흐름을 시작 잔고에 넣어 빼고, 월별 현금흐름은 그 달의 흐름을 그대로
        #   센다. 되더해 같은 범위로 맞춘 뒤 비교한다.
        self.same(
            "순납입 (첫날 포함 기준)",
            Decimal(cashflow["net_deposit_krw"] or 0)
            + Decimal(cashflow["first_day_flow_krw"] or 0),
            Decimal(monthly["total_deposit_krw"]) - Decimal(monthly["total_withdrawal_krw"]),
            "cashflow", "monthly-cashflow",
        )

        # ── 세금 ───────────────────────────────────────────────────────
        # ⚠️연도별로 나눠 본 값의 합이 전체와 같아야 한다. 연도 경계에서
        #   빠지거나 겹치는 건이 있으면 여기서 걸린다.
        print("\n[세금]")
        if taxes:
            # ⚠️세금 화면은 **역년(1/1~12/31)** 단위라 투자 기간과 범위가 다르다.
            #   배당·실현 건수를 동일성으로 비교하면 당연히 어긋난다 — 그건
            #   불일치가 아니라 **의도된 차이**다. 대신 세금 화면 안에서 연도별
            #   합이 서로 맞는지만 본다.
            print(
                f"  ·  세금은 역년 기준({', '.join(str(t['year']) for t in taxes)})"
                f" — 투자 기간({dividends.get('first_pay_date')}~)과 범위가 다르다"
            )
            self.same(
                "세금 화면 내부 (양도차익 = 양도가액 − 취득가액 − 필요경비)",
                sum(
                    Decimal(t["proceeds_krw"])
                    - Decimal(t["cost_basis_krw"])
                    - Decimal(t["expense_krw"])
                    for t in taxes
                ),
                sum(Decimal(t["gain_krw"]) for t in taxes),
                "계산", "gain_krw",
            )
        else:
            print("  ·  세금: 실현 내역이 없어 건너뜀")

        # ── 리밸런싱 ───────────────────────────────────────────────────
        # ⚠️비중의 **분모가 같아야** 두 화면이 같은 말을 한다. 리밸런싱이
        #   예수금을 넣거나 배분이 빼면, 같은 종목이 화면마다 다른 비중으로
        #   보인다 — 사용자는 그걸 버그로 읽는다.
        print("\n[리밸런싱]")
        # ⚠️분모가 갈리면 같은 종목이 화면마다 다른 비중으로 보인다
        #   (실측: SOXL 이 자산 현황 20.9% vs 리밸런싱 20.1% 였다).
        self.same(
            "비중 분모 (총자산 = 주식 + 예수금)",
            allocation["total_market_value_krw"],
            rebalance["base_value_krw"],
            "allocation", "rebalance",
        )
        self.same(
            "비중 분모 (자산 현황과도 같은가)",
            summary["total_assets_krw"],
            rebalance["base_value_krw"],
            "summary", "rebalance",
        )
        self.same(
            "보유 종목 수",
            Decimal(len(holdings["items"])),
            Decimal(len(rebalance["lines"]) + len(rebalance["untargeted"])),
            "holdings", "rebalance",
        )

        # ── 원장 신선도 ────────────────────────────────────────────────
        print("\n[원장 신선도]")
        self.not_stale(
            "체결 원장",
            trades.get("last_trade_date"),
            max(
                filter(None, [realized.get("last_sell_date"), orders_last]),
                default=None,
            ),
        )

        print(f"\n{'=' * 56}")
        if self.failures:
            print(f"불일치 {len(self.failures)}건 / 검사 {self.checked}건")
            for item in self.failures:
                print(f"  X {item}")
            return 1
        print(f"전부 일치 — 검사 {self.checked}건")
        if self.warnings:
            print(f"\n경고 {len(self.warnings)}건 (불일치는 아니지만 알아야 할 것):")
            for item in self.warnings:
                print(f"  !  {item}")
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
