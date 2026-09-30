"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal } from "@/components/ui/modal";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import { CardEmpty, HeaderChip, StubCard } from "@/components/stub";
import {
  getSeasonality,
  getSeasonalityCell,
  type SeasonalityCell,
  type SeasonalityWindow,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 시장 리서치 · 계절성 탭 — "이 달에 과거에는 어땠나".
//
// ★2026-09-27 계획 S4(§3.3): 월별 평균 수익률 매트릭스만 전폭으로 남겼다.
//   상단 타일 4개 · "N월 신호" 카드 · 백테스트 팝업은 뺐다(API 의 signal 필드는 무시).
//
// ★예측 화면이 아니다. 칸은 과거 평균이고, ★ 는 다중검정(FDR 5%)을 통과한 칸이다.
// ⚠️동결 시계열(창업판·IT·커뮤니케이션·경기소비재)은 2026-08 에서 멈췄다 — '갱신 중단' 배지.
//   대용 시계열(CSI300=ASHR, 섹터=SPDR ETF)은 2026-09 부터 ETF 로 이었다 — '대용' 배지.

const WINDOWS: SeasonalityWindow[] = ["전구간", "10년", "5년"];
const GROUPS = [
  { id: "index", label: "지수" },
  { id: "sector", label: "섹터" },
] as const;
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** 평균 수익률 → 칸 색. 상승=bid, 하락=ask, 크기는 |평균| 을 3% 에서 포화. */
function cellStyle(mean: number | null) {
  if (mean == null) return { background: "transparent" };
  const a = Math.min(Math.abs(mean) / 3, 1) * 0.85 + 0.08;
  return {
    background: mean >= 0 ? `rgba(163,58,42,${a})` : `rgba(58,107,150,${a})`,
  };
}

export function SeasonalityTab() {
  const [win, setWin] = useState<SeasonalityWindow>("전구간");
  const [group, setGroup] = useState<"index" | "sector">("index");
  const [picked, setPicked] = useState<{ series: string; label: string; month: number } | null>(null);

  const q = useQuery({
    queryKey: ["seasonality", win],
    queryFn: () => getSeasonality(win),
    staleTime: 10 * 60_000,
  });
  const g = q.data?.groups[group];
  const indexG = q.data?.groups.index;

  const cellBy = useMemo(() => {
    const m = new Map<string, SeasonalityCell>();
    for (const c of g?.cells ?? []) m.set(`${c.series}-${c.month}`, c);
    return m;
  }, [g]);

  // 이번 달(원본의 '다음 달') — 열 강조에만 쓴다.
  const signalMonth = indexG?.signal_month ? Number(indexG.signal_month.slice(5)) : null;
  const signalLabel = signalMonth ? `${signalMonth}월` : "이번 달";

  const cell = useQuery({
    queryKey: ["seasonalityCell", picked?.series, picked?.month],
    queryFn: () => getSeasonalityCell(picked!.series, picked!.month),
    enabled: picked != null,
    staleTime: 10 * 60_000,
  });
  const pickedStats = picked ? cellBy.get(`${picked.series}-${picked.month}`) : undefined;

  return (
    <>
      <StubCard
        title="월별 평균 수익률"
        subtitle={`칸을 누르면 그 달의 연도별 수익률 · ★ = FDR 유의${indexG ? ` · 데이터 ~${indexG.last_month}` : ""} · 예측 아님`}
        className="flex-1"
        scrollBody
        action={
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {GROUPS.map((x) => (
                <HeaderChip key={x.id} active={group === x.id} onClick={() => setGroup(x.id)}>
                  {x.label}
                </HeaderChip>
              ))}
            </div>
            <span className="h-3 w-px bg-white/25" />
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <HeaderChip key={w} active={win === w} onClick={() => setWin(w)}>
                  {w}
                </HeaderChip>
              ))}
            </div>
          </div>
        }
      >
        {q.isLoading || !g ? (
          <CardEmpty text={q.isLoading ? "불러오는 중… (처음 한 번 몇 초)" : "데이터 없음"} />
        ) : (
          <div className="space-y-2">
            <table className="w-full table-fixed border-separate border-spacing-[2px] text-[11px]">
              <thead>
                <tr>
                  <th className="w-[112px]" />
                  {MONTHS.map((m) => (
                    <th
                      key={m}
                      className={cn(
                        "text-center font-bold",
                        m === signalMonth ? "text-ge-point" : "text-ink-muted",
                      )}
                    >
                      {m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {g.series.map((s) => (
                  <tr key={s.key}>
                    <td className="truncate pr-1 font-bold text-ink">
                      {s.label}
                      <SeriesBadge continuation={s.continuation} proxy={s.proxy} />
                    </td>
                    {MONTHS.map((m) => {
                      const c = cellBy.get(`${s.key}-${m}`);
                      return (
                        <td key={m} className="p-0">
                          <button
                            type="button"
                            onClick={() => setPicked({ series: s.key, label: s.label, month: m })}
                            title={
                              c?.mean != null
                                ? `${s.label} ${m}월 · 평균 ${pct(c.mean)} · 상승 ${c.win_rate}% · t ${c.t} · n ${c.n}`
                                : `${s.label} ${m}월 · 표본 부족`
                            }
                            className={cn(
                              "flex h-11 w-full items-center justify-center rounded text-[10px] font-extrabold tabular-nums transition-transform hover:scale-[1.06]",
                              c?.mean == null
                                ? "bg-canvas-soft text-ink-faint"
                                : Math.abs(c.mean) > 1.5
                                  ? "text-white"
                                  : "text-ink",
                              m === signalMonth && "ring-1 ring-ge-point",
                            )}
                            style={cellStyle(c?.mean ?? null)}
                          >
                            {c?.mean == null ? "·" : c.mean.toFixed(1)}
                            {c?.fdr && <span className="ml-0.5">★</span>}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[11px] font-medium leading-snug text-ink-muted">
              칸 = 그 달의 과거 평균 수익률(%, 가격지수) · 빨강 = 오른 달, 파랑 = 내린 달 · 테두리 = {signalLabel} ·
              ★ = 다중검정(FDR 5%) 통과 칸
            </p>
          </div>
        )}
      </StubCard>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked ? `${picked.label} · ${picked.month}월` : ""}
        subtitle={
          pickedStats?.mean != null
            ? `평균 ${pct(pickedStats.mean)} · 상승 확률 ${pickedStats.win_rate}% · t ${pickedStats.t} · n ${pickedStats.n} (${win})${pickedStats.fdr ? " · ★ FDR 유의" : ""}`
            : "연도별 수익률 (전 기간)"
        }
        width={860}
      >
        {cell.isLoading ? (
          <CardEmpty text="불러오는 중…" />
        ) : (
          <div className="space-y-2">
            <SignedBarChart
              columns={(cell.data?.years ?? []).map((y) => ({ key: String(y.year), label: String(y.year), value: y.ret }))}
              height={220}
              unit="년"
              formatLabel={(l) => `'${l.slice(2)}`}
              formatValue={(v) => pct(v, 2)}
            />
            <p className="text-[11px] font-medium leading-snug text-ink-muted">
              막대 = 그 해 {picked?.month}월 수익률(가격지수, 배당 제외) · 빈 해 = 계산 불가(<b>0 아님</b>) ·
              요약 통계는 {win} 기준, 막대는 전 기간
              {pickedStats?.halves_agree === false && " · ⚠️ 앞/뒤 절반 방향 다름"}
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}

function SeriesBadge({ continuation, proxy }: { continuation: string; proxy: string | null }) {
  if (continuation === "frozen") {
    return (
      <span className="ml-1 rounded bg-canvas-soft px-1 py-0.5 text-[9px] font-bold text-ink-muted" title="2026-08 에서 갱신 중단">
        갱신 중단
      </span>
    );
  }
  if (continuation === "proxy") {
    return (
      <span className="ml-1 rounded bg-ge-point/10 px-1 py-0.5 text-[9px] font-bold text-ge-point" title={`2026-09 부터 ${proxy} 로 이음`}>
        대용
      </span>
    );
  }
  return null;
}
