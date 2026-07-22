"use client";

// 급등락 전광판 — 구성종목 전일比 등락 ±MOVERS_THRESHOLD_PCT% 이상을 우→좌 마퀴로.
// 스스로 구성종목을 폴링하는 자립 컴포넌트 (랜딩 상단 배치용).
// 움직이는 종목이 없으면 아무것도 렌더하지 않는다.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Flame } from "lucide-react";
import { getInavComponents, type InavComponentsPayload } from "@/lib/api";
import { RollingText } from "@/components/rolling-text";
import { cn } from "@/lib/utils";

const MOVERS_THRESHOLD_PCT = 5;

interface MoverItem {
  key: string;
  name: string;
  pct: number;
  etfs: string[];
}

function signedPct(pct: number, digits = 2): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

function buildMovers(payload: InavComponentsPayload | null): MoverItem[] {
  if (!payload?.byEtf) return [];
  const grouped = new Map<string, MoverItem>();
  for (const [etfCode, entry] of Object.entries(payload.byEtf)) {
    for (const c of entry.components ?? []) {
      if (c.isCash || c.livePrice == null || c.basePrice == null) continue;
      if (c.livePrice <= 0 || c.basePrice <= 0) continue;
      const pct = (c.livePrice / c.basePrice - 1) * 100;
      if (Math.abs(pct) < MOVERS_THRESHOLD_PCT) continue;
      const key = (c.isin || c.name || "").toUpperCase();
      if (!key) continue;
      const item = grouped.get(key) ?? {
        key,
        name: c.name || c.isin || "?",
        pct,
        etfs: [],
      };
      item.pct = pct;
      if (!item.etfs.includes(etfCode)) item.etfs.push(etfCode);
      grouped.set(key, item);
    }
  }
  return [...grouped.values()].sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));
}

export function MoversTicker() {
  const query = useQuery({
    queryKey: ["inavComponents"],
    queryFn: getInavComponents,
    refetchInterval: 2000,
    retry: false,
  });
  const items = useMemo(() => buildMovers(query.data ?? null), [query.data]);
  if (items.length === 0) return null;

  // 아이템 수에 비례해 속도 유지 (한 바퀴 시간).
  const duration = Math.max(24, items.length * 6);
  return (
    <div className="h-11 shrink-0 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
      <div
        className="inav-ticker-track flex h-11 items-center"
        style={{ animationDuration: `${duration}s` }}
      >
        <TickerRun items={items} />
        <TickerRun items={items} />
      </div>
    </div>
  );
}

function TickerRun({ items }: { items: MoverItem[] }) {
  return (
    <div className="flex h-11 min-w-[100vw] shrink-0 items-center gap-7 px-6">
      <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-ink-muted">
        <Flame className="h-3.5 w-3.5 text-status-failed" strokeWidth={2.2} />
        급등락 ±{MOVERS_THRESHOLD_PCT}%
      </span>
      {items.map((it) => (
        <TickerChip key={it.key} item={it} />
      ))}
    </div>
  );
}

function TickerChip({ item }: { item: MoverItem }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5"
      title={`편입 ETF: ${item.etfs.join(", ")}`}
    >
      <span className="text-[12.5px] font-bold text-ge-navy">{item.name}</span>
      <span
        className={cn(
          "px-0.5 text-[12.5px] font-extrabold tabular-nums",
          item.pct >= 0 ? "text-status-failed" : "text-status-running",
        )}
      >
        <RollingText text={signedPct(item.pct)} />
      </span>
      <span className="text-[10px] text-ink-faint">
        {item.etfs.length > 1
          ? `${item.etfs[0]} 외 ${item.etfs.length - 1}`
          : item.etfs[0]}
      </span>
    </span>
  );
}
