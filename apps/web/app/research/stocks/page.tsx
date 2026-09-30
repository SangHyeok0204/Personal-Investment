"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StubCard } from "@/components/stub";
import { CoveragePanel } from "@/components/research/coverage-panel";

// 종목 리서치 — 종목 하나에 대해 내가 아는 것을 모아 두는 자리.
// 보유 종목 화면(/portfolio/holdings)이 "얼마"를 본다면, 여기는 "왜"를 본다.

export default function StockResearchPage() {
  return (
    <>
      <Topbar
        title="종목 단위 리서치"
        subtitle="종목별 노트 · 투자 아이디어"
        showAccountContext={false}
      />
      <PageContainer wide>
        <CoveragePanel kind="stocks" />
        <StubCard title="노트에 담을 것">
          <PlannedList
            items={[
              "투자 논거 한 문장",
              "논거가 깨지는 조건(무엇이 확인되면 판다)을 같이 적는다",
              "실적 추이와 밸류에이션은 자동으로 붙이고, 판단만 직접 쓴다",
              "관련 자료(리서치·영상)를 종목에 연결",
              "보유 종목은 자동으로 목록에 오른다",
            ]}
          />
        </StubCard>
      </PageContainer>
    </>
  );
}
