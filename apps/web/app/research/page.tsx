"use client";

import Link from "next/link";
import { ArrowRight, FileText, Film, Presentation, Table2 } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StatRow, StatTile, StubCard } from "@/components/stub";

// 리서치 라이브러리 — 내가 이미 가진 자료를 한곳에서 찾는 자리.
//
// ★아직 파일을 읽지 않는다. 수집기가 지정 폴더(예: ~/Downloads/05_리서치)를 훑어
//   제목·종류·날짜·다루는 종목/산업을 뽑아 DB 에 넣으면 이 화면이 그걸 읽는다.
//   지금은 **어떤 서랍이 있는지**만 고정해 둔다 — 실제 폴더 구조를 그대로 옮겼다.

// 사용자 리서치 폴더(05_리서치)의 실제 구획. 수집기가 붙으면 건수가 채워진다.
const SHELVES = [
  { id: "stocks", label: "종목 리서치", desc: "종목 리스트 · 발표 자료", icon: Table2, href: "/research/stocks" },
  { id: "industry", label: "산업 리서치", desc: "반도체 · AI · ESS", icon: FileText, href: "/research/industry" },
  { id: "insight", label: "인사이트", desc: "시장 코멘터리 덱", icon: Presentation },
  { id: "fund", label: "공모펀드/ETF", desc: "사모재간접 · 액티브ETF", icon: FileText },
  { id: "macro", label: "매크로/MP 회의", desc: "시장 전망 · 하우스뷰", icon: FileText },
  { id: "video", label: "영상", desc: "YouTube 자막 · 요약", icon: Film, href: "/research/video" },
];

export default function ResearchLibraryPage() {
  return (
    <>
      <Topbar
        title="리서치 라이브러리"
        subtitle="내가 가진 자료를 한곳에서"
        showAccountContext={false}
      />
      <PageContainer wide>
        <StatRow>
          <StatTile label="자료 수" hint="인덱싱된 문서" />
          <StatTile label="이번 달 추가" />
          <StatTile label="다루는 종목" />
          <StatTile label="미분류" hint="태그가 안 붙은 자료" />
        </StatRow>

        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {SHELVES.map((s) => {
            const Icon = s.icon;
            const inner = (
              <>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ge-blue-bg">
                  <Icon className="h-5 w-5 text-ge-point" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-extrabold text-ge-navy">
                    {s.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] font-medium text-ink-faint">
                    {s.desc}
                  </span>
                </span>
                <span className="shrink-0 text-[12px] font-bold tabular-nums text-ink-faint">
                  —
                </span>
              </>
            );
            const cls =
              "flex items-center gap-3 rounded-2xl border border-hairline bg-canvas px-4 py-3.5 shadow-card transition-colors";
            return s.href ? (
              <Link key={s.id} href={s.href} className={`${cls} hover:bg-ge-blue-bg`}>
                {inner}
              </Link>
            ) : (
              <div key={s.id} className={`${cls} opacity-70`}>
                {inner}
              </div>
            );
          })}
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <StubCard title="최근 추가" subtitle="읽지 않은 자료 먼저">
            <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
              자료 인덱싱이 아직 연결되지 않았습니다
            </div>
          </StubCard>

          <StubCard title="이 화면이 할 일">
            <PlannedList
              items={[
                "지정 폴더를 훑어 pdf·pptx·docx·xlsx 의 제목·날짜·크기를 인덱싱",
                "문서에서 종목코드·산업 키워드를 뽑아 태그로 붙임",
                "보유 종목과 교차 — 내가 가진 종목의 자료를 먼저 띄운다",
                "읽음/안읽음과 한 줄 메모를 남겨 다음에 뭘 볼지 고르게",
                "원문 파일은 옮기지 않는다 — 경로만 들고 열기만 한다",
              ]}
            />
          </StubCard>
        </div>

        <div className="mt-4">
          <Link
            href="/research/industry"
            className="group inline-flex items-center gap-2 text-[13px] font-bold text-ge-point transition-colors hover:text-ge-navy"
          >
            반도체 · AI 산업 리서치로
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </PageContainer>
    </>
  );
}
