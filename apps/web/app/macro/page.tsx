"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { MacroChart } from "@/components/charts/macro-chart";
import { CardEmpty, HeaderChip, SourceDownBanner, StubCard } from "@/components/stub";
import {
  getMacro,
  getMacroSeries,
  type MacroHistorySeries,
  type MacroRange,
  type MacroRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 매크로 지표 — 물가 · 고용 · 금리 · 성장.
//
// ★FRED 를 **키 없이** 쓴다. API(api.stlouisfed.org)는 api_key 가 없으면 400 이지만,
//   그래프 CSV 내보내기(fred.stlouisfed.org/graph/fredgraph.csv)는 키 없이 200 이다.
//
// ★2026-09-27 시계열로 개편(plan S6): 분류별 소형 다중 차트(small multiples).
//   모든 차트가 **같은 x 구간**을 쓴다 — 세로로 훑어 "그때 금리가 오르고 실업률이
//   올랐다"를 읽게 하려는 것이다. 음영은 NBER 경기침체(FRED USREC).
//
// ★지표마다 **읽는 방식이 다르다.** 전부 같은 방식으로 보여 주면 틀린 말이 된다.
//   · level    값 자체        실업률 4.1%
//   · yoy      전년 대비 변화율  CPI 332.8 이 아니라 "+3.35%"
//   · mom_diff 전월 대비 증감   비농업고용 158,913 이 아니라 "+16.2만명"
//   차트 선도 같은 변환을 거친 값이다(서버가 월말 다운샘플 후 계산).
//
// ⚠️CPI·고용은 발표가 한 달 이상 늦다. 차트 머리에 **기준일**을 붙인다 — 안 붙이면
//   "오늘 물가"로 오인된다.

const RANGES: { id: MacroRange; label: string }[] = [
  { id: "5y", label: "5Y" },
  { id: "10y", label: "10Y" },
  { id: "20y", label: "20Y" },
  { id: "max", label: "MAX" },
];

// 부호가 곧 뜻인 지표 — 0 선을 긋는다(금리차 역전, 고용 증감).
const ZERO_LINE_IDS = new Set(["T10Y2Y", "T10Y3M"]);

type Kind = Pick<MacroRow, "transform" | "unit">;

/** 지표의 본래 값을 그 지표의 단위로 적는다. */
function fmtValue(k: Kind, n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (k.transform === "yoy") return `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;
  if (k.transform === "mom_diff") {
    // 천명 단위는 만명으로 바꿔 적는다 — "+162천명"보다 "+16.2만명"이 읽힌다.
    if (k.unit === "천명") return `${n > 0 ? "+" : ""}${(n / 10).toFixed(1)}만명`;
    // ADP 는 **명** 단위로 온다(38,000) — 같은 만명 표기로 맞춘다.
    if (k.unit === "명") return `${n > 0 ? "+" : ""}${(n / 10_000).toFixed(1)}만명`;
    return `${n > 0 ? "+" : ""}${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  const digits = k.unit === "건" ? 0 : 2;
  return `${n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}${k.unit}`;
}

/** 축 눈금 — 소형 차트라 짧게. */
function fmtAxis(k: Kind, n: number): string {
  const trim = (v: number, d: number) => String(Number(v.toFixed(d)));
  if (k.transform === "yoy") return `${trim(n * 100, 1)}%`;
  if (k.transform === "mom_diff" && k.unit === "천명") return `${trim(n / 10, 0)}만`;
  if (k.transform === "mom_diff" && k.unit === "명") return `${trim(n / 10_000, 1)}만`;
  if (k.unit === "건") return `${trim(n / 10_000, 0)}만`;
  if (k.unit === "%" || k.unit === "%p") return `${trim(n, 2)}%`;
  return trim(n, 1);
}

/** 1Y 변화. yoy 는 %p, 퍼센트 수준은 bp, 나머지는 원 단위 차이. */
function delta(r: MacroRow, period: string): string {
  const raw = r.changes[period];
  if (raw == null) return "—";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  if (r.transform === "yoy") return `${sign}${(n * 100).toFixed(2)}%p`;
  if (r.transform === "mom_diff") {
    if (r.unit === "천명") return `${sign}${(n / 10).toFixed(1)}만`;
    if (r.unit === "명") return `${sign}${(n / 10_000).toFixed(1)}만`;
    return `${sign}${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  if (r.unit === "%" || r.unit === "%p") return `${sign}${(n * 100).toFixed(0)}bp`;
  return `${sign}${n.toLocaleString("en-US", { maximumFractionDigits: 1 })}`;
}

function tone(r: MacroRow, period: string): "up" | "down" | undefined {
  const raw = r.changes[period];
  if (raw == null) return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n) || n === 0) return undefined;
  // ⚠️'좋다/나쁘다'를 칠하지 않는다. 물가 상승은 빨강이 맞지만 고용 증가도
  //   빨강이 되면 색이 의미를 잃는다. 방향만 표시한다.
  return n > 0 ? "up" : "down";
}

export default function MacroPage() {
  const [range, setRange] = useState<MacroRange>("10y");
  const [notesOpen, setNotesOpen] = useState(false);

  const macro = useQuery({
    queryKey: ["macro"],
    queryFn: getMacro,
    // 월간 발표가 대부분이다. 서버도 1시간 캐시를 들고 있다.
    staleTime: 10 * 60_000,
    refetchInterval: 60 * 60_000,
  });
  const history = useQuery({
    queryKey: ["macro-series", range],
    queryFn: () => getMacroSeries(range),
    staleTime: 10 * 60_000,
    // 기간을 바꾸는 동안 이전 차트를 남겨 둔다(빈 화면 깜빡임 방지).
    placeholderData: (prev) => prev,
  });

  const rowsById = useMemo(
    () => new Map((macro.data?.rows ?? []).map((r) => [r.series_id, r])),
    [macro.data],
  );
  const byCategory = useMemo(() => {
    const map = new Map<string, MacroHistorySeries[]>();
    for (const s of history.data?.series ?? []) {
      const list = map.get(s.category) ?? [];
      list.push(s);
      map.set(s.category, list);
    }
    return map;
  }, [history.data]);

  const loading = history.isLoading;
  const sourceDown =
    !loading &&
    (history.data?.series.length ?? 0) === 0 &&
    (history.isError || (history.data?.missing.length ?? 0) > 0);
  const categories = history.data?.categories ?? ["물가", "고용", "금리", "성장"];
  const missing = history.data?.missing ?? macro.data?.missing ?? [];

  return (
    <>
      <Topbar
        title="매크로"
        subtitle="물가 · 고용 · 금리 · 성장 (FRED)"
        showAccountContext={false}
      />
      <PageContainer wide>
        <div className="flex flex-col gap-3">
          {sourceDown && (
            <SourceDownBanner source="FRED" detail="미국 경제지표 원천입니다." />
          )}

          <div className="flex flex-wrap items-center gap-2 rounded-xl bg-ge-header px-3 py-1.5">
            <span className="text-[11px] font-bold text-white/70">기간</span>
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <HeaderChip key={r.id} active={range === r.id} onClick={() => setRange(r.id)}>
                  {r.label}
                </HeaderChip>
              ))}
            </div>
            <span className="h-3 w-px bg-white/25" />
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-white/70">
              <span className="inline-block h-2.5 w-3 rounded-sm bg-white/30" />
              NBER 경기침체
            </span>
            {history.isFetching && !loading && (
              <span className="text-[11px] font-medium text-white/50">불러오는 중…</span>
            )}
            <button
              type="button"
              onClick={() => setNotesOpen(true)}
              className="ml-auto rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
            >
              출처 한계
            </button>
          </div>

          {categories.map((name) => {
            const list = byCategory.get(name) ?? [];
            if (!loading && list.length === 0) return null;
            return (
              <StubCard
                key={name}
                title={name}
                subtitle={loading ? "불러오는 중…" : `${list.length}개`}
              >
                {loading ? (
                  <CardEmpty text="불러오는 중…" />
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {list.map((s) => (
                      <MacroPanel
                        key={s.series_id}
                        series={s}
                        row={rowsById.get(s.series_id)}
                        start={history.data!.start}
                        end={history.data!.end}
                        bands={history.data!.recessions}
                      />
                    ))}
                  </div>
                )}
              </StubCard>
            );
          })}

          <p className="text-[11px] leading-relaxed text-ink-muted">
            월말 값 기준 · %: 전년 대비 · 고용: 전월 대비 · 색: 방향
          </p>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="출처 한계"
        subtitle="FRED 로 받을 수 없거나 넣지 않은 것"
      >
        <ul className="space-y-2">
          {(macro.data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                {text}
              </span>
            </li>
          ))}
        </ul>
        {missing.length > 0 && (
          <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
            이번 조회에서 못 받은 지표: {missing.join(", ")}
          </p>
        )}
      </Modal>
    </>
  );
}

/** 소형 차트 한 칸 — 머리에 이름 · 최신값 · 1Y 변화 · 기준일. */
function MacroPanel({
  series,
  row,
  start,
  end,
  bands,
}: {
  series: MacroHistorySeries;
  row: MacroRow | undefined;
  start: string;
  end: string;
  bands: [string, string][];
}) {
  const last = series.points[series.points.length - 1];
  const latest = row?.value != null ? Number(row.value) : last?.[1];
  const oneYear = row ? tone(row, "1Y") : undefined;
  const zeroLine = series.transform === "mom_diff" || ZERO_LINE_IDS.has(series.series_id);
  return (
    <div className="flex min-w-0 flex-col rounded-xl border border-hairline bg-canvas p-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className="truncate text-[12px] font-bold text-ink"
          title={`${series.series_id}${series.note ? ` · ${series.note}` : ""}`}
        >
          {series.name}
        </span>
        <span className="shrink-0 text-[15px] font-extrabold tabular-nums text-ge-navy">
          {latest != null ? fmtValue(series, latest) : "—"}
        </span>
      </div>
      <div className="mb-1 flex items-center justify-between gap-2 text-[11px] font-medium text-ink-muted">
        <span className="truncate">{series.note ?? " "}</span>
        <span className="shrink-0">
          {row && (
            <>
              1Y{" "}
              <b
                className={cn(
                  "tabular-nums",
                  oneYear === "up" && "text-bid",
                  oneYear === "down" && "text-ask",
                )}
              >
                {delta(row, "1Y")}
              </b>{" "}
              ·{" "}
            </>
          )}
          {row?.as_of ?? last?.[0] ?? "—"} 기준
        </span>
      </div>
      {series.points.length > 0 ? (
        <MacroChart
          points={series.points}
          start={start}
          end={end}
          bands={bands}
          zeroLine={zeroLine}
          axisFormat={(v) => fmtAxis(series, v)}
          tooltipFormat={(v) => fmtValue(series, v)}
        />
      ) : (
        <CardEmpty text="이 기간에 관측치가 없습니다" />
      )}
    </div>
  );
}
