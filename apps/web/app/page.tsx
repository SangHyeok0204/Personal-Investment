"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
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

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면 — "오늘".
//
// ★2026-09-21 개조: 원본은 회의 마운트(S:\GE\_Team\07_회의자료)의 HTML 문서 두 장을
//   iframe 으로 붙이던 팀 대시보드 홈이었다. 개인 계좌 기준으로 바꾸면서 통째로
//   교체했다 — 개인 대시보드의 첫 화면이 답해야 할 질문은 "내 자산이 지금 얼마고,
//   오늘 뭐가 움직였고, 내가 볼 게 뭐냐" 세 가지다.
//   (회의 문서 뷰어는 /meeting 에 그대로 남아 있다.)
//
// 여기 숫자는 전부 비어 있다 — 키움 계좌 API 가 붙는 순간 StatRow 와 아래 카드가
// 실데이터로 바뀐다. 자세한 건 /portfolio.
// ─────────────────────────────────────────────────────────────────────────────

function useToday() {
  // 서버/클라이언트 시각 차이로 hydration 이 깨지지 않게 마운트 후에만 찍는다.
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    setText(
      new Date().toLocaleDateString("ko-KR", {
        year: "numeric",
        month: "long",
        day: "numeric",
        weekday: "long",
      }),
    );
  }, []);
  return text;
}

/** 다른 화면으로 넘기는 얕은 카드 — 홈에서 깊은 화면으로 가는 길만 만든다. */
function JumpCard({
  href,
  title,
  desc,
}: {
  href: string;
  title: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-xl border border-hairline bg-canvas px-4 py-3 shadow-card transition-colors hover:bg-ge-blue-bg"
    >
      <div className="min-w-0">
        <div className="text-[13px] font-extrabold text-ge-navy">{title}</div>
        <div className="mt-0.5 text-[11px] font-medium text-ink-faint">
          {desc}
        </div>
      </div>
      <ArrowRight className="ml-auto h-4 w-4 shrink-0 text-ge-point opacity-0 transition-opacity group-hover:opacity-100" />
    </Link>
  );
}

export default function HomePage() {
  const today = useToday();

  return (
    <>
      <Topbar title="오늘" subtitle={today ?? "\u00a0"} />
      <PageContainer wide>
        <NotConnectedBanner what="키움 계좌 API" />

        <StatRow>
          <StatTile label="총 평가금액" hint="전체 계좌 합산" />
          <StatTile label="당일 손익" hint="전일 종가 대비" accent="up" />
          <StatTile label="평가손익" hint="매입원가 대비" accent="up" />
          <StatTile label="예수금" hint="주문 가능 금액" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
          <StubCard title="자산 추이" subtitle="최근 3개월">
            <StubChart height={240} />
          </StubCard>

          <StubCard title="오늘 내 종목" subtitle="보유 종목 등락">
            <StubTable
              columns={["종목", "현재가", "등락률", "평가손익"]}
              rows={6}
            />
          </StubCard>

          <StubCard title="오늘 시장" subtitle="지수 · 환율 · 금리">
            <StubTable columns={["지표", "현재", "전일대비"]} rows={6} />
          </StubCard>

          <StubCard title="바로 가기">
            <div className="grid gap-2.5">
              <JumpCard
                href="/portfolio"
                title="자산 현황"
                desc="보유 종목 · 평가손익 · 배분"
              />
              <JumpCard
                href="/stock-monitor"
                title="자산 가격/수익률"
                desc="시장·지수 — 이미 실데이터가 붙어 있음"
              />
              <JumpCard
                href="/macro"
                title="매크로"
                desc="금리 · 환율 · 원자재"
              />
              <JumpCard
                href="/settings/connections"
                title="계좌 연동"
                desc="키움 · 토스 API 키 등록"
              />
            </div>
          </StubCard>

          <StubCard title="다음 할 일" className="xl:col-span-2">
            <PlannedList
              items={[
                "키움 OpenAPI 키 발급 → /settings/connections 에서 등록",
                "잔고·체결 수집 배치 붙이기 → 이 화면의 숫자가 살아난다",
                "일별 잔고 스냅샷 적재 → 자산 추이 · 수익률(TWR) 계산의 전제",
                "입출금 내역 확보 → 성과 분석이 원금 대비로 정확해진다",
                "토스 계좌 합산 (DailyPriceAgent 의 toss 수집기 재사용)",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
