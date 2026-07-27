"use client";

import { useEffect, useState } from "react";
import { CalendarDays, Clock, Menu, Search, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { MoversTicker } from "@/components/movers-ticker";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면 — 5박스 레이아웃 골격 (웹페이지 디자인 시안 사본.pdf).
// GE 하우스 스타일(그레이 캔버스 + 흰색 카드 + 블루 포인트)로 구현한 빈 골격이며,
// 각 박스의 콘텐츠 연동은 다음 단계다.
// ─────────────────────────────────────────────────────────────────────────────

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

function formatDate(d: Date) {
  return {
    year: String(d.getFullYear()),
    text: `${d.getMonth() + 1}월 ${d.getDate()}일, ${WEEKDAYS[d.getDay()]}요일`,
  };
}

function formatClock(d: Date) {
  let hour = d.getHours();
  const ampm = hour < 12 ? "오전" : "오후";
  hour %= 12;
  if (hour === 0) hour = 12;
  const minute = String(d.getMinutes()).padStart(2, "0");
  return `${ampm} ${hour}:${minute}`;
}

/** 마운트 후에만 시계를 채워 SSR/CSR 불일치를 피한다. */
function useNow() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function HomePage() {
  const now = useNow();
  const date = now ? formatDate(now) : null;
  const clock = now ? formatClock(now) : "—";

  return (
    <div className="flex min-h-screen flex-col gap-4 p-4 xl:gap-5 xl:p-5">
      {/* 상단 헤더 */}
      <header className="flex h-14 shrink-0 items-center gap-4 rounded-2xl border border-hairline bg-canvas px-5 shadow-card">
        <Menu className="h-5 w-5 text-ink-muted" />
        <div className="flex-1" />
        <button
          type="button"
          onClick={() =>
            window.dispatchEvent(new CustomEvent("ge:index-alert-test"))
          }
          className="rounded-lg border border-hairline bg-white px-3 py-1.5 text-xs font-bold text-ink-secondary transition-colors hover:bg-canvas-soft"
        >
          테스트
        </button>
        <button
          type="button"
          className="rounded-lg border border-[#e8735c] bg-white px-3 py-1.5 text-xs font-bold text-[#e8735c] transition-colors hover:bg-[#e8735c]/[0.06]"
        >
          로그아웃
        </button>
        <span className="text-[15px] text-ge-navy">
          안녕하세요. <b className="font-extrabold">홍길동님</b>
        </span>
        <span className="relative flex h-10 w-10 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-ge-main to-ge-point shadow-[0_4px_12px_rgba(70,105,170,0.25)]">
          <User className="h-6 w-6 text-white" />
          <span className="absolute bottom-0.5 right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400" />
        </span>
      </header>

      {/* Top bar 바로 아래 — 급등락 전광판 (우→좌 마퀴, 움직임 없으면 미표시) */}
      <MoversTicker />

      {/* 본문: 좌측 박스 영역 + 우측 위젯 레일 */}
      <div className="flex min-h-0 flex-1 gap-4 xl:gap-5">
        {/* 좌측 — 상단 2박스 + 하단 2박스 (크기 상이) */}
        <div className="flex min-w-0 flex-1 flex-col gap-4 xl:gap-5">
          <div className="grid h-[150px] shrink-0 grid-cols-2 gap-4 xl:gap-5">
            <Box tone="blue" label="시장 요약" />
            <Box tone="plain" label="주요 지표" />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 xl:gap-5">
            <Box tone="plain" label="모니터링 A" />
            <Box tone="plain" label="모니터링 B" />
          </div>
        </div>

        {/* 우측 — 검색 / 날짜 / 시간 + 세로 박스 */}
        <aside className="flex w-[236px] shrink-0 flex-col gap-4">
          <div className="flex h-11 shrink-0 items-center gap-2 rounded-xl border border-hairline bg-canvas px-3.5 shadow-card">
            <Search className="h-4 w-4 shrink-0 text-ink-muted" />
            <input
              placeholder="검색"
              className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
            />
            <Menu className="h-4 w-4 shrink-0 text-ink-muted" />
          </div>

          <InfoCard icon={CalendarDays}>
            <div className="text-xs font-extrabold text-ge-point">
              {date?.year ?? "—"}
            </div>
            <div className="text-sm font-extrabold text-ge-navy">
              {date?.text ?? "날짜 확인 중"}
            </div>
          </InfoCard>

          <InfoCard icon={Clock}>
            <div className="text-[15px] font-extrabold text-ge-navy">{clock}</div>
          </InfoCard>

          <Box tone="blue" label="퀀트 스코어보드" className="min-h-0 flex-1" />
          <Box tone="plain" label="바로가기" className="h-[76px] shrink-0" />
        </aside>
      </div>
    </div>
  );
}

/** 콘텐츠 박스 (children 없으면 빈 골격 문구). */
function Box({
  tone,
  label,
  className,
  children,
}: {
  tone: "plain" | "blue";
  label: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-2xl border shadow-card",
        tone === "blue"
          ? "border-ge-line-soft bg-ge-blue-bg"
          : "border-hairline bg-canvas",
        className,
      )}
    >
      <div className="flex items-center gap-2 px-4 pt-4">
        <span className="h-4 w-1.5 rounded-full bg-ge-point" />
        <span className="text-[13px] font-extrabold text-ge-navy">{label}</span>
      </div>
      <div className="flex flex-1 items-center justify-center p-4 text-xs font-semibold text-ink-faint">
        {children ?? "콘텐츠 준비 중"}
      </div>
    </section>
  );
}

/** 검색 아래 날짜/시간 위젯. */
function InfoCard({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <div className="flex shrink-0 items-center gap-3 rounded-xl border border-hairline bg-canvas px-3.5 py-3 shadow-card">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-ge-blue-bg">
        <Icon className="h-[18px] w-[18px] text-ge-point" />
      </span>
      <div className="min-w-0 leading-tight">{children}</div>
    </div>
  );
}
