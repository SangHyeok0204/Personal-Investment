"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  StubCard,
  StubChart,
  StubTable,
} from "@/components/stub";

export default function AllocationPage() {
  return (
    <>
      <Topbar title="자산 배분" subtitle="자산군 · 섹터 · 지역 · 통화 비중" />
      <PageContainer wide>
        <NotConnectedBanner what="보유 종목 + 분류 테이블" />

        <div className="grid gap-4 xl:grid-cols-3">
          <StubCard title="자산군" subtitle="주식 · 채권 · 현금 · 대체">
            <StubChart height={220} />
          </StubCard>
          <StubCard title="지역" subtitle="한국 · 미국 · 기타">
            <StubChart height={220} />
          </StubCard>
          <StubCard title="통화" subtitle="KRW · USD 노출">
            <StubChart height={220} />
          </StubCard>

          <StubCard title="섹터 비중" className="xl:col-span-2">
            <StubChart height={240} />
          </StubCard>

          <StubCard title="목표 대비 이격" subtitle="리밸런싱 필요 구간">
            <StubTable columns={["자산군", "현재", "목표", "이격"]} rows={5} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
