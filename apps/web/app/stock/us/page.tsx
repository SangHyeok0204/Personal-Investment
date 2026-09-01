"use client";

import { Topbar } from "@/components/layout/topbar";
import { EarningsCard } from "@/components/stock-us/earnings-card";
import { IssueMonitorCard } from "@/components/stock-us/issue-monitor-card";

// [종목 모니터링 · 미국] — 사이드바 '종목 모니터링' 하위 첫 탭(2026-09-01 신설).
//
// 화면 규격(사용자 지시): 좌우 2분할. 왼쪽 어닝 · 오른쪽 이슈 모니터(placeholder).
// 여백 규약은 [종목 모니터]·[AI Key Data] 와 같다 — 바깥 padding 0, 카드끼리 맞붙어
// 화면을 꽉 채우고 경계는 헤어라인 한 줄로만 긋는다(그래서 왼쪽 카드가 border-r 을 갖는다).
//
// 높이를 여기서 확정하는 이유도 같다: 루트 레이아웃이 `min-h-screen` 이라 그대로 두면
// 어닝 목록이 길어질수록 카드가 같이 늘어나 페이지가 통째로 스크롤된다. 스크롤은 카드
// **안쪽**에서 나야 오른쪽 카드와 톱바가 제자리에 남는다.
export default function UsStockMonitorPage() {
  return (
    <div className="flex h-screen flex-col">
      <Topbar
        title="미국"
        subtitle="종목 모니터링 · 어닝 / 이슈"
      />
      <div className="min-h-0 flex-1">
        <div className="grid h-full grid-cols-1 lg:grid-cols-2">
          <EarningsCard />
          <IssueMonitorCard />
        </div>
      </div>
    </div>
  );
}
