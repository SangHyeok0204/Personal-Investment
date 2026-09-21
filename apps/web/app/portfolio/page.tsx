"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  NotConnectedBanner,
  PlannedList,
  StatRow,
  StatTile,
  StubCard,
  StubChart,
  StubTable,
} from "@/components/stub";

// 개인 대시보드의 1면. 키움 잔고 조회(예수금·평가금액·보유종목)가 붙으면
// 여기 StatTile 4개와 아래 두 카드가 가장 먼저 실데이터로 바뀐다.
export default function PortfolioPage() {
  return (
    <>
      <Topbar title="자산 현황" subtitle="전체 계좌 합산 · 실시간 평가" />
      <PageContainer wide>
        <NotConnectedBanner what="키움 계좌 API" />

        <StatRow>
          <StatTile label="총 평가금액" hint="보유종목 평가액 + 예수금" />
          <StatTile label="평가손익" hint="매입원가 대비" accent="up" />
          <StatTile label="당일 손익" hint="전일 종가 대비" accent="up" />
          <StatTile label="예수금(D+2)" hint="주문 가능 금액" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="자산 추이" subtitle="총 평가금액 시계열">
            <StubChart height={260} />
          </StubCard>

          <StubCard title="자산 배분" subtitle="자산군 비중">
            <StubChart height={260} />
          </StubCard>

          <StubCard
            title="보유 종목 상위"
            subtitle="평가금액 순"
            className="xl:col-span-2"
          >
            <StubTable
              columns={[
                "종목",
                "수량",
                "평단",
                "현재가",
                "평가금액",
                "평가손익",
                "수익률",
                "비중",
              ]}
              rows={6}
            />
          </StubCard>

          <StubCard title="오늘 체결" subtitle="당일 매매">
            <StubTable columns={["시각", "종목", "구분", "수량", "단가"]} rows={4} />
          </StubCard>

          <StubCard title="연동하면 채워질 것들">
            <PlannedList
              items={[
                "키움 REST 잔고조회 → 보유종목·평단·평가손익",
                "예수금/증거금 → 주문가능금액과 D+2 정산",
                "일별 잔고 스냅샷 적재 → 자산 추이 차트",
                "토스 계좌 합산 → 계좌별/통합 뷰 전환",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
