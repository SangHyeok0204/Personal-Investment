"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  DataTable,
  PlannedList,
  StubCard,
} from "@/components/stub";

// 종목 리서치 — 종목 하나에 대해 내가 아는 것을 모아 두는 자리.
// 보유 종목 화면(/portfolio/holdings)이 "얼마"를 본다면, 여기는 "왜"를 본다.

export default function StockResearchPage() {
  return (
    <>
      <Topbar
        title="종목 리서치"
        subtitle="종목별 노트 · 투자 아이디어"
        showAccountContext={false}
      />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard title="종목 노트" subtitle="보유 · 관심 종목">
            <DataTable
              columns={["종목", "섹터", "보유", "투자 논거", "자료", "최근 갱신"]}
              align={["left", "left", "right", "left", "right", "right"]}
              empty="아직 작성된 노트가 없습니다"
            >
              {null}
            </DataTable>
          </StubCard>

          <StubCard title="노트에 담을 것">
            <PlannedList
              items={[
                "투자 논거 한 문장 — 길어지면 다시 안 읽는다",
                "논거가 깨지는 조건(무엇이 확인되면 판다)을 같이 적는다",
                "실적 추이와 밸류에이션은 자동으로 붙이고, 판단만 직접 쓴다",
                "관련 자료(리서치·영상)를 종목에 연결",
                "보유 종목은 자동으로 목록에 오른다",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
