"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  PlannedList,
  StubCard,
  StubTable,
} from "@/components/stub";

export default function AccountsPage() {
  return (
    <>
      <Topbar title="계좌별 잔고" subtitle="키움 · 토스 · 연금 합산" />
      <PageContainer wide>
        <NotConnectedBanner what="증권사 계좌 연동" />

        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard title="계좌 목록" subtitle="증권사별 평가금액과 비중">
            <StubTable
              columns={[
                "증권사",
                "계좌",
                "구분",
                "예수금",
                "평가금액",
                "평가손익",
                "비중",
                "동기화",
              ]}
              rows={5}
            />
          </StubCard>

          <StubCard title="연동 대상">
            <PlannedList
              items={[
                "키움증권 — 주계좌 (REST OpenAPI)",
                "키움증권 — ISA / 연금저축",
                "토스증권 — 계좌 연동(시세는 이미 토스 Open API 사용 중)",
                "은행 예적금 — 수기 입력 또는 오픈뱅킹",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
