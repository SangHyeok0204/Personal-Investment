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

export default function ReturnsPage() {
  return (
    <>
      <Topbar title="수익률 추이" subtitle="TWR · MWR" />
      <PageContainer wide>
        <NotConnectedBanner what="일별 잔고 스냅샷 + 입출금 내역" />

        <StatRow>
          <StatTile label="YTD" accent="up" />
          <StatTile label="1년" accent="up" />
          <StatTile label="누적" accent="up" />
          <StatTile label="연환산(CAGR)" accent="up" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard
            title="누적 수익률"
            subtitle="TWR — 입출금 영향을 제거한 운용 성과"
          >
            <StubChart height={280} />
          </StubCard>
          <StubCard title="기간별 수익률">
            <StubTable columns={["기간", "TWR", "MWR"]} rows={7} />
          </StubCard>
          <StubCard title="월별 수익률" className="xl:col-span-2">
            <StubChart height={200} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
