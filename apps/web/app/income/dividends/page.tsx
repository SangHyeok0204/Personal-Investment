"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  StatRow,
  StatTile,
  StubCard,
  StubChart,
  StubTable,
} from "@/components/stub";

export default function DividendsPage() {
  return (
    <>
      <Topbar title="배당 캘린더" subtitle="배당락 · 지급일 · 예상 배당금" />
      <PageContainer wide>
        <NotConnectedBanner what="보유 종목 + 배당 일정 데이터" />

        <StatRow>
          <StatTile label="올해 수령 배당" />
          <StatTile label="예상 연 배당" hint="현 보유 기준" />
          <StatTile label="포트폴리오 배당수익률" />
          <StatTile label="다음 배당락" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StubCard title="월별 배당 수령액">
            <StubChart height={240} />
          </StubCard>
          <StubCard title="다가오는 배당" subtitle="배당락 임박순">
            <StubTable columns={["종목", "배당락", "지급일", "예상액"]} rows={8} />
          </StubCard>
          <StubCard title="배당 수령 내역" className="xl:col-span-2">
            <StubTable
              columns={["지급일", "종목", "주당배당금", "수량", "세전", "세후"]}
              rows={8}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
