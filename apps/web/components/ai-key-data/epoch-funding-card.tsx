"use client";

import { useQuery } from "@tanstack/react-query";
import { getEpochCompanies, type AiSeries, type EpochCompanies } from "@/lib/api";
import { Panel } from "@/components/ai-key-data/panel";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { cn } from "@/lib/utils";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [AI Key Data] Epoch 펀딩 라운드 — [Demand] 분류 (2026-08-31 신설).
//
// ★사용자 지시로 `EpochCard` 에서 떼어냈다. 펀딩은 "AI 에 돈이 얼마나 들어오는가"라
//   수요 신호이고, 남은 매출·칩·데이터센터는 공급/수익성이다.
// ⚠️**같은 queryKey(`epoch-companies`)를 쓴다.** react-query 가 두 카드의 요청을 하나로
//   묶으므로 쪼갠 대가로 네트워크 요청이 늘지 않는다. 이걸 다른 키로 바꾸면 같은 payload 를
//   두 번 받게 된다.
// ★펀딩은 시계열이 아니라 이벤트 목록(rounds)이라 서버가 `kind: "scatter"` 를 준다 —
//   회사별로 묶어 점을 찍을 뿐, 선으로 잇지 않는다(없는 정밀도를 만들지 않는다).

// 회사별로 묶어 [날짜, equity] 점을 만든다. equity 가 null 인 라운드는 건너뛴다
// (부채만 있는 딜 — 0으로 적으면 "0원에 조달했다"가 된다).
function mapFunding(d: EpochCompanies | undefined): AiSeries[] {
  const g = d?.funding;
  if (!g) return [];
  const byCompany = new Map<string, [string, number][]>();
  for (const r of g.rounds) {
    if (r.equity == null) continue;
    const arr = byCompany.get(r.company) ?? [];
    arr.push([r.date, r.equity]);
    byCompany.set(r.company, arr);
  }
  return [...byCompany.entries()]
    .map(([company, points]) => {
      points.sort((a, b) => a[0].localeCompare(b[0]));
      const total = points.reduce((s, p) => s + p[1], 0);
      return { key: company, label: company, kind: g.kind, last: total, points };
    })
    .sort((a, b) => (b.last ?? 0) - (a.last ?? 0));
}

export function EpochFundingCard({
  colSpan = 3,
  tabs,
}: {
  colSpan?: 1 | 2 | 3;
  tabs?: React.ReactNode;
}) {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const { data, isLoading, isError } = useQuery<EpochCompanies>({
    queryKey: ["epoch-companies"],
    queryFn: getEpochCompanies,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  return (
    <section
      className={cn(
        zoomCls,
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(형제 카드들과 같은 이유).
        colSpan === 1 ? "lg:col-span-1" : colSpan === 2 ? "lg:col-span-2" : "lg:col-span-3",
      )}
    >
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        {tabs ?? (
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">펀딩 라운드</h2>
        )}
        {/* ★탭 칩 바로 옆 한 줄 설명(2026-08-31 사용자 지시). */}
        <span className="shrink-0 text-[13px] font-semibold text-white/90">
          AI 기업이 받은 투자금
        </span>
        <span className="min-w-0 truncate text-[13px] text-white/60">
          회사별 equity · 점 = 개별 라운드
        </span>
        <span className="ml-auto shrink-0 text-[12px] text-white/60">
          {data?.source?.license ?? "CC BY 4.0 — Epoch AI"}
        </span>
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-1 p-1.5 pt-1">
        {isLoading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[13.5px] font-semibold text-ink-muted">
            불러오는 중…
          </div>
        ) : isError ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[13.5px] font-semibold text-rose-600">
            collector 에 못 닿았습니다.
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1">
            <Panel
              title="펀딩 라운드(회사별 누적)"
              series={mapFunding(data)}
              emptyMsg={data?.funding?.note ?? undefined}
            />
          </div>
        )}
        {data?.note ? (
          <div className="shrink-0 truncate px-1 text-[12px] font-semibold text-amber-600">
            {data.note}
          </div>
        ) : null}
      </div>
    </section>
  );
}
