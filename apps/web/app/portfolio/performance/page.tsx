import { PerformanceView } from "@/components/performance/performance-view";

// 성과 분석 — 내 자산 › 성과 분석.
//
// ★2026-10-15 사용자 결정: 옛 /performance/{returns,benchmark,analysis,report} 네 화면을
//   이 한 화면(스크롤 + 중복 제거)으로 합쳤다. 옛 주소는 next.config.mjs 의 redirect 로
//   여기 #앵커(#returns · #periods · #report · #drawdown)로 온다. 섹션은 components/performance/.

export default function PortfolioPerformancePage() {
  return <PerformanceView />;
}
