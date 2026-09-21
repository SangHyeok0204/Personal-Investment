"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  PlannedList,
  StubCard,
  StubTable,
} from "@/components/stub";

// 매매일지는 API 가 아니라 **내가 쓰는** 화면이다 — 연동 배너를 달지 않는다.
// 체결 내역이 붙으면 각 일지 항목에 실제 체결을 자동으로 물려 준다.
export default function JournalPage() {
  return (
    <>
      <Topbar title="매매일지" subtitle="진입 근거 · 복기 메모" showAccountContext={false} />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard title="일지 목록" subtitle="최근순">
            <StubTable
              columns={["날짜", "종목", "구분", "근거 태그", "결과", "복기"]}
              rows={8}
            />
          </StubCard>
          <StubCard title="이 화면이 할 일">
            <PlannedList
              items={[
                "체결이 생기면 초안 일지를 자동 생성 — 사후 합리화를 줄인다",
                "진입 근거를 태그로 남기고, 태그별 승률을 뒤에서 집계",
                "청산 뒤 복기 미작성 건을 상단에 띄움",
                "차트 스냅샷 첨부",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
