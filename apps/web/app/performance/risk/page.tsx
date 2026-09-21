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

export default function RiskPage() {
  return (
    <>
      <Topbar title="리스크 지표" subtitle="변동성 · MDD · 샤프" />
      <PageContainer wide>
        <NotConnectedBanner what="일별 수익률 시계열" />

        <StatRow>
          <StatTile label="연환산 변동성" />
          <StatTile label="최대낙폭 (MDD)" accent="down" />
          <StatTile label="샤프 지수" />
          <StatTile label="소르티노" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="낙폭(Drawdown) 추이">
            <StubChart height={240} />
          </StubCard>
          <StubCard title="집중도" subtitle="상위 종목 비중 · 허핀달 지수">
            <StubTable columns={["지표", "값", "경고선"]} rows={6} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
