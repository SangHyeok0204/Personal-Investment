"use client";

import { useState, type ReactNode } from "react";
import { Topbar } from "@/components/layout/topbar";
import { AiUsageCard } from "@/components/ai-key-data/ai-usage-card";
import { BondIssuanceCard } from "@/components/ai-key-data/bond-issuance-card";
import { ComputeIndexCard } from "@/components/ai-key-data/compute-index-card";
import { EpochCard } from "@/components/ai-key-data/epoch-card";
import { EpochFundingCard } from "@/components/ai-key-data/epoch-funding-card";
import { PolicyRateCard } from "@/components/ai-key-data/policy-rate-card";
import { RateChartCard } from "@/components/ai-key-data/rate-chart-card";
import { ToolCallingCard } from "@/components/ai-key-data/tool-calling-card";
import { TabChips } from "@/components/ai-key-data/tab-chips";

// [AI Key Data] — 시장 모니터링 하위.
//
// ★★2026-08-31 사용자 지시로 **분류 3개(Demand · 수익성 · 매크로)** 로 재편했다.
//   그 전에는 카드 6장이 성격 구분 없이 6×2 그리드에 흩어져 있었다.
//
// 화면 규격: 세로 3분할(분류 하나가 한 행) × 각 행 안에 카드 2장 = **차트 패널 6칸**.
//   분류 박스가 행을 통째로 갖고, 그 안쪽 그리드는 **6컬럼 그대로**다 — 그래야 카드들이
//   이미 갖고 있는 `lg:col-span-3` 이 손대지 않고도 맞는다(사용자 지시: 카드는 건드리지 말 것).
//   바깥 padding·gap 은 0(화면 꽉 채움). 카드 사이 1.5px 만 남긴다 — 카드가 rounded 라
//   완전히 붙이면 모서리가 서로 파고든다.
//
// 분류 근거:
//   · Demand   = 얼마나 쓰는가.   토큰·CLI 설치·확장 설치·툴콜 강도. 전부 일별 채택 지표다.
//   · 수익성   = 얼마를 버는가/그 뒤에 얼마가 깔렸는가. ARR·칩 공급·데이터센터·임대단가.
//               ★GPU 임대지수를 여기 둔 이유: 임대료는 컴퓨트 공급자의 **매출 단가**라
//                 ARR·H100e 와 같은 축이다(수요 지표가 아니다).
//   · 매크로   = 조달 조건. 정책금리·채권발행·물가·유가·고용·FOMC 확률.
//
// ★2026-08-31(2차) 펀딩 라운드는 사용자 지시로 [Demand] 로 이사 완료했다.
//   과거 메모(아래)는 이사 전 상태를 적은 것이라 무효다.
// ~~⚠️펀딩 라운드는 지금 [수익성] 의 Epoch 카드 안에 있다.~~ 사용자는 Demand 로 지정했는데,
//   그 데이터가 `EpochCard` 의 "AI 기업" 탭에서 매출(ARR)과 **한 패널 쌍으로 묶여** 있어서
//   떼어내려면 카드를 쪼개야 한다 — "카드는 건드리지 말라"와 정면으로 충돌한다.
//   그래서 이번에는 카드를 보존하고 Epoch 을 통째로 수익성에 뒀다. 쪼개는 편이 낫다고
//   판단되면 `EpochCard` 를 companies-revenue / companies-funding 로 가르면 된다.
//
// ★탭 상태를 **카드가 아니라 이 페이지가 든다** — 한 칸에 서로 다른 컴포넌트를 갈아 끼우는
//   묶음(매크로 4탭 · 물가/유가 2탭)이라 상태가 카드 밖에 있어야 한다. AI 사용량·Epoch 처럼
//   한 컴포넌트 안에서 탭이 도는 경우는 카드가 그대로 들고 있다.

// Demand 두 번째 슬롯 — Tool-calling 과 펀딩 라운드를 갈아 끼운다.
// ★2026-08-31 사용자 지시로 펀딩을 Epoch 카드에서 떼어 Demand 로 옮겼는데, 그대로
//   놓으면 이 행만 카드가 3장이 되어 2x3 이 깨진다. 그래서 같은 칸에 탭으로 겹쳤다
//   (매크로·물가 묶음과 같은 방식 — 서로 다른 컴포넌트라 상태를 페이지가 든다).
type DemandTab = "tool" | "funding";
const DEMAND_TABS: { key: DemandTab; label: string }[] = [
  { key: "tool", label: "Tool-calling" },
  { key: "funding", label: "펀딩 라운드" },
];

// ★2026-08-31 사용자 지시 — **정책금리와 FOMC 내재확률을 한 탭으로 묶는다.**
//   둘은 같은 것을 앞뒤로 보는 지표다(정책금리 = 이미 정해진 것, FOMC 확률 = 시장이
//   보는 다음 것). 따로 탭을 두면 둘을 나란히 못 봐서 "지금 여기서 어디로 가는가"가 안 읽힌다.
//   그래서 이 탭만 슬롯을 2열로 갈라 왼쪽 정책금리 · 오른쪽 FOMC 확률을 같이 띄운다.
type MacroTab = "rates" | "bonds" | "adp";
const MACRO_TABS: { key: MacroTab; label: string }[] = [
  { key: "rates", label: "정책금리 · FOMC" },
  { key: "bonds", label: "채권 발행" },
  { key: "adp", label: "ADP 고용" },
];

type PriceTab = "inflation" | "wti";
const PRICE_TABS: { key: PriceTab; label: string }[] = [
  { key: "inflation", label: "미국 인플레이션" },
  { key: "wti", label: "WTI 유가" },
];

// 분류 박스 — 라벨 띠 + 6컬럼 카드 영역. 띠 색은 `ge-navy`(카드 제목 띠의 `ge-header`
// 다크브라운과 일부러 다르게 둔다 — 같으면 분류와 카드의 위계가 안 읽힌다).
function CategoryBox({
  label,
  sub,
  children,
}: {
  label: string;
  sub: string;
  children: ReactNode;
}) {
  return (
    <section className="flex min-h-0 flex-col">
      <div className="flex shrink-0 items-baseline gap-2 bg-ge-navy px-3 py-[3px]">
        <span className="text-[13.5px] font-extrabold tracking-wide text-white">{label}</span>
        <span className="truncate text-[12px] text-white/55">{sub}</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-1.5 p-1.5 pt-1 lg:grid-cols-6">
        {children}
      </div>
    </section>
  );
}

export default function AiKeyDataPage() {
  const [demandTab, setDemandTab] = useState<DemandTab>("tool");
  const [macroTab, setMacroTab] = useState<MacroTab>("rates");
  const [priceTab, setPriceTab] = useState<PriceTab>("inflation");

  const demandChips = (
    <TabChips tabs={DEMAND_TABS} value={demandTab} onChange={setDemandTab} />
  );
  const macroChips = <TabChips tabs={MACRO_TABS} value={macroTab} onChange={setMacroTab} />;
  const priceChips = <TabChips tabs={PRICE_TABS} value={priceTab} onChange={setPriceTab} />;

  return (
    // 높이를 여기서 확정한다 — 루트 레이아웃이 min-h-screen 이라 그대로 두면 grid-rows-3 가
    // 내용 높이로 커져 3등분이 아니게 되고 페이지가 스크롤된다.
    <div className="flex h-screen flex-col">
      <Topbar title="AI Key Data" subtitle="시장 모니터링 · Demand / 수익성 / 매크로" />

      <div className="min-h-0 flex-1">
        <div className="grid h-full grid-cols-1 lg:grid-rows-3">
          {/* ── 1행 · Demand ─────────────────────────────────────────────── */}
          <CategoryBox label="Demand" sub="AI 를 얼마나 쓰는가 — 토큰 · CLI · 확장 · 툴콜 강도 · 조달">
            {/* OpenRouter 토큰 / npm 다운로드 / VS Code 설치 3탭을 카드가 자체로 돈다. */}
            <AiUsageCard colSpan={3} />
            {demandTab === "tool" ? (
              <ToolCallingCard colSpan={3} tabs={demandChips} />
            ) : (
              <EpochFundingCard colSpan={3} tabs={demandChips} />
            )}
          </CategoryBox>

          {/* ── 2행 · 수익성 ─────────────────────────────────────────────── */}
          <CategoryBox label="수익성" sub="얼마를 벌고 무엇이 깔렸는가 — ARR · 칩 공급 · 데이터센터 · 임대단가">
            {/* AI 기업(매출·펀딩) / 칩 공급(H100e 누적·분기신규) / 데이터센터 3탭. */}
            <EpochCard />
            <ComputeIndexCard />
          </CategoryBox>

          {/* ── 3행 · 매크로 ─────────────────────────────────────────────── */}
          <CategoryBox label="매크로" sub="조달 조건 — 정책금리 · 채권 발행 · 물가 · 유가 · 고용">
            {macroTab === "rates" ? (
              // ★이 탭만 슬롯(3칸)을 2열로 갈라 카드 두 장을 나란히 놓는다.
              //   카드의 `lg:col-span-1` 이 이 **하위 그리드**의 1열을 뜻하게 되므로
              //   카드 컴포넌트는 손대지 않고 폭만 반씩 나눠 갖는다.
              <div className="grid min-h-0 grid-cols-1 gap-1.5 md:grid-cols-2 lg:col-span-3">
                <PolicyRateCard colSpan={1} tabs={macroChips} />
                <RateChartCard
                  topic="fomc_prob"
                  title="FOMC 내재확률"
                  sub="CME FedWatch 일별"
                  chartKeys={["prob"]}
                  digits={1}
                  suffix="%"
                  colSpan={1}
                />
              </div>
            ) : macroTab === "bonds" ? (
              <BondIssuanceCard colSpan={3} tabs={macroChips} />
            ) : (
              <RateChartCard
                topic="adp"
                title="ADP 민간고용"
                sub="월별 증감 · 12M 평균 (천명)"
                chartKeys={["chg", "ma12"]}
                digits={0}
                colSpan={3}
                tabs={macroChips}
              />
            )}

            {priceTab === "inflation" ? (
              <RateChartCard
                topic="inflation"
                title="미국 인플레이션 지표"
                sub="CPI YoY · 클리블랜드 · 1Y 스왑 · 트루플레이션"
                chartKeys={["cpi", "cleveland", "swap1y", "truflation"]}
                digits={2}
                suffix="%"
                colSpan={3}
                tabs={priceChips}
              />
            ) : (
              <RateChartCard
                topic="wti"
                title="WTI 유가"
                sub="근월 · 6개월 · 12개월 (스프레드는 헤더)"
                chartKeys={["cl1", "cl6", "cl12"]}
                statKeys={["spread"]}
                digits={2}
                colSpan={3}
                tabs={priceChips}
              />
            )}
          </CategoryBox>
        </div>
      </div>
    </div>
  );
}
