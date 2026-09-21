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

// 입출금은 수익률(MWR/TWR) 계산의 전제다 — 이 데이터가 없으면 성과 분석이 전부 틀어진다.
export default function TransfersPage() {
  return (
    <>
      <Topbar title="입출금" subtitle="납입 · 인출 이력" />
      <PageContainer wide>
        <NotConnectedBanner what="계좌 입출금 내역" />

        <StatRow>
          <StatTile label="총 납입금" hint="원금" />
          <StatTile label="총 인출금" />
          <StatTile label="순납입" />
          <StatTile label="월 평균 납입" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StubCard title="누적 납입 vs 평가금액">
            <StubChart height={240} />
          </StubCard>
          <StubCard title="입출금 내역">
            <StubTable columns={["일자", "계좌", "구분", "금액"]} rows={8} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
