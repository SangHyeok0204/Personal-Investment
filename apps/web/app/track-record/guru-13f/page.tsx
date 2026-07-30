"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getGuru13fRoster,
  getGuru13fPortfolio,
  getGuru13fChanges,
  getGuru13fTimeline,
  getGuru13fConsensus,
  getGuru13fTurnover,
  type Guru13fPortfolio,
  type Guru13fChangeItem,
  type Guru13fExitItem,
  type Guru13fTimeline,
  type Guru13fConsensusFlow,
  type Guru13fTurnoverRow,
} from "@/lib/api";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

const REFETCH = 300000; // 5분

// 부호색 — 대시보드 컨벤션(＋빨강 / −파랑).
const POS = "#e74c3c"; // status-failed
const NEG = "#4a7ab5"; // status-running / ge-point
const GE_POINT = "#4a7ab5";
const GE_NAVY = "#243b5e";

// 타임라인 다계열(top-8) 구분용 팔레트 — GE 토큰 우선(navy/point/main/ask/success/failed)
// + 8계열 식별을 위한 보조 2색(퍼플·앰버). 구조색이 아닌 계열 식별용.
const SERIES_COLORS = [
  "#243b5e", // ge-navy
  "#4a7ab5", // ge-point
  "#6390bf", // ge-main
  "#0a9bc4", // ask (cyan)
  "#27ae60", // status-success (green)
  "#e74c3c", // status-failed (red)
  "#7c6bb5", // 보조 퍼플
  "#c98a2b", // 보조 앰버
];

/* ── 포맷터 ───────────────────────────────────────────────────────────── */

// 264e9 → "$264.0B" (digitsB=1) / "$264B" (digitsB=0), 450e6 → "$450M".
function fmtUsd(v: number | null | undefined, digitsB = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(digitsB)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${Math.round(v)}`;
}
function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
}
function signedPpt(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%p`;
}
// 티커 없으면 종목명으로 폴백.
function tickerOr(ticker: string | null, name: string): string {
  return ticker && ticker.trim() ? ticker : name;
}
function signColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "#8a94a6"; // ink-muted
  return v > 0 ? POS : NEG;
}

/* ── 페이지 ───────────────────────────────────────────────────────────── */

export default function Guru13fPage() {
  const rosterQuery = useQuery({
    queryKey: ["guru13fRoster"],
    queryFn: getGuru13fRoster,
    refetchInterval: REFETCH,
    retry: false,
  });
  const roster = rosterQuery.data;

  const [selCik, setSelCik] = useState<string | null>(null);
  const [selPeriod, setSelPeriod] = useState<string | null>(null);

  // roster 로드되면 최고 AUM 거장(=버크셔) + 그 거장의 최신 분기를 기본 선택.
  useEffect(() => {
    if (!roster || roster.gurus.length === 0) return;
    if (selCik == null) {
      const g = roster.gurus[0];
      setSelCik(g.cik);
      setSelPeriod(g.latest);
    }
  }, [roster, selCik]);

  const selGuru = useMemo(
    () => roster?.gurus.find((g) => g.cik === selCik) ?? null,
    [roster, selCik],
  );
  // 선택 거장의 분기 목록 (최신순).
  const quarters = useMemo(
    () => (selGuru ? [...selGuru.quarters].sort((a, b) => b.localeCompare(a)) : []),
    [selGuru],
  );

  // 거장 변경 → 해당 거장의 최신 분기로 리셋.
  const onGuruChange = (cik: string) => {
    const g = roster?.gurus.find((x) => x.cik === cik) ?? null;
    setSelCik(cik);
    setSelPeriod(g?.latest ?? null);
  };

  const ready = selCik != null && selPeriod != null;

  const portfolioQuery = useQuery({
    queryKey: ["guru13fPortfolio", selCik, selPeriod],
    queryFn: () => getGuru13fPortfolio(selCik as string, selPeriod as string),
    enabled: ready,
    refetchInterval: REFETCH,
    retry: false,
  });
  const changesQuery = useQuery({
    queryKey: ["guru13fChanges", selCik, selPeriod],
    queryFn: () => getGuru13fChanges(selCik as string, selPeriod as string),
    enabled: ready,
    refetchInterval: REFETCH,
    retry: false,
  });
  const timelineQuery = useQuery({
    queryKey: ["guru13fTimeline", selCik],
    queryFn: () => getGuru13fTimeline(selCik as string),
    enabled: selCik != null,
    refetchInterval: REFETCH,
    retry: false,
  });
  // 컨센서스/턴오버는 최신 분기 · 거장 무관(cross-guru).
  const consensusQuery = useQuery({
    queryKey: ["guru13fConsensus"],
    queryFn: getGuru13fConsensus,
    refetchInterval: REFETCH,
    retry: false,
  });
  const turnoverQuery = useQuery({
    queryKey: ["guru13fTurnover"],
    queryFn: getGuru13fTurnover,
    refetchInterval: REFETCH,
    retry: false,
  });

  const portfolio = portfolioQuery.data;
  const changes = changesQuery.data;
  const generatedAt = portfolio?.generatedAt ?? roster?.generatedAt ?? null;
  // roster 조회 실패/빈 목록이면 선택 의존 쿼리들이 영원히 비활성(=계속 Skeleton)
  // 되므로, 그 카드들은 degraded 안내로 대체한다.
  const rosterFailed =
    rosterQuery.isError || (roster != null && roster.gurus.length === 0);

  return (
    <>
      <Topbar
        title="GURU [13F]"
        subtitle="성과 분석 · 13F 기관/거장 포트폴리오"
        status={
          generatedAt ? (
            <span className="truncate text-[11px] text-slate-400">
              갱신 {generatedAt}
            </span>
          ) : undefined
        }
      />
      <PageContainer wide>
        {rosterQuery.isError && (
          <div className="mb-4">
            <ApiErrorBanner error={rosterQuery.error} />
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 lg:items-start">
        {/* ① 포트폴리오 구성 — 좌측 절반, 2행 span */}
        <Card
          title="포트폴리오 구성"
          className="lg:col-start-1 lg:row-start-1 lg:row-span-2"
          titleRight={
            roster && roster.gurus.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={selCik ?? ""}
                  onChange={(e) => onGuruChange(e.target.value)}
                  className="max-w-[300px] rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ge-navy outline-none focus:border-ge-point"
                >
                  {roster.gurus.map((g) => (
                    <option key={g.cik} value={g.cik}>
                      {g.guru} · {g.firm} ({fmtUsd(g.aum_usd, 0)})
                    </option>
                  ))}
                </select>
                <select
                  value={selPeriod ?? ""}
                  onChange={(e) => setSelPeriod(e.target.value)}
                  className="rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ge-navy outline-none focus:border-ge-point"
                >
                  {quarters.map((q) => (
                    <option key={q} value={q}>
                      {q}
                    </option>
                  ))}
                </select>
              </div>
            ) : undefined
          }
        >
          {rosterFailed ? (
            <NotReady />
          ) : portfolioQuery.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-8 w-full max-w-lg rounded-lg" />
              <Skeleton className="h-64 w-full rounded-xl" />
            </div>
          ) : portfolioQuery.isError || !portfolio ? (
            <NotReady />
          ) : (
            <div className="space-y-3">
              {/* 헤더 지표 */}
              <div className="flex flex-wrap items-stretch gap-1.5">
                <Stat label="종목수" value={`${portfolio.n_holdings}`} />
                <Stat label="AUM" value={fmtUsd(portfolio.aum_usd, 1)} />
                <Stat
                  label="top5 집중도"
                  value={fmtPct(portfolio.top5_pct, 1)}
                />
                <Stat
                  label="top10 집중도"
                  value={fmtPct(portfolio.top10_pct, 1)}
                />
                <Stat
                  label="가격커버"
                  value={`${portfolio.priced_n}/${portfolio.total_n}`}
                />
                {portfolio.filingDate && (
                  <Stat label="filing" value={portfolio.filingDate} />
                )}
              </div>

              {/* 상위 15 보유 */}
              <HoldingsTable portfolio={portfolio} />
            </div>
          )}
        </Card>

        {/* ② QoQ 비중 변화 — 우측 상단 */}
        <Card
          title="QoQ 비중 변화"
          className="lg:col-start-2 lg:row-start-1"
          titleBadge={
            changes?.amended ? (
              <span className="rounded-md bg-ge-blue-bg px-2 py-0.5 text-[10px] font-bold text-ge-point">
                정정본(13F-HR/A)
              </span>
            ) : undefined
          }
        >
          {rosterFailed ? (
            <NotReady />
          ) : changesQuery.isPending ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : changesQuery.isError || !changes ? (
            <NotReady />
          ) : changes.isFirst ? (
            <div className="flex h-24 items-center justify-center text-center text-[13px] text-ink-muted">
              직전 분기 데이터가 없습니다 — 최초 편입 분기입니다.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <ChangeCol title="신규 편입" tone="pos" items={changes.new} />
              <ChangeCol title="비중 확대" tone="pos" items={changes.increased} />
              <ChangeCol title="비중 축소" tone="neg" items={changes.decreased} />
              <ChangeCol title="청산" tone="neg" items={changes.exited} exited />
            </div>
          )}
        </Card>

        {/* ③ 비중 변화 타임라인 — 우측 하단 */}
        <Card
          title="비중 변화 타임라인"
          accent="navy"
          className="lg:col-start-2 lg:row-start-2"
        >
          {rosterFailed ? (
            <NotReady />
          ) : timelineQuery.isPending ? (
            <Skeleton className="h-72 w-full rounded-xl" />
          ) : timelineQuery.isError || !timelineQuery.data ? (
            <NotReady />
          ) : (
            <TimelineChart data={timelineQuery.data} />
          )}
        </Card>

        </div>

        {/* ④ 거장 컨센서스 / 턴오버 (최신 분기 · cross-guru) — 하단 풀폭 */}
        <Card title="거장 컨센서스 / 턴오버" accent="navy" className="mt-3">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {/* 컨센서스 */}
            <div>
              <SubHead>
                거장 컨센서스
                {consensusQuery.data && (
                  <span className="ml-1.5 text-[11px] font-semibold text-ink-muted">
                    {consensusQuery.data.period} · {consensusQuery.data.gurus_n}
                    개 기관
                  </span>
                )}
              </SubHead>
              {consensusQuery.isPending ? (
                <Skeleton className="h-52 w-full rounded-xl" />
              ) : consensusQuery.isError || !consensusQuery.data ? (
                <NotReady />
              ) : (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    {consensusQuery.data.holdings.slice(0, 10).map((h) => (
                      <div
                        key={h.cusip}
                        className="flex items-center gap-2 text-[12px]"
                      >
                        <span className="w-24 shrink-0 truncate font-bold text-ge-navy">
                          {tickerOr(h.ticker, h.name)}
                        </span>
                        <span className="w-14 shrink-0 tabular-nums text-ink-muted">
                          {h.holders_n}개
                        </span>
                        <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-canvas-soft">
                          <div
                            className="absolute inset-y-0 left-0 rounded-sm bg-ge-point"
                            style={{
                              width: `${Math.min(100, Math.max(0, h.conviction_pct))}%`,
                            }}
                          />
                        </div>
                        <span className="w-12 shrink-0 text-right font-bold tabular-nums text-ge-point">
                          {fmtPct(h.conviction_pct, 0)}
                        </span>
                      </div>
                    ))}
                  </div>
                  {(consensusQuery.data.buys.length > 0 ||
                    consensusQuery.data.sells.length > 0) && (
                    <div className="grid grid-cols-2 gap-x-4 border-t border-hairline pt-3">
                      <FlowCol
                        title="공동 매수 ▲"
                        color={POS}
                        rows={consensusQuery.data.buys.slice(0, 5)}
                      />
                      <FlowCol
                        title="공동 매도 ▼"
                        color={NEG}
                        rows={consensusQuery.data.sells.slice(0, 5)}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 턴오버 리더보드 */}
            <div>
              <SubHead>
                회전율 리더보드
                {turnoverQuery.data && (
                  <span className="ml-1.5 text-[11px] font-semibold text-ink-muted">
                    {turnoverQuery.data.period}
                  </span>
                )}
              </SubHead>
              {turnoverQuery.isPending ? (
                <Skeleton className="h-52 w-full rounded-xl" />
              ) : turnoverQuery.isError || !turnoverQuery.data ? (
                <NotReady />
              ) : (
                <TurnoverBoard rows={turnoverQuery.data.rows} />
              )}
            </div>
          </div>
        </Card>
      </PageContainer>
    </>
  );
}

/* ── 공용 셸 ──────────────────────────────────────────────────────────── */

function Card({
  title,
  accent = "point",
  titleBadge,
  titleRight,
  className,
  children,
}: {
  title: string;
  accent?: "point" | "navy";
  titleBadge?: React.ReactNode;
  titleRight?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const strip = accent === "navy" ? "bg-ge-navy" : "bg-ge-point";
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card",
        className,
      )}
    >
      <div className={cn("h-1.5 rounded-t-2xl", strip)} />
      <div className="px-4 pb-3.5 pt-3">
        <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <div className="flex items-center gap-2">
            <span className={cn("h-4 w-1.5 rounded-full", strip)} />
            <span className="text-[14px] font-extrabold text-ge-navy">
              {title}
            </span>
            {titleBadge}
          </div>
          {titleRight && <div className="ml-auto">{titleRight}</div>}
        </div>
        {children}
      </div>
    </section>
  );
}

function NotReady() {
  return (
    <div className="flex h-28 items-center justify-center px-4 text-center text-[13px] leading-relaxed text-ink-muted">
      데이터 준비 중 — 최초 스냅샷 생성이 완료되면 표시됩니다.
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-canvas-soft px-2.5 py-1">
      <div className="text-[10px] font-semibold text-ink-muted">{label}</div>
      <div className="text-[13.5px] font-extrabold tabular-nums text-ge-navy">
        {value}
      </div>
    </div>
  );
}

function SubHead({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center gap-2">
      <span className="h-3.5 w-1 rounded-full bg-ge-point" />
      <span className="text-[12.5px] font-extrabold text-ge-navy">
        {children}
      </span>
    </div>
  );
}

/* ── ① 보유 테이블 ───────────────────────────────────────────────────── */

function HoldingsTable({ portfolio }: { portfolio: Guru13fPortfolio }) {
  const maxW = Math.max(
    0.01,
    ...portfolio.holdings.map((h) => h.weight_pct),
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[340px] text-[11.5px]">
        <thead>
          <tr className="bg-ge-th text-ink-muted">
            <th className="rounded-l-md py-1 pl-2 pr-2 text-left font-semibold">
              티커
            </th>
            <th className="py-1 pr-2 text-left font-semibold">종목명</th>
            <th className="py-1 pr-2 text-right font-semibold">비중</th>
            <th className="w-[24%] py-1 pr-2" />
            <th className="rounded-r-md py-1 pr-2 text-right font-semibold">
              평가액
            </th>
          </tr>
        </thead>
        <tbody>
          {portfolio.holdings.map((h) => (
            <tr key={h.cusip} className="border-b border-hairline/60">
              <td className="py-1 pl-2 pr-2 font-bold text-ge-navy">
                {h.ticker ? h.ticker : h.name}
              </td>
              <td className="max-w-[150px] truncate py-1 pr-2 text-ink-secondary">
                {h.name}
              </td>
              <td className="py-1 pr-2 text-right font-bold tabular-nums text-ge-navy">
                {fmtPct(h.weight_pct, 2)}
              </td>
              <td className="py-1 pr-2">
                <div className="relative h-2 w-full overflow-hidden rounded-sm bg-canvas-soft">
                  <div
                    className="absolute inset-y-0 left-0 rounded-sm bg-ge-point"
                    style={{ width: `${(h.weight_pct / maxW) * 100}%` }}
                  />
                </div>
              </td>
              <td className="py-1 pr-2 text-right tabular-nums text-ink-secondary">
                {fmtUsd(h.value_usd, 1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── ② QoQ 변화 컬럼 ─────────────────────────────────────────────────── */

function ChangeCol({
  title,
  tone,
  items,
  exited = false,
}: {
  title: string;
  tone: "pos" | "neg";
  items: (Guru13fChangeItem | Guru13fExitItem)[];
  exited?: boolean;
}) {
  const color = tone === "pos" ? POS : NEG;
  const maxAbs = Math.max(
    0.01,
    ...items.map((it) => Math.abs(it.delta_ppt)),
  );
  const shown = items.slice(0, 8);
  const more = items.length - shown.length;
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ background: color }}
        />
        <span className="text-[11.5px] font-bold text-ink-secondary">
          {title}
        </span>
        <span className="text-[10.5px] tabular-nums text-ink-faint">
          {items.length}
        </span>
      </div>
      {shown.length === 0 ? (
        <div className="text-[11.5px] text-ink-faint">변동 없음</div>
      ) : (
        <div className="space-y-1.5">
          {shown.map((it) => {
            const frac = (Math.abs(it.delta_ppt) / maxAbs) * 100;
            const prevW =
              exited && "prev_weight_pct" in it ? it.prev_weight_pct : null;
            return (
              <div key={it.cusip} className="text-[11.5px]">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate font-semibold text-ge-navy">
                    {tickerOr(it.ticker, it.name)}
                  </span>
                  <span
                    className="shrink-0 font-bold tabular-nums"
                    style={{ color }}
                  >
                    {signedPpt(it.delta_ppt, 2)}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <div className="relative h-2 flex-1 overflow-hidden rounded-sm bg-canvas-soft">
                    <div
                      className="absolute inset-y-0 left-0 rounded-sm"
                      style={{ width: `${frac}%`, background: color }}
                    />
                  </div>
                  {prevW != null && (
                    <span className="shrink-0 text-[10px] tabular-nums text-ink-faint">
                      직전 {fmtPct(prevW, 1)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
          {more > 0 && (
            <div className="text-[10.5px] text-ink-faint">외 {more}종목</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── ③ 타임라인 차트 (반응형 SVG 멀티라인) ───────────────────────────── */

const TL_H = 240;
const TL_PAD_L = 42;
const TL_PAD_R = 14;
const TL_PAD_T = 12;
const TL_PAD_B = 30;

function niceStep(raw: number): number {
  if (!(raw > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const nn = raw / p;
  const step = nn < 1.5 ? 1 : nn < 3 ? 2 : nn < 7 ? 5 : 10;
  return step * p;
}

function TimelineChart({ data }: { data: Guru13fTimeline }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(760);
  const [hoverI, setHoverI] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      for (const en of entries) setW(en.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const periods = data.periods;
  const series = data.series.slice(0, 8);
  const n = periods.length;

  const iw = Math.max(1, w - TL_PAD_L - TL_PAD_R);
  const ih = TL_H - TL_PAD_T - TL_PAD_B;
  const denomX = Math.max(1, n - 1);

  let mx = 0;
  for (const s of series) for (const v of s.weights) if (v > mx) mx = v;
  mx = mx <= 0 ? 1 : mx * 1.08;

  const X = (i: number) => TL_PAD_L + (iw * i) / denomX;
  const Y = (v: number) => TL_PAD_T + (ih * (mx - v)) / mx;

  const step = niceStep(mx / 4);
  const gridVals: number[] = [];
  for (let g = 0; g <= mx + 1e-9; g += step) gridVals.push(g);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const x = ((e.clientX - rect.left) / rect.width) * w;
    let i = Math.round(((x - TL_PAD_L) / iw) * denomX);
    i = Math.max(0, Math.min(n - 1, i));
    setHoverI(i);
  };

  if (n === 0 || series.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center text-center text-[13px] text-ink-muted">
        타임라인 데이터가 없습니다.
      </div>
    );
  }

  const hx = hoverI != null ? X(hoverI) : 0;
  const tipRight = hx > w / 2;

  return (
    <div className="space-y-3">
      <div ref={wrapRef} className="relative w-full">
        <svg
          width="100%"
          height={TL_H}
          viewBox={`0 0 ${w} ${TL_H}`}
          onMouseMove={onMove}
          onMouseLeave={() => setHoverI(null)}
          style={{ display: "block" }}
        >
          {/* Y 그리드 */}
          {gridVals.map((g) => (
            <g key={`g-${g}`}>
              <line
                x1={TL_PAD_L}
                y1={Y(g)}
                x2={w - TL_PAD_R}
                y2={Y(g)}
                stroke="#EDF0F5"
                strokeWidth={1}
              />
              <text
                x={TL_PAD_L - 8}
                y={Y(g) + 3.5}
                textAnchor="end"
                fontSize={10.5}
                fill="#8a94a6"
              >
                {g.toFixed(0)}%
              </text>
            </g>
          ))}

          {/* X 분기 눈금 */}
          {periods.map((p, i) => (
            <g key={`x-${p}`}>
              <line
                x1={X(i)}
                y1={TL_H - TL_PAD_B}
                x2={X(i)}
                y2={TL_H - TL_PAD_B + 4}
                stroke="#c9d1dd"
                strokeWidth={1}
              />
              <text
                x={X(i)}
                y={TL_H - TL_PAD_B + 16}
                textAnchor="middle"
                fontSize={9.5}
                fill="#8a94a6"
              >
                {p}
              </text>
            </g>
          ))}

          {/* 호버 세로선 */}
          {hoverI != null && (
            <line
              x1={hx}
              y1={TL_PAD_T}
              x2={hx}
              y2={TL_H - TL_PAD_B}
              stroke="#B7C0CE"
              strokeWidth={1}
            />
          )}

          {/* 라인 */}
          {series.map((s, si) => {
            const pts = s.weights
              .map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`)
              .join(" ");
            return (
              <polyline
                key={s.cusip}
                points={pts}
                fill="none"
                stroke={SERIES_COLORS[si % SERIES_COLORS.length]}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}

          {/* 호버 점 */}
          {hoverI != null &&
            series.map((s, si) => {
              const v = s.weights[hoverI];
              if (v == null || !Number.isFinite(v)) return null;
              return (
                <circle
                  key={`dot-${s.cusip}`}
                  cx={X(hoverI)}
                  cy={Y(v)}
                  r={3}
                  fill={SERIES_COLORS[si % SERIES_COLORS.length]}
                  stroke="#ffffff"
                  strokeWidth={1.5}
                  style={{ pointerEvents: "none" }}
                />
              );
            })}
        </svg>

        {/* 호버 툴팁 */}
        {hoverI != null && (
          <div
            className="pointer-events-none absolute top-2 z-10 rounded-lg border border-hairline bg-canvas/95 px-3 py-2 shadow-panel backdrop-blur-sm"
            style={{
              left: hx,
              transform: tipRight
                ? "translateX(calc(-100% - 10px))"
                : "translateX(10px)",
            }}
          >
            <div className="mb-1 text-[11px] font-bold text-ge-navy">
              {periods[hoverI]}
            </div>
            <div className="space-y-0.5">
              {series.map((s, si) => (
                <div
                  key={`tip-${s.cusip}`}
                  className="flex items-center justify-between gap-4 text-[11px]"
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{
                        background: SERIES_COLORS[si % SERIES_COLORS.length],
                      }}
                    />
                    <span className="text-ink-secondary">
                      {tickerOr(s.ticker, s.name)}
                    </span>
                  </span>
                  <span className="font-bold tabular-nums text-ge-navy">
                    {fmtPct(s.weights[hoverI], 1)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 범례 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-hairline pt-3">
        {series.map((s, si) => {
          const last = s.weights[s.weights.length - 1];
          return (
            <div key={`lg-${s.cusip}`} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-4 rounded-full"
                style={{ background: SERIES_COLORS[si % SERIES_COLORS.length] }}
              />
              <span className="text-[11.5px] font-bold text-ge-navy">
                {tickerOr(s.ticker, s.name)}
              </span>
              <span className="text-[11px] tabular-nums text-ink-muted">
                {fmtPct(last, 1)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── ④ 컨센서스 플로우 · 턴오버 ─────────────────────────────────────── */

function FlowCol({
  title,
  color,
  rows,
}: {
  title: string;
  color: string;
  rows: Guru13fConsensusFlow[];
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-bold" style={{ color }}>
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="text-[11px] text-ink-faint">없음</div>
      ) : (
        <div className="space-y-1">
          {rows.map((r) => (
            <div
              key={r.cusip}
              className="flex items-center justify-between gap-2 text-[11px]"
            >
              <span className="min-w-0 truncate font-semibold text-ge-navy">
                {tickerOr(r.ticker, r.name)}
              </span>
              <span className="shrink-0 tabular-nums text-ink-muted">
                {r.buyers}/{r.sellers}
                <span className="ml-1.5 font-bold" style={{ color }}>
                  {r.net > 0 ? "+" : ""}
                  {r.net}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TurnoverBoard({ rows }: { rows: Guru13fTurnoverRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-[12px] text-ink-muted">
        데이터 없음
      </div>
    );
  }
  const maxT = Math.max(0.01, ...rows.map((r) => r.turnover_pct));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.cik} className="flex items-center gap-2 text-[12px]">
          <span className="w-36 shrink-0 truncate">
            <span className="font-bold text-ge-navy">{r.guru}</span>
            <span className="ml-1 text-[10.5px] text-ink-faint">{r.firm}</span>
          </span>
          <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-canvas-soft">
            <div
              className="absolute inset-y-0 left-0 rounded-sm bg-ge-navy"
              style={{ width: `${(r.turnover_pct / maxT) * 100}%` }}
            />
          </div>
          <span className="w-14 shrink-0 text-right font-bold tabular-nums text-ge-navy">
            {fmtPct(r.turnover_pct, 1)}
          </span>
          <span className="w-24 shrink-0 text-right text-[10.5px] tabular-nums text-ink-muted">
            <span style={{ color: POS }}>+{r.new_n}</span>
            <span className="mx-0.5 text-ink-faint">/</span>
            <span style={{ color: NEG }}>−{r.exited_n}</span>
            {r.partial && (
              <span className="ml-1 rounded bg-canvas-soft px-1 py-0.5 text-[9px] font-bold text-ink-faint">
                부분
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
