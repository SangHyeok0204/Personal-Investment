"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { CHART_MUTED, CHART_PALETTE } from "@/components/charts/donut-chart";
import { PlannedList, StubCard, StubTable } from "@/components/stub";
import { cn } from "@/lib/utils";

// 모델 포트폴리오 · 리밸런싱 — **placeholder**(2026-09-25 사용자 지시).
//
// ★이 화면의 뼈대는 **탑다운**이다. 위 층이 아래 층의 예산을 정한다:
//     ① 투자 정책 → ② 자산군 배분 → ③ 섹터·테마 배분 → ④ 종목 선정 → ⑤ 리밸런싱
//   종목은 맨 마지막에 고른다. 종목부터 사고 비중을 나중에 맞추면 '모델'이 아니라
//   '보유 목록'이 된다.
//
// ⚠️여기 숫자는 전부 **예시**다(실데이터 아님). 화면에 "예시"라고 붙여 둔다 —
//   실데이터처럼 보이면 그 숫자로 판단하게 된다.
//
// 이전 구현(목표 비중 → 주수 계산, /api/v1/portfolio/rebalance)은 git 이력에
// 남아 있다. ⑤ 단계를 붙일 때 그 계산을 되살려 쓰면 된다.

type Node = { label: string; weight: number; muted?: boolean; children?: Node[] };

// 예시 모델. 합이 100 이 되게만 맞춰 둔 값이다.
const EXAMPLE_MODEL: Node[] = [
  {
    label: "주식",
    weight: 70,
    children: [
      { label: "컴퓨팅 인프라", weight: 30 },
      { label: "에너지 인프라", weight: 12 },
      { label: "AI 혁신 산업", weight: 10 },
      { label: "배당·분산", weight: 18 },
    ],
  },
  { label: "실물자산", weight: 10, children: [{ label: "금", weight: 10 }] },
  { label: "가상자산", weight: 5, children: [{ label: "BTC·ETH", weight: 5 }] },
  { label: "채권·현금", weight: 15, muted: true, children: [{ label: "단기채·예수금", weight: 15, muted: true }] },
];

const STEPS = [
  {
    no: 1,
    title: "투자 정책",
    en: "IPS",
    desc: "목표 수익·감내 손실·기간·제약",
  },
  {
    no: 2,
    title: "자산군 배분",
    en: "Strategic AA",
    desc: "주식·실물·가상·채권현금 목표 비중",
  },
  {
    no: 3,
    title: "섹터·테마 배분",
    en: "Sector / Theme",
    desc: "자산군 안에서 AI/Tech 밸류체인 비중",
  },
  {
    no: 4,
    title: "종목 선정",
    en: "Security Selection",
    desc: "유니버스 → 스크리닝 → 점수 → 편입",
  },
  {
    no: 5,
    title: "리밸런싱",
    en: "Model vs Actual",
    desc: "괴리 → 밴드 판정 → 주문 수량",
  },
] as const;

export default function ModelPortfolioPage() {
  const [step, setStep] = useState<number>(2);

  return (
    <>
      <Topbar title="모델 포트폴리오" subtitle="탑다운 배분 · 종목 선정 · 리밸런싱 — 준비 중" />
      <PageContainer wide>
        {/* 1행: 탑다운 단계 — 위 단계가 아래 단계의 예산을 정한다. */}
        <div className="flex shrink-0 items-stretch gap-1.5 overflow-x-auto pb-1">
          {STEPS.map((s, i) => (
            <div key={s.no} className="flex min-w-[170px] flex-1 items-center gap-1.5">
              <button
                type="button"
                onClick={() => setStep(s.no)}
                aria-pressed={step === s.no}
                className={cn(
                  "flex h-full w-full flex-col rounded-2xl border px-3.5 py-3 text-left shadow-card transition-colors",
                  step === s.no
                    ? "border-ge-point bg-ge-blue-bg"
                    : "border-hairline bg-canvas hover:bg-canvas-soft",
                )}
              >
                <span className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-extrabold",
                      step === s.no ? "bg-ge-point text-white" : "bg-canvas-soft text-ink-muted",
                    )}
                  >
                    {s.no}
                  </span>
                  <span className="text-[13px] font-extrabold text-ge-navy">{s.title}</span>
                </span>
                <span className="mt-0.5 pl-7 text-[10px] font-bold uppercase tracking-wide text-ink-faint">
                  {s.en}
                </span>
                <span className="mt-1.5 pl-7 text-[11px] font-semibold leading-snug text-ink-muted">
                  {s.desc}
                </span>
              </button>
              {i < STEPS.length - 1 && (
                <ChevronRight className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden />
              )}
            </div>
          ))}
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          {/* 왼쪽: 모델 트리 — 층마다 막대 한 줄. 아래 층은 위 층 조각 안에서 나뉜다. */}
          <StubCard title="모델 구조" subtitle="100% → 자산군 → 섹터·테마 · 예시 값">
            <ModelTree model={EXAMPLE_MODEL} />
          </StubCard>

          {/* 오른쪽: 선택한 단계의 상세 자리 */}
          <StubCard
            title={`${step}. ${STEPS[step - 1].title}`}
            subtitle={STEPS[step - 1].en}
            action={
              <span className="rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-bold text-white/80">
                준비 중
              </span>
            }
          >
            <StepDetail step={step} />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}

function ModelTree({ model }: { model: Node[] }) {
  const leaves = model.flatMap((n, i) =>
    (n.children ?? []).map((c, j) => ({ ...c, parent: i, idx: j })),
  );
  return (
    <div className="space-y-3">
      <Level label="포트폴리오">
        <Bar segments={[{ label: "전체 100%", weight: 100, color: "#4C2C19" }]} />
      </Level>
      <Level label="자산군">
        <Bar
          segments={model.map((n, i) => ({
            label: `${n.label} ${n.weight}%`,
            weight: n.weight,
            color: n.muted ? CHART_MUTED : CHART_PALETTE[i % CHART_PALETTE.length],
          }))}
        />
      </Level>
      <Level label="섹터·테마">
        <Bar
          segments={leaves.map((c) => ({
            label: `${c.label} ${c.weight}%`,
            weight: c.weight,
            color: c.muted
              ? CHART_MUTED
              : CHART_PALETTE[c.parent % CHART_PALETTE.length],
            // 같은 자산군 안의 조각은 명도로만 갈라 부모가 읽히게 한다.
            opacity: 1 - c.idx * 0.18,
          }))}
        />
      </Level>
      <Level label="종목">
        <div className="flex h-8 items-center justify-center rounded-lg border border-dashed border-ge-line-soft bg-canvas-soft/60 text-[11px] font-bold text-ink-faint">
          ④ 종목 선정 로직이 섹터 예산 안에서 채웁니다
        </div>
      </Level>
    </div>
  );
}

function Level({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[64px_minmax(0,1fr)] items-center gap-2">
      <span className="text-[11px] font-bold text-ink-muted">{label}</span>
      {children}
    </div>
  );
}

function Bar({
  segments,
}: {
  segments: { label: string; weight: number; color: string; opacity?: number }[];
}) {
  return (
    <div className="flex h-8 w-full overflow-hidden rounded-lg">
      {segments.map((s) => (
        <div
          key={s.label}
          title={s.label}
          className="flex min-w-0 items-center justify-center border-r border-white px-1 last:border-r-0"
          style={{ width: `${s.weight}%`, background: s.color, opacity: s.opacity ?? 1 }}
        >
          <span
            className={cn(
              "truncate text-[10px] font-bold",
              s.color === CHART_MUTED ? "text-ink-secondary" : "text-white",
            )}
          >
            {s.label}
          </span>
        </div>
      ))}
    </div>
  );
}

function StepDetail({ step }: { step: number }) {
  switch (step) {
    case 1:
      return (
        <PlannedList
          items={[
            "**목표 수익률**과 **감내 가능한 최대 손실(MDD)** 을 숫자로 적는다",
            "투자 기간 · 추가 납입 계획 · 필요 현금(비상금) 하한",
            "제약: 레버리지 ETF 상한, 단일 종목 상한, 가상자산 상한",
            "벤치마크 선택 — 모델 성과를 무엇과 비교할지",
          ]}
        />
      );
    case 2:
      return (
        <div className="space-y-3">
          <StubTable columns={["자산군", "목표", "허용 밴드", "현재", "괴리"]} rows={4} />
          <PlannedList
            items={[
              "현재 비중은 배분 화면의 **섹터 축(exposure)** 을 자산군으로 묶어 계산",
              "밴드를 벗어난 자산군만 ⑤ 리밸런싱 대상으로 넘긴다",
            ]}
          />
        </div>
      );
    case 3:
      return (
        <div className="space-y-3">
          <StubTable columns={["자산군", "섹터·테마", "목표(자산군 내)", "목표(전체)", "현재"]} rows={4} />
          <PlannedList
            items={[
              "섹터 목표는 **자산군 안에서의 비중**으로 적는다 — 합이 100% 를 넘지 않게",
              "분류 축은 AI/Tech 밸류체인(v3) — 보유 종목·배분 화면과 같은 어휘",
            ]}
          />
        </div>
      );
    case 4:
      return (
        <div className="space-y-3">
          <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {["유니버스", "스크리닝", "점수화", "편입 규칙"].map((t, i) => (
              <li
                key={t}
                className="rounded-xl border border-dashed border-ge-line-soft bg-canvas-soft/60 px-2.5 py-2 text-center"
              >
                <span className="block text-[10px] font-extrabold text-ink-faint">{i + 1}</span>
                <span className="text-[12px] font-bold text-ink-secondary">{t}</span>
              </li>
            ))}
          </ol>
          <PlannedList
            items={[
              "**유니버스**: 섹터별 후보 목록(분류표 4,736 종목 + ETF 대표 노출)",
              "**스크리닝**: 시가총액·유동성·실적 등 통과/탈락 조건",
              "**점수화**: 팩터 가중합 — 규칙과 가중치를 여기서 관리",
              "**편입 규칙**: 섹터당 종목 수, 종목당 상한, 동점 처리",
            ]}
          />
        </div>
      );
    default:
      return (
        <div className="space-y-3">
          <StubTable columns={["종목", "모델", "현재", "괴리", "주문", "수량"]} rows={4} />
          <PlannedList
            items={[
              "트리거: **밴드 이탈**(예: ±3%p) 또는 **정기**(분기) 중 먼저 오는 것",
              "괴리를 주문 수량으로 — 예수금 부족이면 매도부터",
              "주문 전 수수료·세금 추정치를 같이 보여 준다",
            ]}
          />
        </div>
      );
  }
}
