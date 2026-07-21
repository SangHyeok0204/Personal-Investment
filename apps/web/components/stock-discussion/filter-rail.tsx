"use client";

import { useMemo } from "react";
import type {
  SdEtf,
  SdSentiment,
  SdSource,
  SdStats,
} from "@/lib/stock-discussion";
import { SENTIMENT_STYLE, SOURCE_STYLE, issuerColor } from "./brand";
import { cn } from "@/lib/utils";

export interface FilterState {
  issuer: string | null;
  category: string | null;
  etfCode: string | null;
  source: SdSource | null;
  sentiment: SdSentiment | null;
}

interface FilterRailProps {
  etfs: SdEtf[];
  stats: SdStats | undefined;
  filter: FilterState;
  onIssuer: (v: string | null) => void;
  onCategory: (v: string | null) => void;
  onEtf: (v: string | null) => void;
  onSource: (v: SdSource | null) => void;
  onSentiment: (v: SdSentiment | null) => void;
}

function Chip({
  label,
  active,
  onClick,
  accentColor,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  accentColor?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={active && accentColor ? { color: accentColor } : undefined}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[12px] font-semibold transition-colors",
        active
          ? "border-ge-point bg-ge-blue-bg text-ge-navy"
          : "border-hairline bg-canvas-soft text-ink-muted hover:bg-ge-blue-bg/50",
      )}
    >
      {label}
    </button>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-hairline bg-canvas p-4 shadow-card">
      <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-muted">
        {title}
      </div>
      {children}
    </section>
  );
}

export function FilterRail({
  etfs,
  stats,
  filter,
  onIssuer,
  onCategory,
  onEtf,
  onSource,
  onSentiment,
}: FilterRailProps) {
  const issuers = useMemo(
    () =>
      Array.from(new Set(etfs.map((e) => e.issuer).filter(Boolean))).sort(),
    [etfs],
  );
  const categories = useMemo(
    () =>
      Array.from(new Set(etfs.map((e) => e.category).filter(Boolean))).sort(),
    [etfs],
  );

  // 총건수(by_etf_source 합) / 오늘(today_by_etf) 맵.
  const totalByEtf = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of stats?.by_etf_source ?? [])
      m.set(r.etf_code, (m.get(r.etf_code) ?? 0) + r.n);
    return m;
  }, [stats]);
  const todayByEtf = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of stats?.today_by_etf ?? []) m.set(r.etf_code, r.n);
    return m;
  }, [stats]);

  // 발행사/분류 선택으로 ETF 목록 좁힘.
  const visibleEtfs = useMemo(
    () =>
      etfs
        .filter(
          (e) =>
            (!filter.issuer || e.issuer === filter.issuer) &&
            (!filter.category || e.category === filter.category),
        )
        .sort(
          (a, b) => (totalByEtf.get(b.code) ?? 0) - (totalByEtf.get(a.code) ?? 0),
        ),
    [etfs, filter.issuer, filter.category, totalByEtf],
  );

  const sent = stats?.sentiment;
  const labeled = sent?.labeled ?? 0;
  const pct = (n: number | undefined) =>
    labeled > 0 ? Math.round(((n ?? 0) / labeled) * 100) : 0;

  return (
    <div className="flex flex-col gap-3">
      {/* 발행사 */}
      <Section title="발행사">
        <div className="flex flex-wrap gap-1.5">
          <Chip
            label="전체"
            active={filter.issuer == null}
            onClick={() => onIssuer(null)}
          />
          {issuers.map((iss) => (
            <Chip
              key={iss}
              label={iss}
              active={filter.issuer === iss}
              accentColor={issuerColor(iss)}
              onClick={() => onIssuer(filter.issuer === iss ? null : iss)}
            />
          ))}
        </div>
      </Section>

      {/* 분류 */}
      {categories.length > 0 && (
        <Section title="분류">
          <div className="flex flex-wrap gap-1.5">
            <Chip
              label="전체"
              active={filter.category == null}
              onClick={() => onCategory(null)}
            />
            {categories.map((cat) => (
              <Chip
                key={cat}
                label={cat}
                active={filter.category === cat}
                onClick={() =>
                  onCategory(filter.category === cat ? null : cat)
                }
              />
            ))}
          </div>
        </Section>
      )}

      {/* ETF 목록 */}
      <Section title="ETF">
        <div className="flex flex-col gap-0.5">
          <EtfRow
            name="전체"
            code=""
            total={stats?.total}
            today={undefined}
            selected={filter.etfCode == null}
            onClick={() => onEtf(null)}
          />
          {visibleEtfs.map((e) => (
            <EtfRow
              key={e.code}
              name={e.name}
              code={e.code}
              accent={issuerColor(e.issuer, e.name)}
              total={totalByEtf.get(e.code) ?? 0}
              today={todayByEtf.get(e.code)}
              selected={filter.etfCode === e.code}
              onClick={() => onEtf(filter.etfCode === e.code ? null : e.code)}
            />
          ))}
        </div>
      </Section>

      {/* 소스 세그먼트 */}
      <Section title="소스">
        <div className="flex items-stretch rounded-lg border border-hairline p-0.5">
          <SourceSeg
            label="전체"
            active={filter.source == null}
            onClick={() => onSource(null)}
          />
          {(["네이버", "토스증권"] as SdSource[]).map((s) => (
            <SourceSeg
              key={s}
              label={s}
              active={filter.source === s}
              accent={SOURCE_STYLE[s].color}
              onClick={() => onSource(filter.source === s ? null : s)}
            />
          ))}
        </div>
      </Section>

      {/* 감성 (로드된 윈도우 클라 필터 · 수치는 전역 stats) */}
      <Section title="감성">
        <div className="mb-2 flex flex-wrap gap-1.5">
          <Chip
            label="전체"
            active={filter.sentiment == null}
            onClick={() => onSentiment(null)}
          />
          {(["긍정", "부정", "중립"] as SdSentiment[]).map((s) => (
            <Chip
              key={s}
              label={`${s} ${pct(sent?.[s])}%`}
              active={filter.sentiment === s}
              accentColor={SENTIMENT_STYLE[s].color}
              onClick={() => onSentiment(filter.sentiment === s ? null : s)}
            />
          ))}
        </div>
        {/* 미니 분포 바 */}
        <div className="flex h-1.5 overflow-hidden rounded-full bg-ge-blue-bg">
          {(["긍정", "부정", "중립"] as SdSentiment[]).map((s) => (
            <div
              key={s}
              style={{
                width: `${pct(sent?.[s])}%`,
                background: SENTIMENT_STYLE[s].color,
              }}
            />
          ))}
        </div>
        <div className="mt-1.5 text-[10.5px] leading-snug text-ink-faint">
          비율은 전체 라벨({labeled.toLocaleString("ko-KR")}건) 기준 · 칩 선택은
          로드된 목록에만 적용
        </div>
      </Section>
    </div>
  );
}

function EtfRow({
  name,
  code,
  accent,
  total,
  today,
  selected,
  onClick,
}: {
  name: string;
  code: string;
  accent?: string;
  total: number | undefined;
  today: number | undefined;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-md border-l-2 py-1.5 pl-2 pr-1.5 text-left transition-colors",
        selected
          ? "border-ge-point bg-ge-blue-bg"
          : "border-transparent hover:bg-canvas-soft",
      )}
    >
      <div className="min-w-0 flex-1">
        <div
          className="truncate text-[12.5px] font-semibold"
          style={accent ? { color: accent } : undefined}
        >
          {name}
        </div>
        {code && (
          <div className="text-[10.5px] tabular-nums text-ink-faint">{code}</div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {total != null && (
          <span className="text-[11px] tabular-nums text-ink-muted">
            {total.toLocaleString("ko-KR")}
          </span>
        )}
        {today != null && today > 0 && (
          <span className="rounded-full bg-ge-point/10 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-ge-point">
            +{today}
          </span>
        )}
      </div>
    </button>
  );
}

function SourceSeg({
  label,
  active,
  accent,
  onClick,
}: {
  label: string;
  active: boolean;
  accent?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative flex-1 rounded-md px-2 py-1.5 text-[12px] font-semibold transition-colors",
        active ? "bg-ge-blue-bg text-ge-navy" : "text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {label}
      {active && accent && (
        <span
          className="absolute inset-x-2 bottom-0.5 h-0.5 rounded-full"
          style={{ background: accent }}
        />
      )}
    </button>
  );
}
