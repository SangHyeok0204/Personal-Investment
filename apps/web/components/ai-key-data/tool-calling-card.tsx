"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getToolCalling, type AiSeries, type ToolCalling } from "@/lib/api";
import { TimeSeriesChart } from "@/components/ai-key-data/timeseries-chart";
import { StaleBadge } from "@/components/ai-key-data/stale-badge";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [AI Key Data] OpenRouter tool-calling — Demand 분류 (2026-08-31 신설).
//
// ★★**비중(tool/total)을 그리지 않는다.** 598일 내내 99.28~99.46% 라 사실상 상수다
//   (원본 xlsx·재수집 양쪽 실측). OpenRouter 의 `modality=tool_calling` 은 "툴콜을 실제로
//   쓴 요청"이 아니라 "툴콜을 지원하는 모델" 쪽에 가까워서, 비중을 선으로 그리면 평평한
//   99% 직선이 나오고 아무것도 안 보인다. 서버(`/tool-calling`)도 같은 이유로 series 에
//   비중을 싣지 않고 `stats.share_pct` 에 숫자 하나로만 준다 — 그 숫자는 헤더에 적는다.
//
// ★패널 둘로 세로 분할하는 이유는 컴퓨팅 지수 카드와 같다: 배수(160x)와 non-tool
//   토큰(82,000,000,000)은 스케일이 9자릿수 차이라 한 축에 겹치면 한쪽이 바닥에 눌린다.
//   각자 자기 축을 갖는 패널로 나눈다(dual-axis 금지).
//
// 렌더 관례는 epoch-card / ai-usage-card 와 같다(ResizeObserver + TimeSeriesChart).

const RATIO_COLOR = ["#7b5ea7"];
const NON_TOOL_COLOR = ["#e8871e"];

function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US");
}

function Panel({
  title,
  last,
  series,
  colors,
  fmt,
}: {
  title: string;
  last: string;
  series: AiSeries[];
  colors: string[];
  fmt: (v: number) => string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-hairline/70">
      <div className="flex items-baseline gap-2 border-b border-hairline/70 px-2.5 py-1">
        <span className="text-[13px] font-bold text-ink">{title}</span>
        <span className="ml-auto text-[13px] font-extrabold tabular-nums text-ink">
          {last}
        </span>
      </div>
      <div ref={wrapRef} className="min-h-0 flex-1">
        {box.w > 0 && box.h > 0 ? (
          <TimeSeriesChart series={series} w={box.w} h={box.h} fmt={fmt} colors={colors} />
        ) : null}
      </div>
    </div>
  );
}

export function ToolCallingCard({
  colSpan = 3,
  tabs,
}: {
  colSpan?: 1 | 2 | 3;
  tabs?: React.ReactNode;
}) {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const { data, isLoading, isError } = useQuery<ToolCalling>({
    queryKey: ["tool-calling"],
    queryFn: getToolCalling,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  const ratio = data?.series.find((s) => s.key === "ratio");
  const nonTool = data?.series.find((s) => s.key === "non_tool");
  const st = data?.stats ?? null;

  const toSeries = (s: typeof ratio, label: string, unit: string): AiSeries[] =>
    s ? [{ key: s.key, label, unit, kind: "line", last: null, points: s.points }] : [];

  return (
    <section
      className={cn(
        zoomCls,
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(`lg:col-span-${n}` 은 안 나온다).
        colSpan === 1 ? "lg:col-span-1" : colSpan === 2 ? "lg:col-span-2" : "lg:col-span-3",
      )}
    >
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        {tabs ?? (
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">Tool-calling</h2>
        )}
        {/* ★탭 칩 바로 옆 한 줄 설명(2026-08-31 사용자 지시) — 이 탭이 뭘 재는지.
            비중 숫자는 그 뒤에 맥락으로만 붙인다(차트로 그리면 평평한 직선이라 안 그린다). */}
        <span className="shrink-0 text-[13px] font-semibold text-white/90">
          에이전트형 사용 강도
        </span>
        <span className="min-w-0 truncate text-[13px] text-white/60">
          tool 비중 {st?.share_pct == null ? EMDASH : `${st.share_pct.toFixed(1)}%`} · 거의 상수라 배수로 본다
        </span>
        <StaleBadge source={data?.source} />
        {data?.asof ? (
          <span className="ml-auto shrink-0 text-[13px] tabular-nums text-white/60">
            {data.asof} 기준
          </span>
        ) : null}
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
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-1.5 md:grid-cols-2">
            <Panel
              title="tool / non-tool (배수)"
              last={st?.ratio == null ? EMDASH : `${st.ratio.toFixed(1)}x`}
              series={toSeries(ratio, "배수", "x")}
              colors={RATIO_COLOR}
              fmt={(v) => `${v.toFixed(0)}x`}
            />
            <Panel
              title="non-tool 토큰"
              last={st?.non_tool == null ? EMDASH : fmtCompact(st.non_tool)}
              series={toSeries(nonTool, "non-tool", "tokens")}
              colors={NON_TOOL_COLOR}
              fmt={fmtCompact}
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
