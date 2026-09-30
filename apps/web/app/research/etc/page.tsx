"use client";

import Link from "next/link";
import { BookOpen, FileText, Landmark, NotebookPen, UserCheck } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";

// 기타 — 리서치 그룹 3단계 중첩 대신 만든 허브 페이지.
// ★2026-09-27 계획 S1 §12-7/§10 Q2·Q3 — 사용자 결정: 사이드바에 3단계를
//   추가하지 않고 여기 하나로 모은다. 여기 모인 화면은 각자 갈 곳이 애매해서
//   묶었을 뿐 — 오래 이 상태로 두지 않고 정리(통합/삭제) 대상으로 본다.

const LINKS = [
  {
    id: "library",
    label: "리서치 라이브러리",
    desc: "보유 자료 인덱스 (05_리서치 폴더)",
    icon: BookOpen,
    href: "/research",
  },
  {
    id: "industry",
    label: "산업 리서치(구)",
    desc: "반도체·AI 공부 진행도 (밸류체인으로 대체)",
    icon: FileText,
    href: "/research/industry",
  },
  {
    id: "notes",
    label: "학습 노트",
    desc: "반도체·AI 개념 정리",
    icon: NotebookPen,
    href: "/research/notes",
  },
  {
    id: "insiders",
    label: "내부자 거래",
    desc: "보유·관심종목 Form 4 순매수 · 13D",
    icon: UserCheck,
    href: "/research/insiders",
  },
  {
    id: "us-earnings",
    label: "미국 어닝(구)",
    desc: "실적 모니터(/research/earnings)로 대체된 화면",
    icon: Landmark,
    href: "/stock/us",
  },
];

export default function ResearchEtcPage() {
  return (
    <>
      <Topbar
        title="기타"
        subtitle="정리 후보"
        showAccountContext={false}
      />
      <PageContainer wide>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {LINKS.map((l) => {
            const Icon = l.icon;
            return (
              <Link
                key={l.id}
                href={l.href}
                className="flex items-center gap-3 rounded-2xl border border-hairline bg-canvas px-4 py-3.5 shadow-card transition-colors hover:bg-ge-blue-bg"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ge-blue-bg">
                  <Icon className="h-5 w-5 text-ge-point" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-extrabold text-ge-navy">
                    {l.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] font-medium leading-snug text-ink-faint">
                    {l.desc}
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      </PageContainer>
    </>
  );
}
