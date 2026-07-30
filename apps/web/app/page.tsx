"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Clock, Menu, RefreshCw, Search, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { getMeetingFile } from "@/lib/api";
import { MoversTicker } from "@/components/movers-ticker";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면 — 5박스 레이아웃 골격 (웹페이지 디자인 시안 사본.pdf).
// GE 하우스 스타일(그레이 캔버스 + 흰색 카드 + 블루 포인트)로 구현한 빈 골격이며,
// 각 박스의 콘텐츠 연동은 다음 단계다.
// ─────────────────────────────────────────────────────────────────────────────

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

// 하단 통합 박스의 원본 — S:\GE\_Team\07_회의자료\글로벌주식운용부 회의 체계.html.
// 회의 마운트(/srv/legacy/meeting) 루트 바로 아래이므로 rel 은 파일명 그대로다.
// 부서에서 이 파일을 직접 고치므로 상단 '회의 체계 갱신' 버튼으로 다시 읽어온다.
const MEETING_DOC = "글로벌주식운용부 회의 체계.html";

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

  // 하단 통합 박스 — 주간 회의 운영 체계 HTML 을 iframe(srcDoc)으로.
  // 회의 마운트(/srv/legacy/meeting) 하위 · 자체완결 HTML · 정적이라 재폴링 안 함.
  // 원본이 바뀌면 상단 '회의 체계 갱신' 버튼(refetch)으로 다시 읽는다.
  const meetingQuery = useQuery({
    queryKey: ["landingMeeting", MEETING_DOC],
    queryFn: () => getMeetingFile(MEETING_DOC),
    staleTime: 10 * 60_000,
  });

  return (
    <div className="flex min-h-screen flex-col gap-4 p-4 xl:gap-5 xl:p-5">
      {/* 상단 헤더 */}
      <header className="flex h-14 shrink-0 items-center gap-4 rounded-2xl border border-hairline bg-canvas px-5 shadow-card">
        <Menu className="h-5 w-5 text-ink-muted" />
        <div className="flex-1" />
        {/* 회의 체계 갱신 — S: 원본(글로벌주식운용부 회의 체계.html)을 다시 읽어
            하단 박스를 최신본으로 교체한다. */}
        <button
          type="button"
          onClick={() => void meetingQuery.refetch()}
          disabled={meetingQuery.isFetching}
          className="flex items-center gap-1.5 rounded-lg border border-hairline bg-white px-3 py-1.5 text-xs font-bold text-ink-secondary transition-colors hover:bg-canvas-soft disabled:opacity-60"
        >
          <RefreshCw
            className={cn(
              "h-3.5 w-3.5",
              meetingQuery.isFetching && "animate-spin",
            )}
          />
          회의 체계 갱신
        </button>
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
        {/* 좌측 — 상단 2박스 + 하단 통합 박스. min-h-0 필수: 없으면 자식(회의 박스)
            콘텐츠 높이가 컬럼을 밀어 페이지가 y축으로 넘친다(flex 높이 봉쇄). */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 xl:gap-5">
          <div className="grid h-[150px] shrink-0 grid-cols-2 gap-4 xl:gap-5">
            <Box tone="blue" label="시장 요약" />
            <Box tone="plain" label="주요 지표" />
          </div>
          {/* 하단 — 모니터링 A/B 통합 박스에 GE 회의 HTML 을 헤더 없이 꽉 채워 렌더.
              sandbox 에서 allow-scripts 를 빼 문서 내장 편집 스크립트(<script id=edit-js>)를
              비활성화 → 수정/저장 버튼·서식 툴바 안 뜨고 정적 리포트만 읽기전용으로 표시. */}
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
            {meetingQuery.data ? (
              <MeetingEmbed html={prepMeetingHtml(meetingQuery.data.html)} />
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center text-xs font-semibold text-ink-faint">
                {meetingQuery.isError
                  ? "회의 자료를 불러오지 못했습니다"
                  : "회의 자료 불러오는 중…"}
              </div>
            )}
          </section>
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

// A4 가로(297mm) @96dpi 픽셀폭 — GE_회의.html 이 A4 landscape 설계라 이 폭으로 렌더.
const A4L_W = 1123;

// 대시보드 렌더용 HTML 가공(S: 원본 파일은 불변): 하단 '글로벌주식운용부 · 주간 회의
// 운영 체계 · 기준일 …' 푸터 div 제거 (2026-07-29 사용자 요청).
function prepMeetingHtml(html: string): string {
  return html.replace(/<div[^>]*class="footer"[^>]*>[\s\S]*?<\/div>/i, "");
}

// 회의 HTML 을 박스 가로폭에 꽉 맞춰(fit-to-width) 좌우 여백 없이 렌더한다. 문서를
// 고정폭(A4 가로)으로 렌더한 뒤 박스 실폭/A4폭 배율로 transform scale. 세로가 넘치면
// 박스 안에서만 스크롤(페이지는 좌측 컬럼 min-h-0 봉쇄로 한 화면 유지). 스케일된
// 래퍼(=시각 크기)로 스크롤 영역을 정확히 잡는다(transform 만으론 안 생김). 실제
// 콘텐츠 높이는 same-origin contentDocument 로 측정.
function MeetingEmbed({ html }: { html: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [box, setBox] = useState({ w: A4L_W, h: 700 });
  const [contentH, setContentH] = useState(760);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const upd = () =>
      setBox({ w: el.clientWidth || A4L_W, h: el.clientHeight || 700 });
    upd();
    const ro = new ResizeObserver(upd);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const measure = () => {
    const doc = frameRef.current?.contentDocument;
    if (!doc) return;
    const h = Math.max(
      doc.documentElement?.scrollHeight ?? 0,
      doc.body?.scrollHeight ?? 0,
    );
    if (h > 0) setContentH(h);
  };
  const onLoad = () => {
    measure();
    window.setTimeout(measure, 400); // 웹폰트 로드 후 리플로우 재측정
  };
  // 가로폭을 꽉 채운다(좌우 여백 제거) — 박스 실폭/A4폭 배율. 세로가 넘치면 박스
  // 안에서만 스크롤(overflow-y-auto), 짧으면 하단은 문서 배경(흰색). 페이지는 flex
  // 봉쇄(좌측 컬럼 min-h-0)로 한 화면 유지되고 이 박스만 내부 스크롤한다.
  const scale = box.w / A4L_W;
  return (
    <div
      ref={boxRef}
      className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden bg-white"
    >
      <div style={{ width: box.w, height: contentH * scale }}>
        <iframe
          ref={frameRef}
          title="GE 회의"
          srcDoc={html}
          sandbox="allow-same-origin"
          scrolling="no"
          onLoad={onLoad}
          style={{
            width: A4L_W,
            height: contentH,
            transform: `scale(${scale})`,
            transformOrigin: "0 0",
            border: 0,
            display: "block",
          }}
        />
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
