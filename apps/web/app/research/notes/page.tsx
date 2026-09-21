"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StubCard } from "@/components/stub";
import { cn } from "@/lib/utils";

// 학습 노트 — 반도체·AI를 "구조부터" 잡는 자리.
//
// 리서치 자료(남이 쓴 것)와 학습 노트(내가 이해한 것)를 나눈다. 자료를 아무리 쌓아도
// 내 말로 다시 쓰지 않으면 남는 게 없고, 다음에 무엇을 모르는지도 알 수 없다.

const TRACKS = [
  {
    id: "semi",
    label: "반도체",
    items: [
      "메모리 사이클 — 무엇이 가격을 움직이나",
      "DRAM vs NAND, 그리고 HBM 이 다른 이유",
      "파운드리 공정 노드와 수율의 경제학",
      "소부장: 노광·식각·증착 어디에 돈이 몰리나",
      "중국 CXMT·YMTC 가 한국에 주는 위협",
    ],
  },
  {
    id: "ai",
    label: "AI",
    items: [
      "학습과 추론의 비용 구조가 다른 점",
      "GPU 수급 — 왜 CoWoS 가 병목인가",
      "데이터센터 CAPEX 를 읽는 법",
      "전력·냉각이 성장의 한계가 되는 지점",
      "AI 수익화: 누가 실제로 돈을 버나",
    ],
  },
];

export default function StudyNotesPage() {
  return (
    <>
      <Topbar
        title="학습 노트"
        subtitle="반도체 · AI 개념 정리"
        showAccountContext={false}
      />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-2">
          {TRACKS.map((t) => (
            <StubCard key={t.id} title={t.label} subtitle="이해 순서">
              <ol className="space-y-2">
                {t.items.map((item, i) => (
                  <li key={item} className="flex items-start gap-3">
                    <span
                      className={cn(
                        "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                        "bg-canvas-soft text-[10px] font-extrabold text-ink-muted",
                      )}
                    >
                      {i + 1}
                    </span>
                    <span className="text-[13px] font-semibold leading-snug text-ink-secondary">
                      {item}
                    </span>
                    <span className="ml-auto shrink-0 text-[10px] font-bold text-ink-faint">
                      미작성
                    </span>
                  </li>
                ))}
              </ol>
            </StubCard>
          ))}

          <StubCard title="노트를 쓰는 규칙" className="xl:col-span-2">
            <PlannedList
              items={[
                "한 노트는 질문 하나에 답한다 — 제목이 질문이 아니면 쪼갠다",
                "내 말로 다시 쓴다. 인용만 모은 노트는 읽은 적이 없는 것과 같다",
                "숫자에는 출처와 기준일을 붙인다 — 반도체는 반년이면 낡는다",
                "모르는 채로 넘어간 것을 노트 끝에 남긴다(다음에 볼 목록이 된다)",
                "관련 종목이 있으면 종목 노트와 연결",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
