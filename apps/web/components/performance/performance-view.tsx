"use client";

import { useEffect, useRef, useState } from "react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { NotConnectedBanner } from "@/components/stub";
import { PERFORMANCE_SECTIONS, jumpTo } from "./anchors";
import { BridgeSection } from "./bridge-section";
import { ContributionSection } from "./contribution-section";
import { DrawdownSection } from "./drawdown-section";
import { MonthlySection } from "./monthly-section";
import { PeriodsSection } from "./periods-section";
import { useAccountReturn, useAnalytics, useBenchmark, usePerformanceSeries } from "./queries";
import { ReportSection } from "./report-section";
import { ReturnsSection } from "./returns-section";
import { SummaryTiles } from "./summary-tiles";

// 성과 분석 — 내 자산 › 성과 분석(/portfolio/performance). 한 화면을 위에서 아래로 읽는다.
//
// ★2026-10-15 사용자 결정: '성과 분석' 메뉴 그룹(수익률 추이 · 벤치마크 비교 · 성과 분석 ·
//   기간 리포트 네 화면)을 없애고 내 자산 아래 한 화면으로 합쳤다(.omc/plans/performance-merge.md).
//   네 화면이 같은 숫자를 각자 첫 칸에 두고 있었다(내 계좌 수익률이 네 번). 겹친 것은 한 번만,
//   재는 것이 다른 것(금액 vs %, 환율 제외 vs 원화, 정본 vs 참고 TWR)은 둘 다 남겼다.
//   순서: 요약 → 수익률 추이(+벤치마크) → 월별 → 기간별 → 낙폭 → 종목 기여도 → 기간 리포트 →
//   숫자가 이어지는 법.
//
// ⚠️옛 화면들은 PageContainer fit(한 화면 압축, 스크롤 없음)이었다. 넷을 합치면 한 화면에
//   들어갈 수 없다 — 이 화면만 스크롤한다. 대신 위에 섹션 목차를 붙여 두고, 옛 주소는
//   next.config.mjs redirect 로 해당 섹션 #앵커 로 보낸다.
//
// ⚠️조회는 queries.ts 에서 키를 정한다 — 같은 키를 여러 섹션이 써도 한 번만 부른다.

export function PerformanceView() {
  const { connected } = useAccount();
  // 요약 '주가 손익' 칸이 월별 섹션의 월별 표를 연다 — 그래서 상태를 여기 둔다.
  const [monthListOpen, setMonthListOpen] = useState(false);

  // 옛 주소에서 #앵커 로 들어오면, 데이터가 들어와 높이가 정해진 뒤 한 번 더 맞춘다.
  // ⚠️처음 그릴 때는 카드들이 '불러오는 중'이라 키가 작다 — 그때 브라우저가 맞춘 위치는
  //   데이터가 들어오면 밀려난다.
  const perf = usePerformanceSeries();
  const account = useAccountReturn();
  const benchmark = useBenchmark();
  const analytics = useAnalytics();
  const settled =
    !perf.isLoading && !account.isLoading && !benchmark.isLoading && !analytics.isLoading;
  const jumped = useRef(false);
  useEffect(() => {
    if (!settled || jumped.current) return;
    jumped.current = true;
    const hash = window.location.hash.slice(1);
    if (hash) requestAnimationFrame(() => jumpTo(hash, false));
  }, [settled]);

  return (
    <>
      <Topbar
        title="성과 분석"
        subtitle="내 계좌 수익률 · 벤치마크 · 월별 · 위험지표 · 종목 기여도 · 기간 리포트"
      />
      {/* 섹션 목차 — 상단 바(h-16) 바로 아래에 붙는다. 섹션의 scroll-mt-28 이 이 높이까지 뺀다. */}
      <nav className="sticky top-16 z-10 border-b border-hairline bg-canvas/95 px-6 py-2 backdrop-blur">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {PERFORMANCE_SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              onClick={(e) => {
                e.preventDefault();
                history.replaceState(null, "", `#${s.id}`);
                jumpTo(s.id);
              }}
              className="shrink-0 rounded-full border border-hairline bg-canvas px-3 py-1 text-[11px] font-bold text-ink-secondary transition-colors hover:bg-canvas-soft"
            >
              {s.label}
            </a>
          ))}
        </div>
      </nav>
      <PageContainer wide>
        <div className="space-y-5">
          {!connected && <NotConnectedBanner what="계좌 성과" />}
          {/* 옛 성과 분석 화면처럼 — 분석 API 가 실패하면 기간별·낙폭·기여도가 '데이터 없음'으로만 보이지 않게 알린다. */}
          {connected && analytics.isError && <NotConnectedBanner what="성과 분석(위험지표·낙폭·종목 기여도)" />}
          <SummaryTiles
            onMonthList={() => {
              jumpTo("monthly");
              setMonthListOpen(true);
            }}
            onBridge={() => jumpTo("bridge")}
          />
          <ReturnsSection />
          <MonthlySection listOpen={monthListOpen} onListOpenChange={setMonthListOpen} />
          <PeriodsSection />
          <DrawdownSection />
          <ContributionSection />
          <ReportSection />
          <BridgeSection />
        </div>
      </PageContainer>
    </>
  );
}
