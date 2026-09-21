"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  StubCard,
  StubTable,
} from "@/components/stub";

export default function OrdersPage() {
  return (
    <>
      <Topbar title="주문 / 미체결" subtitle="당일 주문 상태" />
      <PageContainer wide>
        <NotConnectedBanner what="키움 주문 조회" />

        <div className="grid gap-4 xl:grid-cols-2">
          <StubCard title="미체결" subtitle="정정 · 취소 대상">
            <StubTable
              columns={["주문시각", "종목", "구분", "주문수량", "미체결", "주문가"]}
              rows={5}
            />
          </StubCard>
          <StubCard title="당일 전체 주문" subtitle="체결 · 정정 · 취소 포함">
            <StubTable
              columns={["주문시각", "종목", "구분", "수량", "가격", "상태"]}
              rows={5}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
