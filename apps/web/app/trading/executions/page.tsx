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

export default function ExecutionsPage() {
  return (
    <>
      <Topbar title="체결 내역" subtitle="일자별 매수 · 매도 체결" />
      <PageContainer wide>
        <NotConnectedBanner what="키움 체결 조회" />

        <StatRow>
          <StatTile label="이번 달 매수" />
          <StatTile label="이번 달 매도" />
          <StatTile label="체결 건수" />
          <StatTile label="거래비용" hint="수수료 + 세금" />
        </StatRow>

        <StubCard title="체결 목록" subtitle="최근순">
          <StubTable
            columns={[
              "체결일시",
              "계좌",
              "종목",
              "구분",
              "수량",
              "단가",
              "체결금액",
              "수수료",
              "세금",
            ]}
            rows={12}
          />
        </StubCard>
      </PageContainer>
    </>
  );
}
