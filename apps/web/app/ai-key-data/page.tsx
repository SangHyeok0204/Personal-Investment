"use client";

import { useState } from "react";
import { Topbar } from "@/components/layout/topbar";
import { AiUsageCard } from "@/components/ai-key-data/ai-usage-card";
import { BondIssuanceCard } from "@/components/ai-key-data/bond-issuance-card";
import { ComputeIndexCard } from "@/components/ai-key-data/compute-index-card";
import { EpochCard } from "@/components/ai-key-data/epoch-card";
import { PolicyRateCard } from "@/components/ai-key-data/policy-rate-card";
import { RateChartCard } from "@/components/ai-key-data/rate-chart-card";
import { TabChips } from "@/components/ai-key-data/tab-chips";

// [AI Key Data] — 시장 모니터링 하위 (iNAV·WRAP·LP평가·종목 모니터와 동급, 2026-08-27).
// AI 밸류체인을 재는 지표들을 모으는 자리다.
//
// 화면 규격(사용자 지시): **종목 모니터와 같은 가로6×세로2 = 12등분, 스크롤 없이
// 한 화면**. 카드 폭은 내용 무게에 맞춰 갈랐다.
//
// ★★2026-08-28(2차) 사용자 지시 — 하위 페이지 `/ai-key-data/epoch` 를 없애고 그
//   내용(Epoch AI)을 메인으로 편입했다. 12칸은 그대로인데 카드가 늘었으므로,
//   **성격이 붙는 카드끼리 탭으로 접어** 자리를 만들었다:
//   · 매크로(2칸)   = 정책금리 · 채권 발행 [· ADP · FOMC확률]
//   · 물가·유가(2칸) = 미국 인플레이션 · WTI 유가
//   ADP·FOMC 내재확률은 없어지는 하위 페이지에 살던 카드다 — 지울 이유가 없어
//   매크로 탭에 같이 넣었다(칸을 더 쓰지 않는다).
//
//   1행: 컴퓨팅 지수(3) · Epoch AI(3, 기업/칩/데이터센터 탭)
//   2행: 매크로(2, 4탭) · AI 사용량(2, OpenRouter/npm/VSCode 탭) · 물가·유가(2, 2탭)
//
// ★탭 상태를 **카드가 아니라 이 페이지가 든다** — 한 칸에 서로 다른 컴포넌트를
//   갈아 끼우는 묶음이라 상태가 카드 밖에 있어야 한다(AI 사용량·Epoch 처럼 한
//   컴포넌트 안에서 탭이 도는 경우는 카드가 그대로 들고 있다).
// 금리 4주제는 `RateChartCard` 하나를 설정만 바꿔 재사용한다(원천도 엔드포인트도
// 같은 한 장이라 react-query 가 fetch 를 한 번으로 묶는다).

type MacroTab = "policy" | "bonds" | "adp" | "fomc";
const MACRO_TABS: { key: MacroTab; label: string }[] = [
  { key: "policy", label: "정책금리" },
  { key: "bonds", label: "채권 발행" },
  { key: "adp", label: "ADP 고용" },
  { key: "fomc", label: "FOMC 확률" },
];

type PriceTab = "inflation" | "wti";
const PRICE_TABS: { key: PriceTab; label: string }[] = [
  { key: "inflation", label: "미국 인플레이션" },
  { key: "wti", label: "WTI 유가" },
];

export default function AiKeyDataPage() {
  const [macroTab, setMacroTab] = useState<MacroTab>("policy");
  const [priceTab, setPriceTab] = useState<PriceTab>("inflation");

  const macroChips = <TabChips tabs={MACRO_TABS} value={macroTab} onChange={setMacroTab} />;
  const priceChips = <TabChips tabs={PRICE_TABS} value={priceTab} onChange={setPriceTab} />;

  return (
    // 높이를 여기서 확정한다 — 루트 레이아웃이 min-h-screen 이라 그대로 두면
    // grid-rows-2 가 내용 높이로 커져 12등분이 아니게 되고 페이지가 스크롤된다.
    <div className="flex h-screen flex-col">
      <Topbar title="AI Key Data" subtitle="시장 모니터링 · AI 밸류체인 핵심 지표" />

      {/* ★2026-08-28 사용자 지시로 여백을 걷어냈다 — 카드 사이 16px(gap-4) + 오른쪽·
          아래 24px 를 각각 6px / 8px 로 줄여 화면을 카드로 꽉 채운다. 카드가 늘어난
          만큼 차트에 돌아가는 픽셀이 늘어난다.
          ⚠️공용 PageContainer 를 쓰지 않는다(기본형이 가운데 정렬이라 카드가 밀린다). */}
      <div className="min-h-0 flex-1 pb-2 pr-2">
        <div className="grid h-full grid-cols-1 gap-1.5 lg:grid-cols-6 lg:grid-rows-2">
          {/* ── 1행 ─────────────────────────────────────────────────────── */}
          {/* 컴퓨팅 지수 모니터링 — 세대별 패널 3장이라 이 카드만 3칸이 필요하다. */}
          <ComputeIndexCard />

          {/* Epoch AI — 하위 페이지에서 편입(2026-08-28). 패널이 탭마다 2~3장이라
              폭 3칸이 필요하다. */}
          <EpochCard />

          {/* ── 2행 ─────────────────────────────────────────────────────── */}
          {/* 매크로 4탭 — 한 칸에 카드 넷을 갈아 끼운다. 활성 칩이 곧 카드 이름이라
              카드 안의 제목(h2)은 칩으로 대체된다. */}
          {macroTab === "policy" ? (
            <PolicyRateCard colSpan={2} tabs={macroChips} />
          ) : macroTab === "bonds" ? (
            <BondIssuanceCard tabs={macroChips} />
          ) : macroTab === "adp" ? (
            <RateChartCard
              topic="adp"
              title="ADP 민간고용"
              sub="월별 증감 · 12M 평균 (천명)"
              chartKeys={["chg", "ma12"]}
              digits={0}
              colSpan={2}
              tabs={macroChips}
            />
          ) : (
            <RateChartCard
              topic="fomc_prob"
              title="FOMC 내재확률"
              sub="CME FedWatch 일별"
              chartKeys={["prob"]}
              digits={1}
              suffix="%"
              colSpan={2}
              tabs={macroChips}
            />
          )}

          <AiUsageCard colSpan={2} />

          {priceTab === "inflation" ? (
            <RateChartCard
              topic="inflation"
              title="미국 인플레이션 지표"
              sub="CPI YoY · 클리블랜드 · 1Y 스왑 · 트루플레이션"
              chartKeys={["cpi", "cleveland", "swap1y", "truflation"]}
              digits={2}
              suffix="%"
              colSpan={2}
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
              colSpan={2}
              tabs={priceChips}
            />
          )}
        </div>
      </div>
    </div>
  );
}
