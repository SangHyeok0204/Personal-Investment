"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  StatRow,
  StatTile,
  StubCard,
  StubTable,
} from "@/components/stub";

export default function HoldingsPage() {
  return (
    <>
      <Topbar title="보유 종목" subtitle="종목별 수량 · 평단 · 손익" />
      <PageContainer wide>
        <NotConnectedBanner what="키움 잔고 조회" />

        <StatRow>
          <StatTile label="보유 종목 수" />
          <StatTile label="총 매입금액" />
          <StatTile label="총 평가금액" />
          <StatTile label="총 수익률" accent="up" />
        </StatRow>

        <StubCard
          title="보유 종목 전체"
          subtitle="국내 · 해외 통합 (통화 환산 후 KRW 기준)"
        >
          <StubTable
            columns={[
              "종목코드",
              "종목명",
              "시장",
              "통화",
              "수량",
              "평단",
              "현재가",
              "매입금액",
              "평가금액",
              "평가손익",
              "수익률",
              "비중",
            ]}
            rows={10}
          />
        </StubCard>
      </PageContainer>
    </>
  );
}
