"use client";

import { useEffect, useRef, useState } from "react";
import { TimeSeriesChart } from "@/components/ai-key-data/timeseries-chart";
import type { AiSeries } from "@/lib/api";

// [AI Key Data] 미니 패널 — 제목 + 범례 숫자 + 차트 한 장.
//
// ★2026-08-31 `epoch-card.tsx` 에서 그대로 빼냈다. 사용자 지시로 Epoch 카드를
//   "매출·칩·데이터센터"(수익성)와 "펀딩 라운드"(Demand)로 쪼개면서 같은 패널을 두 카드가
//   쓰게 됐다. 이 레포는 보통 차트 헬퍼를 카드마다 복붙하지만, 60줄짜리를 두 벌 두면
//   한쪽만 고쳐지는 사고가 난다 — `timeseries-chart.tsx` 를 공용으로 뺀 것과 같은 판단이다.
// 팔레트·숫자 포맷도 같이 온다. 두 카드가 색을 다르게 쓰면 같은 회사가 카드마다 다른
// 색으로 보인다.

export const PALETTE = ["#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7"];

export function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US");
}

// 그룹 하나 = 미니 패널(제목 + 범례 숫자 + 차트). note 는 group 이 아니라
// 카드 최상위(active.data.note)에 실리므로 여기선 series 빈 배열만 판단한다.
export function Panel({
  title,
  series,
  emptyMsg,
}: {
  title: string;
  series: AiSeries[];
  emptyMsg?: string;
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

  const top = series.slice(0, 4);

  return (
    // h-full — 카드가 그리드 한 칸에 갇히므로 패널이 그 높이를 나눠 갖는다.
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-hairline/70">
      <div className="flex items-center gap-2 border-b border-hairline/70 px-2.5 py-1">
        <span className="text-[13px] font-bold text-ink">{title}</span>
      </div>
      {top.length > 0 ? (
        <div className="flex flex-wrap gap-x-2 gap-y-0 px-2.5 pt-1 text-[12px]">
          {top.map((s, i) => (
            <span key={s.key} className="flex items-baseline gap-1">
              <span
                className="inline-block h-1.5 w-1.5 shrink-0 rounded-sm"
                style={{ background: PALETTE[i % PALETTE.length] }}
              />
              <span className="text-ink-muted">{s.label}</span>
              <b className="font-bold tabular-nums text-ink">
                {s.last == null ? "—" : fmtCompact(s.last)}
              </b>
            </span>
          ))}
        </div>
      ) : null}
      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-1 pt-0.5">
        {top.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4 text-center">
            <span className="text-[13px] font-semibold leading-relaxed text-ink-muted">
              {emptyMsg ?? "판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
            </span>
          </div>
        ) : box.w > 0 && box.h > 0 ? (
          <TimeSeriesChart series={top} w={box.w} h={box.h} fmt={fmtCompact} colors={PALETTE} />
        ) : null}
      </div>
    </div>
  );
}
