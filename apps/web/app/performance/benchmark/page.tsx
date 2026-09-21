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

export default function BenchmarkPage() {
  return (
    <>
      <Topbar title="벤치마크 비교" subtitle="KOSPI · S&P500 대비" />
      <PageContainer wide>
        <NotConnectedBanner what="내 수익률 시계열" />

        <StatRow>
          <StatTile label="초과수익 (vs KOSPI)" accent="up" />
          <StatTile label="초과수익 (vs S&P500)" accent="up" />
          <StatTile label="베타" />
          <StatTile label="상관계수" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="누적 수익률 비교" subtitle="내 포트폴리오 vs 지수">
            <StubChart height={280} />
          </StubCard>
          <StubCard title="구간별 초과수익">
            <StubTable columns={["기간", "내 수익률", "지수", "초과"]} rows={7} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
