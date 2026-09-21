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

export default function RealizedPnlPage() {
  return (
    <>
      <Topbar title="실현손익" subtitle="매도 확정 기준 손익" />
      <PageContainer wide>
        <NotConnectedBanner what="체결 내역 기반 손익 계산" />

        <StatRow>
          <StatTile label="올해 실현손익" accent="up" />
          <StatTile label="이번 달" accent="up" />
          <StatTile label="승률" hint="익절 건수 / 전체 청산" />
          <StatTile label="손익비" hint="평균이익 / 평균손실" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StubCard title="월별 실현손익">
            <StubChart height={240} />
          </StubCard>
          <StubCard title="종목별 손익 기여" subtitle="상·하위">
            <StubTable columns={["종목", "실현손익", "수익률"]} rows={8} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
