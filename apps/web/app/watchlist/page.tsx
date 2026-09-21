"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  PlannedList,
  StubCard,
  StubTable,
} from "@/components/stub";

export default function WatchlistPage() {
  return (
    <>
      <Topbar title="관심종목" subtitle="내가 보는 종목 보드" showAccountContext={false} />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="관심종목" subtitle="가격 · 등락 · 거래대금">
            <StubTable
              columns={[
                "종목",
                "현재가",
                "전일대비",
                "등락률",
                "거래대금",
                "52주 위치",
                "메모",
              ]}
              rows={10}
            />
          </StubCard>
          <StubCard title="붙일 데이터원">
            <PlannedList
              items={[
                "DailyPriceAgent 의 toss 수집기 — 일별 종가·거래대금",
                "키움 시세 API — 장중 현재가",
                "보유 종목은 자동으로 관심종목에 포함",
                "목표가/손절가를 걸어 두고 도달 시 알림",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
