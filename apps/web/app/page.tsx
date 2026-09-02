"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Menu, RefreshCw, User } from "lucide-react";
import { getMeetingFile } from "@/lib/api";
import { useSidebar } from "@/components/layout/sidebar-context";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면 — 회의 마운트(S:\GE\_Team\07_회의자료)의 문서 두 장을 위아래로 붙인
// 단일 컬럼 — 주간 회의 운영 체계 · 미국주식 리서치 분장표.
// ★2026-09-01 급등락 전광판 띠 · 상단 2박스(시장 요약/주요 지표) · 우측 위젯 레일(236px)
//   을 걷어내 문서 폭을 최대로 확보(사용자 요청). 빈 골격이던 Box/InfoCard 와 날짜·시계
//   헬퍼도 쓰는 곳이 없어져 같이 지웠다 — 되살릴 일이 있으면 git 이력에서.
// ─────────────────────────────────────────────────────────────────────────────

// 하단 통합 박스의 원본 — S:\GE\_Team\07_회의자료\글로벌주식운용부 회의 체계_수정본.html.
// 회의 마운트(/srv/legacy/meeting) 루트 바로 아래이므로 rel 은 파일명 그대로다.
// 부서에서 이 파일을 직접 고치므로 상단 '회의 체계 갱신' 버튼으로 다시 읽어온다.
// ★2026-08-27 `_수정본` 으로 교체(구본 `글로벌주식운용부 회의 체계.html` 은 7/29 이후
//   갱신이 없다 — 부서가 수정본을 따로 만들어 그쪽만 고치고 있다). 파일명이 또 바뀌면
//   여기 한 줄만 고치면 된다 — 갱신 버튼도 이 상수를 그대로 다시 읽는다.
const MEETING_DOC = "글로벌주식운용부 회의 체계_수정본.html";

// 회의 체계 바로 아래에 붙는 두 번째 문서 — 미국주식 리서치 분장표(A4 가로 1p).
// 같은 회의 마운트 루트에 있고, 상단 '회의 체계 갱신' 버튼이 이 문서도 같이 다시 읽는다.
const RESEARCH_DOC = "글로벌주식운용부_리서치분장.html";

export default function HomePage() {
  const sidebar = useSidebar();

  // 하단 통합 박스 — 주간 회의 운영 체계 HTML 을 iframe(srcDoc)으로.
  // 회의 마운트(/srv/legacy/meeting) 하위 · 자체완결 HTML · 정적이라 재폴링 안 함.
  // 원본이 바뀌면 상단 '회의 체계 갱신' 버튼(refetch)으로 다시 읽는다.
  const meetingQuery = useQuery({
    queryKey: ["landingMeeting", MEETING_DOC],
    queryFn: () => getMeetingFile(MEETING_DOC),
    staleTime: 10 * 60_000,
  });

  // 회의 체계 아래 문서 — 읽는 방식은 위와 같다(같은 마운트 · 같은 엔드포인트).
  const researchQuery = useQuery({
    queryKey: ["landingResearch", RESEARCH_DOC],
    queryFn: () => getMeetingFile(RESEARCH_DOC),
    staleTime: 10 * 60_000,
  });

  const docsFetching = meetingQuery.isFetching || researchQuery.isFetching;

  return (
    <div className="flex min-h-screen flex-col gap-4 p-4 xl:gap-5 xl:p-5">
      {/* 상단 헤더 */}
      <header className="flex h-14 shrink-0 items-center gap-4 rounded-2xl border border-hairline bg-canvas px-5 shadow-card">
        {/* 사이드바 접기/펼치기 — 이 화면은 Topbar 를 안 쓰고 자체 헤더라 따로 잇는다.
            (아래 검색창 오른쪽 Menu 아이콘은 장식이라 그대로 둔다.) */}
        <button
          type="button"
          onClick={sidebar.toggle}
          aria-label={sidebar.collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          aria-expanded={!sidebar.collapsed}
          title={sidebar.collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          className="-m-1.5 shrink-0 rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ink"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex-1" />
        {/* 회의 체계 갱신 — 아래 두 문서(MEETING_DOC · RESEARCH_DOC)를 **같은 경로**로
            다시 읽어 최신본으로 교체한다. refetch 는 staleTime 을 무시하고 항상 네트워크를
            타고, getMeetingFile 은 `cache: "no-store"`, collector 는 캐시 없이 그때그때
            디스크를 읽는다 — 세 층이 다 뚫려 있어야 부서가 방금 고친 내용이 바로 올라온다. */}
        <button
          type="button"
          onClick={() => {
            void meetingQuery.refetch();
            void researchQuery.refetch();
          }}
          disabled={docsFetching}
          className="flex items-center gap-1.5 rounded-lg border border-hairline bg-white px-3 py-1.5 text-xs font-bold text-ink-secondary transition-colors hover:bg-canvas-soft disabled:opacity-60"
        >
          <RefreshCw
            className={cn(
              "h-3.5 w-3.5",
              docsFetching && "animate-spin",
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

      {/* 본문 — 회의 마운트의 문서 두 장을 위아래로. 문서는 박스 폭에 맞춰 확대되므로
          두 장을 합치면 한 화면을 넘는다: 각 박스는 내용 높이 그대로 두고 페이지가
          스크롤한다(박스 안에서만 스크롤하면 문서가 반씩 잘려 읽기 나쁘다). */}
      <div className="flex min-w-0 flex-1 flex-col gap-4 xl:gap-5">
        {/* 주간 회의 운영 체계 */}
        <section className="flex flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
          {meetingQuery.data ? (
            <DocEmbed
              title="GE 회의"
              html={prepMeetingHtml(meetingQuery.data.html)}
            />
          ) : (
            <div className="flex h-40 items-center justify-center text-xs font-semibold text-ink-faint">
              {meetingQuery.isError
                ? "회의 자료를 불러오지 못했습니다"
                : "회의 자료 불러오는 중…"}
            </div>
          )}
        </section>

        {/* 그 아래 — 미국주식 리서치 분장표 */}
        <section className="flex flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
          {researchQuery.data ? (
            <DocEmbed
              title="리서치 분장표"
              html={prepResearchHtml(researchQuery.data.html)}
            />
          ) : (
            <div className="flex h-40 items-center justify-center text-xs font-semibold text-ink-faint">
              {researchQuery.isError
                ? "리서치 분장표를 불러오지 못했습니다"
                : "리서치 분장표 불러오는 중…"}
            </div>
          )}
        </section>
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

// 리서치 분장표도 원본은 그대로 두고 렌더본만 손댄다. 이 문서는 단독으로 열릴 때를
// 전제로 회색 바닥(html background) 위에 그림자 얹은 종이처럼 그려진다 — 대시보드 카드
// 안에서는 그 회색 액자가 이중 테두리로 보이므로 배경·바깥 여백·그림자만 눌러 꽉 채운다.
function prepResearchHtml(html: string): string {
  const override =
    "<style>html{background:#fff!important}" +
    ".sheet{margin:0 auto!important;box-shadow:none!important}</style>";
  return html.replace(/<\/head>/i, override + "</head>");
}

// A4 가로 문서를 박스 가로폭에 꽉 맞춰(fit-to-width) 좌우 여백 없이 렌더한다. 문서를
// 고정폭(A4 가로)으로 렌더한 뒤 박스 실폭/A4폭 배율로 transform scale 하고, 스케일된
// 래퍼가 그 시각 높이를 그대로 차지한다(transform 만으론 레이아웃 높이가 안 생긴다).
// 실제 콘텐츠 높이는 same-origin contentDocument 로 측정.
// sandbox 에서 allow-scripts 를 빼 문서 내장 스크립트를 비활성화 — 편집/저장 바나 서식
// 툴바 없이 정적 리포트로만 읽힌다(편집은 원본 파일을 직접 열어서).
function DocEmbed({ title, html }: { title: string; html: string }) {
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
  // 가로폭을 꽉 채운다(좌우 여백 제거) — 박스 실폭/A4폭 배율. 세로는 잘라내지 않고
  // 스케일된 높이를 그대로 차지하므로, 넘치는 만큼은 페이지가 스크롤한다.
  const scale = box.w / A4L_W;
  return (
    <div ref={boxRef} className="w-full overflow-x-hidden bg-white">
      <div style={{ width: box.w, height: contentH * scale }}>
        <iframe
          ref={frameRef}
          title={title}
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

