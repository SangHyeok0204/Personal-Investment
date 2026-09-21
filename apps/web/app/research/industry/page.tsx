"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  DataTable,
  PlannedList,
  StubCard,
  StubChart,
} from "@/components/stub";
import { cn } from "@/lib/utils";

// 산업 리서치 — 당장의 목표는 반도체와 AI다.
//
// 산업을 "공부 진행도"로 관리한다. 자료만 쌓아 두면 읽었는지 안 읽었는지 모르고,
// 아는 것과 모르는 것이 구분되지 않아 다음에 뭘 볼지 못 고른다.

const SECTORS = [
  {
    id: "semi",
    label: "반도체",
    sub: "메모리 사이클 · HBM · 파운드리 · 장비",
    focus: true,
    topics: ["메모리 사이클", "HBM/CoWoS", "파운드리 경쟁", "소부장", "CXMT·중국 굴기"],
  },
  {
    id: "ai",
    label: "AI",
    sub: "컴퓨트 · 모델 · 인프라 · 전력",
    focus: true,
    topics: ["GPU 수급", "데이터센터 CAPEX", "전력·냉각", "추론 비용", "AI 수익화"],
  },
  { id: "battery", label: "2차전지", sub: "셀 · 소재 · 전방 수요", topics: [] },
  { id: "ess", label: "ESS", sub: "전력저장 · 정책", topics: [] },
  { id: "defense", label: "방산", sub: "수출 사이클", topics: [] },
];

export default function IndustryResearchPage() {
  return (
    <>
      <Topbar
        title="산업 리서치"
        subtitle="반도체 · AI 우선"
        showAccountContext={false}
      />
      <PageContainer wide>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {SECTORS.map((s) => (
            <div
              key={s.id}
              className={cn(
                "rounded-2xl border bg-canvas p-4 shadow-card",
                s.focus ? "border-ge-point/40" : "border-hairline opacity-75",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-extrabold text-ge-navy">
                  {s.label}
                </span>
                {s.focus && (
                  <span className="rounded-full bg-ge-blue-bg px-2 py-0.5 text-[10px] font-bold text-ge-point">
                    집중
                  </span>
                )}
                <span className="ml-auto text-[11px] font-bold text-ink-faint">
                  자료 —
                </span>
              </div>
              <p className="mt-1 text-[11px] font-medium text-ink-faint">{s.sub}</p>

              {s.topics.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.topics.map((t) => (
                    <span
                      key={t}
                      className="rounded-lg border border-hairline bg-canvas-soft px-2 py-1 text-[10px] font-bold text-ink-secondary"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}

              {/* 공부 진행도 — 자료 수가 아니라 "이해했는가"를 센다. */}
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
                <div className="h-full w-0 rounded-full bg-ge-point" />
              </div>
              <p className="mt-1.5 text-[10px] font-semibold text-ink-faint">
                학습 진행도 — 노트가 쌓이면 채워집니다
              </p>
            </div>
          ))}
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StubCard title="산업 자료" subtitle="보고서 · 세미나 · 덱">
            <DataTable
              columns={["제목", "산업", "출처", "날짜", "상태"]}
              align={["left", "left", "left", "right", "right"]}
              empty="자료 인덱싱이 아직 연결되지 않았습니다"
            >
              {null}
            </DataTable>
          </StubCard>

          <StubCard title="내 포지션과의 연결">
            <PlannedList
              items={[
                "보유 종목의 섹터를 산업에 매핑 — 내가 돈을 넣은 산업부터 공부",
                "섹터 비중 대비 학습 진행도가 낮은 곳을 상단에 띄움",
                "산업 자료에서 언급된 종목을 관심종목으로 옮기기",
              ]}
            />
          </StubCard>

          <StubCard title="산업 지표" subtitle="사이클 판단용" className="xl:col-span-2">
            <StubChart height={200} note="DRAM 고정가 · 설비투자 · 수출액 등 연동 예정" />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
