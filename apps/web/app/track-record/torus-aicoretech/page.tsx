"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getFundSeries,
  getInavWrapRebalancing,
  type FundSeriesResponse,
  type RebalSeries,
  type RebalEvent,
  type RebalCat,
  type RebalWindowPerf,
} from "@/lib/api";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PerfReportCard } from "@/components/perf-brief/perf-report-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

const EMDASH = "−";

// 부호색 — 대시보드 컨벤션(＋빨강 / −파랑).
const POS = "#e74c3c"; // status-failed
const NEG = "#4a7ab5"; // status-running / ge-point

// 하단 리밸런싱 성과분석 패널은 여전히 이 두 포트폴리오 전용이다(편입 구성 이력이
// 리밸런싱_히스토리 시트에만 있다). 위 차트는 등록된 펀드를 전부 그리므로 이 상수를 쓰지 않는다.
const SELF_ID = "aicoretech";
const BM_ID = "torus";

// 라인 색 — 펀드가 몇 개로 늘어나도 서로 구분되도록 팔레트를 돌려 쓴다. 자사/BM 같은
// 고정 역할이 없어져서 "무슨 색이 누구"는 범례가 알려 준다. 다만 눈에 익은 두 포트폴리오는
// 쓰던 색을 유지한다.
const PALETTE = [
  "#4a7ab5", // ge-point
  "#243b5e", // ge-navy
  "#c0873a", // bronze
  "#3f8f74", // teal
  "#8e5aa8", // violet
  "#c4574f", // clay
  "#5c8fa8", // steel
  "#7f8a3f", // olive
];
const PINNED_COLOR: Record<string, string> = {
  aicoretech: "#4a7ab5",
  torus: "#243b5e",
};

function assignColors(ids: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  const used = new Set<string>();
  for (const id of ids) {
    const c = PINNED_COLOR[id];
    if (c) {
      out[id] = c;
      used.add(c);
    }
  }
  let k = 0;
  for (const id of ids) {
    if (out[id]) continue;
    // 팔레트를 다 쓰면 겹침을 허용하고 순환한다(색보다 그림이 우선).
    while (used.size < PALETTE.length && used.has(PALETTE[k % PALETTE.length])) k++;
    out[id] = PALETTE[k % PALETTE.length];
    used.add(out[id]);
    k++;
  }
  return out;
}

function signedPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function signColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "#8a94a6"; // ink-muted
  return v > 0 ? POS : NEG;
}

// "2026-03-10" → "2026.03.10"
function dotDate(d: string | undefined): string {
  return d ? d.replace(/-/g, ".") : "";
}

// "2026-03" → "2026.03"
function fmtMonth(m: string): string {
  return m.replace("-", ".");
}

/* ── 데이터 모델: 공통 날짜축 위의 N 개 계열 ───────────────────────────── */

interface Line {
  id: string;
  label: string;
  color: string;
  values: (number | null)[]; // 각 계열 인셉션 기준 누적수익률%, 공통축 정렬
}
interface Model {
  D: string[]; // 공통 날짜축 (합집합, 오름차순)
  lines: Line[];
}

/** 등록된 펀드 → 비교 모델. hidden 에 든 id 는 뺀다(범례에서 끄는 용도).
 *
 * 날짜축은 **합집합**이다. 예전에는 두 계열의 교집합을 썼는데, 펀드가 늘어나면 인셉션이
 * 가장 늦은 하나가 비교 구간 전체를 잘라 버린다(2024-11 부터 있는 펀드와 2026-03 부터인
 * 펀드를 같이 올리면 4개월만 남는다). 합집합으로 두고 값이 없는 구간은 null 로 비우면,
 * buildPlot 이 각 선을 자기 첫 데이터부터 그리면서 창 시작 기준으로 리베이스한다.
 */
function buildModel(
  data: FundSeriesResponse | undefined,
  hidden: Set<string>,
): Model | null {
  // 색은 **등록된 전체** 기준으로 배정한다. 보이는 것만으로 배정하면 하나 껐을 때 남은
  // 선들의 색이 바뀌어 버린다.
  const colors = assignColors((data?.funds ?? []).map((f) => f.id));
  const funds = (data?.funds ?? []).filter((f) => !hidden.has(f.id));
  if (!funds.length) return null;

  const all = new Set<string>();
  const maps = funds.map((f) => {
    for (const [d] of f.points) all.add(d);
    return new Map(f.points);
  });
  const D = Array.from(all).sort();
  if (D.length < 2) return null;

  return {
    D,
    lines: funds.map((f, i) => ({
      id: f.id,
      label: f.label,
      color: colors[f.id],
      values: D.map((d) => maps[i].get(d) ?? null),
    })),
  };
}

/* ── 기간 선택 → 윈도우 인덱스 [s0, e] ────────────────────────────────── */

type Period =
  | { kind: "all" }
  | { kind: "recent"; months: 1 | 3 | 6 | 12 }
  | { kind: "month"; m: string }
  | { kind: "custom"; start: string; end: string };

// D[0] 을 제외한 고유 YYYY-MM (등장순).
function monthsOf(D: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (let i = 1; i < D.length; i++) {
    const m = D[i].slice(0, 7);
    if (!seen.has(m)) {
      seen.add(m);
      out.push(m);
    }
  }
  return out;
}
function monthStartIdx(D: string[], m: string): number {
  return D.findIndex((d) => d.slice(0, 7) === m);
}
function monthEndIdx(D: string[], m: string): number {
  let last = -1;
  for (let i = 0; i < D.length; i++) if (D[i].slice(0, 7) === m) last = i;
  return last;
}
// date 미만인 마지막 인덱스 (없으면 -1).
function idxBefore(D: string[], date: string): number {
  let idx = -1;
  for (let i = 0; i < D.length; i++) {
    if (D[i] < date) idx = i;
    else break;
  }
  return idx;
}
// date 이하인 마지막 인덱스 (없으면 -1).
function idxAsof(D: string[], date: string): number {
  let idx = -1;
  for (let i = 0; i < D.length; i++) {
    if (D[i] <= date) idx = i;
    else break;
  }
  return idx;
}

function computeWindow(period: Period, D: string[]): { s0: number; e: number } {
  const n = D.length;
  if (n < 2) return { s0: 0, e: Math.max(0, n - 1) };
  const last = n - 1;

  if (period.kind === "all") return { s0: 0, e: last };

  if (period.kind === "recent") {
    const MONTHS = monthsOf(D);
    if (!MONTHS.length) return { s0: 0, e: last };
    const m = MONTHS[Math.max(0, MONTHS.length - period.months)];
    return { s0: Math.max(0, monthStartIdx(D, m) - 1), e: last };
  }

  if (period.kind === "month") {
    const si = monthStartIdx(D, period.m);
    const ei = monthEndIdx(D, period.m);
    if (si < 0 || ei < 0) return { s0: 0, e: last };
    return { s0: Math.max(0, si - 1), e: ei };
  }

  // custom: start~end 직접 지정. 앵커 = start 직전 거래일, e = end 당일까지.
  const { start, end } = period;
  if (!start || !end || start > end) return { s0: 0, e: last }; // start<=end 가드
  const s0 = Math.max(0, idxBefore(D, start));
  const b = idxAsof(D, end);
  if (b < 0 || b < s0) return { s0: 0, e: last };
  return { s0, e: b };
}

/* ── 윈도우 시작 = 0% 리베이스 + 스케일 ───────────────────────────────── */

interface PlotLine {
  id: string;
  label: string;
  color: string;
  vals: (number | null)[]; // 윈도우 시작 기준 리베이스된 %
}
interface Plot {
  dates: string[];
  lines: PlotLine[];
  mn: number;
  mx: number;
}

function buildPlot(model: Model, win: { s0: number; e: number }): Plot {
  const { s0, e } = win;
  const dates = model.D.slice(s0, e + 1);
  let mn = 0; // 0% 기준선을 항상 포함
  let mx = 0;

  const lines: PlotLine[] = model.lines.map((ln) => {
    const raw = ln.values.slice(s0, e + 1);
    const first = raw.findIndex((v) => v != null && Number.isFinite(v));
    let vals: (number | null)[];
    if (first < 0) {
      vals = raw.map(() => null);
    } else {
      const b = 1 + (raw[first] as number) / 100;
      vals = raw.map((v, i) =>
        i < first || v == null || !Number.isFinite(v)
          ? null
          : ((1 + v / 100) / b - 1) * 100,
      );
    }
    for (const v of vals) {
      if (v != null && Number.isFinite(v)) {
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    return { id: ln.id, label: ln.label, color: ln.color, vals };
  });

  const pad = (mx - mn || 1) * 0.06;
  return { dates, lines, mn: mn - pad, mx: mx + pad };
}

// (mx-mn)/5 근처의 "예쁜" 눈금 간격.
function niceStep(raw: number): number {
  if (!(raw > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const nn = raw / p;
  const step = nn < 1.5 ? 1 : nn < 3 ? 2 : nn < 7 ? 5 : 10;
  return step * p;
}
function fmtTick(v: number): string {
  let r = Math.round(v * 100) / 100;
  if (Object.is(r, -0)) r = 0;
  const s = Number.isInteger(r) ? String(r) : r.toFixed(1);
  return `${r > 0 ? "+" : ""}${s}%`;
}

/* ── 리밸런싱 이력: 시점별 편입/편출 델타 ─────────────────────────────── */

const REBAL_MIN_DELTA = 0.5; // %p 이상 변동만 증감으로 취급

interface DeltaItem {
  name: string;
  cat1: string;
  delta: number; // %p (신규=+비중, 편출=−이전비중, 증감=Δ)
  kind: "new" | "up" | "down" | "out";
}
interface RebalDelta {
  key: string; // "aicoretech" | "torus"
  date: string;
  isFirst: boolean;
  nHoldings: number;
  cashPct: number;
  added: DeltaItem[]; // 신규편입 + 비중확대
  removed: DeltaItem[]; // 편출 + 비중축소
  top: { name: string; cat1: string; weight: number }[]; // 최초구성 상위
}
interface Marker {
  key: string; // 펀드 id
  date: string;
  color: string; // 그 펀드의 선 색 (삼각형도 같은 색)
  title: string; // 삼각형 네이티브 툴팁 요약
}

// 인접 리밸 시점 비교 → 편입/편출 델타. events 는 오름차순 정렬 후 사용.
function computeDeltas(key: string, series: RebalSeries | undefined): RebalDelta[] {
  if (!series?.events?.length) return [];
  const evs = [...series.events].sort((a, b) => a.date.localeCompare(b.date));
  const out: RebalDelta[] = [];
  for (let i = 0; i < evs.length; i++) {
    const cur = evs[i];
    if (i === 0) {
      const top = [...cur.holdings]
        .sort((a, b) => b.weight_pct - a.weight_pct)
        .slice(0, 6)
        .map((h) => ({ name: h.name, cat1: h.cat1, weight: h.weight_pct }));
      out.push({
        key, date: cur.date, isFirst: true, nHoldings: cur.n_holdings,
        cashPct: cur.cash_pct, added: [], removed: [], top,
      });
      continue;
    }
    const prev = evs[i - 1];
    const prevMap = new Map(prev.holdings.map((h) => [h.name, h.weight_pct]));
    const curMap = new Map(cur.holdings.map((h) => [h.name, h.weight_pct]));
    const added: DeltaItem[] = [];
    const removed: DeltaItem[] = [];
    for (const h of cur.holdings) {
      const pw = prevMap.get(h.name);
      if (pw === undefined) {
        added.push({ name: h.name, cat1: h.cat1, delta: h.weight_pct, kind: "new" });
      } else {
        const d = h.weight_pct - pw;
        if (d >= REBAL_MIN_DELTA) added.push({ name: h.name, cat1: h.cat1, delta: d, kind: "up" });
        else if (d <= -REBAL_MIN_DELTA) removed.push({ name: h.name, cat1: h.cat1, delta: d, kind: "down" });
      }
    }
    for (const h of prev.holdings) {
      if (!curMap.has(h.name))
        removed.push({ name: h.name, cat1: h.cat1, delta: -h.weight_pct, kind: "out" });
    }
    added.sort((a, b) => b.delta - a.delta);
    removed.sort((a, b) => a.delta - b.delta);
    out.push({
      key, date: cur.date, isFirst: false, nHoldings: cur.n_holdings,
      cashPct: cur.cash_pct, added, removed, top: [],
    });
  }
  return out;
}

// 대분류 비중 변화(직전 리밸 대비): prev/cur cats(대분류 소계) 병합 diff.
interface CatChange {
  cat1: string;
  prevW: number;
  curW: number;
  delta: number;
}
function diffCats(
  prev: RebalCat[] | undefined,
  cur: RebalCat[] | undefined,
): CatChange[] {
  const pm = new Map((prev ?? []).map((c) => [c.name, c.weight_pct]));
  const cm = new Map((cur ?? []).map((c) => [c.name, c.weight_pct]));
  const out: CatChange[] = [];
  for (const nm of new Set([...pm.keys(), ...cm.keys()])) {
    const pw = pm.get(nm) ?? 0;
    const cw = cm.get(nm) ?? 0;
    out.push({ cat1: nm, prevW: pw, curW: cw, delta: cw - pw });
  }
  out.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || b.curW - a.curW);
  return out;
}

// 선택된 리밸 시점의 상세(변경내역 + 전후 성과) 조립 결과.
interface RebalDetailData {
  key: string;
  date: string;
  isFirst: boolean;
  cur: RebalEvent;
  catChange: CatChange[];
  deltas: RebalDelta | null;
}

function markerTitle(rd: RebalDelta, label: string): string {
  if (rd.isFirst) return `${label} · ${dotDate(rd.date)} 최초 구성 · ${rd.nHoldings}종목`;
  const ins = rd.added.slice(0, 3).map((d) => d.name).join(", ") || "—";
  const outs = rd.removed.slice(0, 3).map((d) => d.name).join(", ") || "—";
  return `${label} · ${dotDate(rd.date)} 리밸 · 편입 ${ins} / 편출 ${outs}`;
}

// dates 오름차순에서 d 이하인 마지막 인덱스(as-of). 창 왼쪽 밖이면 -1.
function asofIndex(dates: string[], d: string): number {
  let idx = -1;
  for (let i = 0; i < dates.length; i++) {
    if (dates[i] <= d) idx = i;
    else break;
  }
  return idx;
}

/* ── 페이지 ───────────────────────────────────────────────────────────── */

export default function TorusAicoretechPage() {
  const query = useQuery({
    queryKey: ["fundSeries"],
    queryFn: getFundSeries,
    refetchInterval: 60000,
    retry: false,
  });
  const data = query.data;

  // 범례에서 끈 펀드. 기본은 등록된 것 전부 표시.
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const toggleFund = (id: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const model = useMemo(() => buildModel(data, hidden), [data, hidden]);
  const D = useMemo(() => model?.D ?? [], [model]);

  const [period, setPeriod] = useState<Period>({ kind: "recent", months: 3 });
  // 직접지정 date input 로컬 상태 (프리셋 클릭 시 "" 로 초기화되어 윈도우로 스냅백).
  const [cStart, setCStart] = useState("");
  const [cEnd, setCEnd] = useState("");

  const win = useMemo(() => computeWindow(period, D), [period, D]);
  const plot = useMemo(
    () => (model ? buildPlot(model, win) : null),
    [model, win],
  );

  const MONTHS = useMemo(() => monthsOf(D), [D]);

  // ── 리밸런싱 이력 (별도 소스: 리밸런싱_히스토리 시트) ──
  const rebalQuery = useQuery({
    queryKey: ["wrapRebalancing"],
    queryFn: getInavWrapRebalancing,
    refetchInterval: 60000,
    retry: false,
  });
  const rebalAi = useMemo(
    () => computeDeltas(SELF_ID, rebalQuery.data?.portfolios?.[SELF_ID]),
    [rebalQuery.data],
  );
  const rebalTr = useMemo(
    () => computeDeltas(BM_ID, rebalQuery.data?.portfolios?.[BM_ID]),
    [rebalQuery.data],
  );

  const [pfFilter, setPfFilter] = useState<"all" | "aicoretech" | "torus">("all");
  const [selEvent, setSelEvent] = useState<{ key: string; date: string } | null>(null);

  // 필터 반영한 리밸 목록(패널: 최신순) + 마커(차트 오버레이).
  const rebalFiltered = useMemo(() => {
    const src: RebalDelta[] = [];
    if (pfFilter !== "torus") src.push(...rebalAi);
    if (pfFilter !== "aicoretech") src.push(...rebalTr);
    return src;
  }, [rebalAi, rebalTr, pfFilter]);
  // 마커는 차트에 그려진 펀드에서 나온다(범례로 끄면 마커도 사라진다). 편입 구성까지
  // 아는 두 포트폴리오는 풍부한 요약을, 나머지는 이름과 날짜만 보여 준다.
  const markers = useMemo<Marker[]>(() => {
    const lines = model?.lines ?? [];
    const labelOf = new Map(lines.map((l) => [l.id, l.label]));
    const rich = new Map<string, string>();
    for (const rd of [...rebalAi, ...rebalTr]) {
      rich.set(`${rd.key}|${rd.date}`, markerTitle(rd, labelOf.get(rd.key) ?? rd.key));
    }
    const out: Marker[] = [];
    for (const ln of lines) {
      const f = data?.funds.find((x) => x.id === ln.id);
      for (const d of f?.rebalancing ?? []) {
        out.push({
          key: ln.id,
          date: d,
          color: ln.color,
          title: rich.get(`${ln.id}|${d}`) ?? `${ln.label} · ${dotDate(d)} 리밸`,
        });
      }
    }
    return out;
  }, [model, data, rebalAi, rebalTr]);
  const panelList = useMemo(
    () =>
      [...rebalFiltered].sort(
        (a, b) => b.date.localeCompare(a.date) || a.key.localeCompare(b.key),
      ),
    [rebalFiltered],
  );

  const onSelectMarker = (key: string, date: string) => setSelEvent({ key, date });

  // 선택된 리밸 시점 상세 조립(변경내역 + cats + perf).
  const detail = useMemo<RebalDetailData | null>(() => {
    if (!selEvent) return null;
    const series = rebalQuery.data?.portfolios?.[selEvent.key];
    if (!series) return null;
    const evs = [...series.events].sort((a, b) => a.date.localeCompare(b.date));
    const i = evs.findIndex((e) => e.date === selEvent.date);
    if (i < 0) return null;
    const cur = evs[i];
    const prev = i > 0 ? evs[i - 1] : null;
    const deltas =
      (selEvent.key === SELF_ID ? rebalAi : rebalTr).find(
        (r) => r.date === selEvent.date,
      ) ?? null;
    return {
      key: selEvent.key,
      date: selEvent.date,
      isFirst: i === 0,
      cur,
      catChange: diffCats(prev?.cats, cur.cats),
      deltas,
    };
  }, [selEvent, rebalQuery.data, rebalAi, rebalTr]);

  return (
    <>
      <Topbar
        title="TORUS / AI테크"
        subtitle="성과 분석 · 등록된 펀드 누적수익률 비교"
        status={
          data ? (
            <span className="truncate text-[11px] text-slate-400">
              최근 갱신 {data.generatedAt}
            </span>
          ) : undefined
        }
      />
      <PageContainer wide>
        {query.isError && (
          <div className="mb-4">
            <ApiErrorBanner error={query.error} />
          </div>
        )}

        {/* 성과 비교 차트 카드 */}
        <section className="overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
          <div className="h-2 rounded-t-2xl bg-ge-point" />
          <div className="px-5 pb-5 pt-4">
            <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
              <div className="flex items-center gap-2">
                <span className="h-4 w-1.5 rounded-full bg-ge-point" />
                <span className="text-[14px] font-extrabold text-ge-navy">
                  누적 수익률 비교
                </span>
                {data && data.funds.length > 0 && (
                  <span className="text-[11.5px] text-ink-faint">
                    펀드 {data.funds.length - hidden.size}/{data.funds.length}
                  </span>
                )}
              </div>
              {plot && (
                <div className="ml-auto">
                  <PeriodControls
                    period={period}
                    setPeriod={setPeriod}
                    months={MONTHS}
                    D={D}
                    plotDates={plot.dates}
                    cStart={cStart}
                    cEnd={cEnd}
                    setCStart={setCStart}
                    setCEnd={setCEnd}
                  />
                </div>
              )}
            </div>

            {query.isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-9 w-full max-w-md rounded-lg" />
                <Skeleton className="h-[340px] w-full rounded-xl" />
              </div>
            ) : !plot ? (
              <div className="flex h-[340px] flex-col items-center justify-center gap-1.5 text-center text-sm text-ink-muted">
                {!data?.funds.length ? (
                  <>
                    <span className="font-bold text-ge-navy">등록된 펀드가 없습니다</span>
                    <span className="text-[12.5px]">
                      S: 성과분석 폴더에서 register_funds.py 로 엑셀을 등록한 뒤
                      build_funds.py 를 돌리면 여기에 뜹니다.
                    </span>
                  </>
                ) : (
                  <span>범례에서 펀드를 하나 이상 켜 주세요.</span>
                )}
              </div>
            ) : (
              <ReadyChart
                plot={plot}
                funds={data?.funds ?? []}
                hidden={hidden}
                onToggle={toggleFund}
                markers={markers}
                selEvent={selEvent}
                onSelectMarker={onSelectMarker}
              />
            )}
          </div>
        </section>

        {/* 리밸런싱 성과분석 (마커/칩 클릭 → 해당 시점 상세) */}
        <RebalAnalysis
          chips={panelList}
          pfFilter={pfFilter}
          setPfFilter={setPfFilter}
          detail={detail}
          selEvent={selEvent}
          setSelEvent={setSelEvent}
          isLoading={rebalQuery.isLoading}
          isError={rebalQuery.isError}
        />

        {/* 성과보고 (월=위클리 / 화~금=데일리) — S: bat 이 만든 HTML 을 iframe 렌더 */}
        <PerfReportCard />
      </PageContainer>
    </>
  );
}

/* ── 준비 완료 상태: 헤더 스트립 + 컨트롤 + 차트 + 범례 ───────────────── */

function ReadyChart({
  plot,
  funds,
  hidden,
  onToggle,
  markers,
  selEvent,
  onSelectMarker,
}: {
  plot: Plot;
  funds: { id: string; label: string; inception: string; lastDate: string }[];
  hidden: Set<string>;
  onToggle: (id: string) => void;
  markers: Marker[];
  selEvent: { key: string; date: string } | null;
  onSelectMarker: (key: string, date: string) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(760);

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

  const winStart = plot.dates[0] ?? "";
  const winEnd = plot.dates[plot.dates.length - 1] ?? "";

  return (
    <div className="space-y-3">
      {/* 헤더 스트립: 윈도우 범위 (기준일). 우측 인셉션·최종데이터 멘트 제거 —
          최종일은 이 범위 텍스트로 파악. 컨트롤은 카드 제목 줄로 이동. */}
      <div className="text-[12.5px] text-ink-secondary">
        <span className="font-bold text-ge-navy">
          {dotDate(winStart)} ~ {dotDate(winEnd)}
        </span>
        <span className="ml-2 text-ink-muted">
          · 기준 {dotDate(winStart)} = 0%
        </span>
      </div>

      {/* 차트 */}
      <div ref={wrapRef} className="w-full">
        {w > 0 && (
          <PerfChart
            plot={plot}
            w={w}
            markers={markers}
            selEvent={selEvent}
            onSelectMarker={onSelectMarker}
          />
        )}
      </div>

      {/* 범례 + 윈도우 수익률. 등록된 펀드를 전부 보여 주고, 클릭하면 선을 껐다 켠다.
          숨긴 펀드도 목록에 남아야 다시 켤 수 있다. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline pt-3">
        {funds.map((f) => {
          const ln = plot.lines.find((l) => l.id === f.id);
          const off = hidden.has(f.id);
          const finite = (ln?.vals ?? []).filter(
            (v): v is number => v != null && Number.isFinite(v),
          );
          const ret = finite.length ? finite[finite.length - 1] : null;
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => onToggle(f.id)}
              title={
                off
                  ? "클릭하면 그래프에 표시합니다"
                  : `${dotDate(f.inception)} ~ ${dotDate(f.lastDate)} · 클릭하면 숨깁니다`
              }
              className={cn(
                "flex items-center gap-2 rounded-md px-1.5 py-0.5 transition hover:bg-canvas-soft",
                off && "opacity-40",
              )}
            >
              <span
                className="inline-block h-2.5 w-4 rounded-full"
                style={{ background: ln?.color ?? "#c9d1dd" }}
              />
              <span className="text-[12.5px] font-bold text-ge-navy">{f.label}</span>
              {off ? (
                <span className="text-[11px] text-ink-faint">숨김</span>
              ) : (
                <span
                  className="text-[13px] font-extrabold tabular-nums"
                  style={{ color: signColor(ret) }}
                >
                  {signedPct(ret)}
                </span>
              )}
            </button>
          );
        })}
        {markers.length > 0 && (
          <span className="flex items-center gap-1 text-[11px] text-ink-faint">
            <span>▲</span> 곡선 위 리밸 시점 · hover→시기선 · 클릭→상세
          </span>
        )}
        <span className="ml-auto text-[11px] text-ink-faint">
          기간 수익률 · 기준 {dotDate(winStart)} = 0%
        </span>
      </div>
    </div>
  );
}

/* ── 기간/날짜 컨트롤 (카드 제목 줄 우측) ─────────────────────────────── */

function PeriodControls({
  period,
  setPeriod,
  months,
  D,
  plotDates,
  cStart,
  cEnd,
  setCStart,
  setCEnd,
}: {
  period: Period;
  setPeriod: (p: Period) => void;
  months: string[];
  D: string[];
  plotDates: string[];
  cStart: string;
  cEnd: string;
  setCStart: (v: string) => void;
  setCEnd: (v: string) => void;
}) {
  const winStart = plotDates[0] ?? "";
  const winEnd = plotDates[plotDates.length - 1] ?? "";
  const domainStart = D[0] ?? "";
  const domainEnd = D[D.length - 1] ?? "";
  const startVal = cStart || winStart;
  const endVal = cEnd || winEnd;

  const applyStart = (v: string) => {
    setCStart(v);
    const end = cEnd || winEnd;
    if (v && end && v <= end) setPeriod({ kind: "custom", start: v, end });
  };
  const applyEnd = (v: string) => {
    setCEnd(v);
    const start = cStart || winStart;
    if (v && start && start <= v) setPeriod({ kind: "custom", start, end: v });
  };
  const preset = (p: Period) => {
    setCStart("");
    setCEnd("");
    setPeriod(p);
  };

  const is1M = period.kind === "recent" && period.months === 1;
  const is3M = period.kind === "recent" && period.months === 3;
  const is6M = period.kind === "recent" && period.months === 6;
  const is1Y = period.kind === "recent" && period.months === 12;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex overflow-hidden rounded-lg border border-hairline bg-canvas-soft p-0.5">
        <PeriodBtn active={is1M} onClick={() => preset({ kind: "recent", months: 1 })}>
          1M
        </PeriodBtn>
        <PeriodBtn active={is3M} onClick={() => preset({ kind: "recent", months: 3 })}>
          3M
        </PeriodBtn>
        <PeriodBtn active={is6M} onClick={() => preset({ kind: "recent", months: 6 })}>
          6M
        </PeriodBtn>
        <PeriodBtn active={is1Y} onClick={() => preset({ kind: "recent", months: 12 })}>
          1Y
        </PeriodBtn>
      </div>

      <select
        value={period.kind === "month" ? period.m : ""}
        onChange={(e) => {
          const m = e.target.value;
          setCStart("");
          setCEnd("");
          if (m) setPeriod({ kind: "month", m });
        }}
        className="rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ge-navy outline-none focus:border-ge-point"
      >
        <option value="">월별 선택</option>
        {months.map((m) => (
          <option key={m} value={m}>
            {fmtMonth(m)}
          </option>
        ))}
      </select>

      <div className="flex items-center gap-1.5 text-[12px] text-ink-muted">
        <input
          type="date"
          value={startVal}
          min={domainStart}
          max={domainEnd}
          onChange={(e) => applyStart(e.target.value)}
          className={cn(
            "rounded-lg border bg-canvas px-2 py-1.5 text-[12px] tabular-nums text-ge-navy outline-none focus:border-ge-point",
            period.kind === "custom" ? "border-ge-point" : "border-hairline",
          )}
        />
        <span>~</span>
        <input
          type="date"
          value={endVal}
          min={domainStart}
          max={domainEnd}
          onChange={(e) => applyEnd(e.target.value)}
          className={cn(
            "rounded-lg border bg-canvas px-2 py-1.5 text-[12px] tabular-nums text-ge-navy outline-none focus:border-ge-point",
            period.kind === "custom" ? "border-ge-point" : "border-hairline",
          )}
        />
      </div>
    </div>
  );
}

function PeriodBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-[12px] font-bold transition-colors",
        active
          ? "bg-ge-point text-white shadow-sm"
          : "text-ink-muted hover:text-ge-point",
      )}
    >
      {children}
    </button>
  );
}

/* ── SVG 차트 (반응형, 호버 툴팁) ─────────────────────────────────────── */

const H = 340;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 14;
const PAD_B = 26;

function PerfChart({
  plot,
  w,
  markers,
  selEvent,
  onSelectMarker,
}: {
  plot: Plot;
  w: number;
  markers: Marker[];
  selEvent: { key: string; date: string } | null;
  onSelectMarker: (key: string, date: string) => void;
}) {
  const [hoverI, setHoverI] = useState<number | null>(null);
  const [hoverMarker, setHoverMarker] = useState<{
    x: number;
    key: string;
    date: string;
    color: string;
    label: string;
  } | null>(null);

  const iw = Math.max(1, w - PAD_L - PAD_R);
  const ih = H - PAD_T - PAD_B;
  const n = plot.dates.length;
  const denomX = Math.max(1, n - 1);
  const { mn, mx } = plot;
  const spanY = mx - mn || 1;

  const X = (i: number) => PAD_L + (iw * i) / denomX;
  const Y = (v: number) => PAD_T + (ih * (mx - v)) / spanY;

  // Y 그리드
  const step = niceStep((mx - mn) / 5);
  const gridVals: number[] = [];
  for (let g = Math.ceil(mn / step) * step; g <= mx + 1e-9; g += step) {
    gridVals.push(g);
  }
  const showZero = mn < 0 && mx > 0;

  // X 월 눈금 (윈도우 내 거래일 4일 미만인 달은 생략)
  const monthTicks = useMemo(() => {
    const firstIdx = new Map<string, number>();
    const counts = new Map<string, number>();
    plot.dates.forEach((d, i) => {
      const m = d.slice(0, 7);
      counts.set(m, (counts.get(m) ?? 0) + 1);
      if (!firstIdx.has(m)) firstIdx.set(m, i);
    });
    const out: { i: number; label: string }[] = [];
    for (const [m, i] of firstIdx) {
      if ((counts.get(m) ?? 0) >= 4) {
        out.push({ i, label: `${Number(m.slice(5, 7))}월` });
      }
    }
    return out;
  }, [plot.dates]);

  // 리밸런싱 마커: 리밸 날짜를 창 내 as-of 거래일 인덱스에 매핑(창 밖·값 없는 시점 제외).
  // 삼각형을 해당 포트폴리오 곡선 위에 얹기 위해 그 시점 라인 값이 있어야 한다.
  const markerHits = useMemo(() => {
    const first = plot.dates[0] ?? "";
    const last = plot.dates[plot.dates.length - 1] ?? "";
    const out: { mk: Marker; idx: number }[] = [];
    for (const mk of markers) {
      const idx = asofIndex(plot.dates, mk.date);
      if (idx < 0 || mk.date < first || mk.date > last) continue;
      const line = plot.lines.find((l) => l.id === mk.key);
      const v = line?.vals[idx];
      if (v == null || !Number.isFinite(v)) continue;
      out.push({ mk, idx });
    }
    return out;
  }, [markers, plot.dates, plot.lines]);

  // 폴리라인 세그먼트 (null 은 선을 끊는다)
  const segsOf = (vals: (number | null)[]): string[] => {
    const segs: string[] = [];
    let cur: string[] = [];
    vals.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) {
        if (cur.length) {
          segs.push(cur.join(" "));
          cur = [];
        }
      } else {
        cur.push(`${X(i).toFixed(1)},${Y(v).toFixed(1)}`);
      }
    });
    if (cur.length) segs.push(cur.join(" "));
    return segs;
  };

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const x = ((e.clientX - rect.left) / rect.width) * w;
    let i = Math.round(((x - PAD_L) / iw) * denomX);
    i = Math.max(0, Math.min(n - 1, i));
    setHoverI(i);
  };

  // 그 시점에 값이 있는 선만 툴팁에 올린다(인셉션 전 구간은 null).
  const hoverRows =
    hoverI == null
      ? []
      : plot.lines
          .map((ln) => ({ ln, v: ln.vals[hoverI] ?? null }))
          .filter((r) => r.v != null && Number.isFinite(r.v));
  // 두 개만 보고 있을 때는 차이를 같이 보여 준다. 셋 이상이면 무엇에서 무엇을 뺀 값인지
  // 모호해지므로 넣지 않는다.
  const spread =
    hoverRows.length === 2
      ? (hoverRows[0].v as number) - (hoverRows[1].v as number)
      : null;
  const hx = hoverI != null ? X(hoverI) : 0;
  const tipRight = hx > w / 2;

  // 빨간 세로선 + 리밸 라벨: 마커 hover 우선, 없으면 선택된 마커.
  const selHit = selEvent
    ? markerHits.find(
        (h) => h.mk.key === selEvent.key && h.mk.date === selEvent.date,
      )
    : undefined;
  const activeMk = hoverMarker
    ? {
        date: hoverMarker.date,
        x: hoverMarker.x,
        color: hoverMarker.color,
        label: hoverMarker.label,
      }
    : selHit
      ? {
          date: selHit.mk.date,
          x: X(selHit.idx),
          color: selHit.mk.color,
          label:
            plot.lines.find((l) => l.id === selHit.mk.key)?.label ?? selHit.mk.key,
        }
      : null;
  const redX = activeMk ? activeMk.x : null;

  return (
    <div className="relative w-full">
      <svg
        width="100%"
        height={H}
        viewBox={`0 0 ${w} ${H}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverI(null)}
        style={{ display: "block" }}
      >
        {/* Y 그리드 + 라벨 */}
        {gridVals.map((g) => (
          <g key={`g-${g}`}>
            <line
              x1={PAD_L}
              y1={Y(g)}
              x2={w - PAD_R}
              y2={Y(g)}
              stroke="#EDF0F5"
              strokeWidth={1}
            />
            <text
              x={PAD_L - 8}
              y={Y(g) + 3.5}
              textAnchor="end"
              fontSize={10.5}
              fill="#8a94a6"
            >
              {fmtTick(g)}
            </text>
          </g>
        ))}

        {/* 0% 기준선 (음/양 걸칠 때만 강조 점선) */}
        {showZero && (
          <line
            x1={PAD_L}
            y1={Y(0)}
            x2={w - PAD_R}
            y2={Y(0)}
            stroke="#B7C0CE"
            strokeWidth={1}
            strokeDasharray="4 3"
          />
        )}

        {/* X 월 눈금 */}
        {monthTicks.map((t) => (
          <g key={`x-${t.i}`}>
            <line
              x1={X(t.i)}
              y1={H - PAD_B}
              x2={X(t.i)}
              y2={H - PAD_B + 4}
              stroke="#c9d1dd"
              strokeWidth={1}
            />
            <text
              x={X(t.i)}
              y={H - PAD_B + 15}
              textAnchor="middle"
              fontSize={10.5}
              fill="#8a94a6"
            >
              {t.label}
            </text>
          </g>
        ))}

        {/* 호버 세로 가이드 (마커 위에선 숨김 — 빨간선이 대신) */}
        {hoverI != null && hoverMarker == null && (
          <line
            x1={hx}
            y1={PAD_T}
            x2={hx}
            y2={H - PAD_B}
            stroke="#B7C0CE"
            strokeWidth={1}
          />
        )}

        {/* 리밸 시점 빨간 세로선 (삼각형 hover 또는 선택 시, y축 평행) */}
        {redX != null && (
          <line
            x1={redX}
            y1={PAD_T}
            x2={redX}
            y2={H - PAD_B}
            stroke="#e5484d"
            strokeWidth={1.5}
          />
        )}

        {/* 폴리라인 */}
        {plot.lines.map((ln) =>
          segsOf(ln.vals).map((pts, si) => (
            <polyline
              key={`${ln.id}-${si}`}
              points={pts}
              fill="none"
              stroke={ln.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          )),
        )}

        {/* 리밸런싱 마커 (해당 포트 곡선 위 채운 삼각형, hover→빨간선 / 클릭→상세) */}
        {markerHits.map(({ mk, idx }) => {
          const x = X(idx);
          const line = plot.lines.find((l) => l.id === mk.key);
          const v = line?.vals[idx];
          if (v == null || !Number.isFinite(v)) return null;
          const y = Y(v);
          const color = mk.color;
          const isSel = selEvent?.key === mk.key && selEvent?.date === mk.date;
          const s = isSel ? 6.5 : 5; // 삼각형 반너비
          return (
            <g
              key={`mk-${mk.key}-${mk.date}`}
              style={{ cursor: "pointer" }}
              onMouseEnter={() =>
                setHoverMarker({
                  x,
                  key: mk.key,
                  date: mk.date,
                  color,
                  label: line?.label ?? mk.key,
                })
              }
              onMouseLeave={() => setHoverMarker(null)}
              onClick={(e) => {
                e.stopPropagation();
                onSelectMarker(mk.key, mk.date);
              }}
            >
              <title>{mk.title}</title>
              {/* 히트영역 확대 */}
              <rect x={x - 8} y={y - 12} width={16} height={20} fill="transparent" />
              {/* 위를 향하는 채운 삼각형, 곡선 점 위에 얹음 */}
              <path
                d={`M ${x} ${y - s - 2} L ${x - s} ${y + s - 2} L ${x + s} ${y + s - 2} Z`}
                fill={color}
                stroke="#ffffff"
                strokeWidth={isSel ? 1.8 : 1.2}
              />
            </g>
          );
        })}

        {/* 호버 점 (장식 — 마커 hover 가리지 않도록 pointer-events 제거) */}
        {hoverI != null &&
          plot.lines.map((ln) => {
            const v = ln.vals[hoverI];
            if (v == null || !Number.isFinite(v)) return null;
            return (
              <circle
                key={`dot-${ln.id}`}
                cx={X(hoverI)}
                cy={Y(v)}
                r={3.5}
                fill={ln.color}
                stroke="#ffffff"
                strokeWidth={1.5}
                style={{ pointerEvents: "none" }}
              />
            );
          })}
      </svg>

      {/* 리밸 유형 라벨 (빨간선 상단 텍스트 박스) */}
      {activeMk && redX != null && (
        <div
          className="pointer-events-none absolute top-0 z-20 -translate-x-1/2 whitespace-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-bold text-white shadow-sm"
          style={{
            left: Math.max(74, Math.min(redX, w - 74)),
            background: activeMk.color,
          }}
        >
          {activeMk.label} 리밸 · {dotDate(activeMk.date)}
        </div>
      )}

      {/* 툴팁 (마커 hover 중엔 리밸 라벨이 대신) */}
      {hoverI != null && hoverMarker == null && (
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
            {dotDate(plot.dates[hoverI])}
          </div>
          <div className="space-y-0.5">
            {hoverRows.map(({ ln, v }) => (
              <TipRow key={ln.id} color={ln.color} label={ln.label} v={v} />
            ))}
            {spread != null && (
              <div className="mt-1 flex items-center justify-between gap-4 border-t border-hairline pt-1 text-[11px]">
                <span className="text-ink-muted">
                  {hoverRows[0].ln.label}−{hoverRows[1].ln.label}
                </span>
                <span
                  className="font-extrabold tabular-nums"
                  style={{ color: signColor(spread) }}
                >
                  {signedPct(spread)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TipRow({
  color,
  label,
  v,
}: {
  color: string;
  label: string;
  v: number | null;
}) {
  return (
    <div className="flex items-center justify-between gap-4 text-[11.5px]">
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: color }}
        />
        <span className="text-ink-secondary">{label}</span>
      </span>
      <span
        className="font-bold tabular-nums"
        style={{ color: signColor(v) }}
      >
        {signedPct(v)}
      </span>
    </div>
  );
}

/* ── 리밸런싱 성과분석 (시점 선택 → 상세) ─────────────────────────────── */

function RebalAnalysis({
  chips,
  pfFilter,
  setPfFilter,
  detail,
  selEvent,
  setSelEvent,
  isLoading,
  isError,
}: {
  chips: RebalDelta[];
  pfFilter: "all" | "aicoretech" | "torus";
  setPfFilter: (v: "all" | "aicoretech" | "torus") => void;
  detail: RebalDetailData | null;
  selEvent: { key: string; date: string } | null;
  setSelEvent: (v: { key: string; date: string } | null) => void;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section
      id="rebal-analysis"
      className="mt-4 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card"
    >
      <div className="h-2 rounded-t-2xl bg-ge-navy" />
      <div className="px-5 pb-5 pt-4">
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex items-center gap-2">
            <span className="h-4 w-1.5 rounded-full bg-ge-navy" />
            <span className="text-[14px] font-extrabold text-ge-navy">
              리밸런싱 성과분석
            </span>
          </div>
          <div className="ml-auto inline-flex overflow-hidden rounded-lg border border-hairline bg-canvas-soft p-0.5">
            <FilterBtn active={pfFilter === "all"} onClick={() => setPfFilter("all")}>
              전체
            </FilterBtn>
            <FilterBtn active={pfFilter === "aicoretech"} onClick={() => setPfFilter("aicoretech")}>
              자사
            </FilterBtn>
            <FilterBtn active={pfFilter === "torus"} onClick={() => setPfFilter("torus")}>
              TORUS
            </FilterBtn>
          </div>
        </div>

        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : isError || chips.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-center text-sm text-ink-muted">
            리밸런싱 데이터를 불러올 수 없습니다.
          </div>
        ) : (
          <>
            {/* 리밸 시점 드롭다운 (포트별 optgroup) */}
            <div className="mb-4">
              <select
                value={selEvent ? `${selEvent.key}|${selEvent.date}` : ""}
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) {
                    setSelEvent(null);
                    return;
                  }
                  const [key, date] = v.split("|");
                  setSelEvent({ key, date });
                }}
                className="w-full max-w-xs rounded-lg border border-hairline bg-canvas px-3 py-2 text-[13px] font-semibold text-ge-navy outline-none focus:border-ge-point"
              >
                <option value="">리밸 시점 선택…</option>
                {chips.some((c) => c.key === SELF_ID) && (
                  <optgroup label="자사 (AI코어테크랩)">
                    {chips
                      .filter((c) => c.key === SELF_ID)
                      .map((c) => (
                        <option key={c.date} value={`${c.key}|${c.date}`}>
                          {dotDate(c.date)}
                        </option>
                      ))}
                  </optgroup>
                )}
                {chips.some((c) => c.key === BM_ID) && (
                  <optgroup label="TORUS (BM)">
                    {chips
                      .filter((c) => c.key === BM_ID)
                      .map((c) => (
                        <option key={c.date} value={`${c.key}|${c.date}`}>
                          {dotDate(c.date)}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            </div>

            {detail ? (
              <RebalDetail detail={detail} />
            ) : (
              <div className="flex h-28 items-center justify-center px-4 text-center text-[13px] leading-relaxed text-ink-muted">
                위 그래프의 삼각형(리밸 시점) 또는 상단 날짜 칩을 클릭하면
                <br />
                해당 리밸런싱의 성과분석이 여기 표시됩니다.
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function FilterBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-[12px] font-bold transition-colors",
        active ? "bg-ge-navy text-white shadow-sm" : "text-ink-muted hover:text-ge-navy",
      )}
    >
      {children}
    </button>
  );
}

function RebalDetail({ detail }: { detail: RebalDetailData }) {
  const { key, date, isFirst, cur, catChange, deltas } = detail;
  // 이 패널은 편입 구성 이력이 있는 두 포트폴리오 전용이라 이름·색을 그대로 둔다.
  const who = key === SELF_ID ? "자사(AI코어테크랩)" : "TORUS(BM)";
  const color = PINNED_COLOR[key] ?? "#243b5e";
  const aft = cur.perf?.after ?? null;
  const bef = cur.perf?.before ?? null;
  return (
    <div className="space-y-3.5">
      {/* 헤더 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[15px] font-extrabold text-ge-navy">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: color }}
          />
          {dotDate(date)} 리밸런싱
        </span>
        <span className="text-[12px] text-ink-muted">{who}</span>
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-muted">
          <Badge>{cur.n_holdings}종목</Badge>
          <Badge>현금 {cur.cash_pct.toFixed(1)}%</Badge>
        </span>
      </div>

      {/* ① 변경 내역 */}
      <DetailBlock n="01" title="리밸런싱 변경 내역">
        {isFirst || !deltas || deltas.isFirst ? (
          <div className="text-[12px] text-ink-muted">
            최초 구성 시점 — 직전 대비 변동 없음
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-x-5 gap-y-3 sm:grid-cols-2">
            <DeltaCol title="편입 ▲ (신규·확대)" items={deltas.added} />
            <DeltaCol title="편출 ▼ (제외·축소)" items={deltas.removed} />
          </div>
        )}
        {catChange.length > 0 && (
          <div className="mt-3 border-t border-hairline pt-3">
            <div className="mb-1.5 text-[11px] font-bold text-ink-secondary">
              대분류 비중 변화
            </div>
            <div className="space-y-1">
              {catChange.map((c) => (
                <div key={c.cat1} className="flex items-center gap-2 text-[11.5px]">
                  <span className="w-28 shrink-0 truncate font-semibold text-ge-navy">
                    {c.cat1}
                  </span>
                  <span className="tabular-nums text-ink-muted">
                    {c.prevW.toFixed(1)}% → {c.curW.toFixed(1)}%
                  </span>
                  <span
                    className="ml-auto font-bold tabular-nums"
                    style={{ color: signColor(c.delta) }}
                  >
                    {signedPct(c.delta, 1)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </DetailBlock>

      {/* ② 전후 1주 성과 */}
      <DetailBlock n="02" title="리밸 전후 1주 성과 (수익률 · 분류별 기여)">
        {!aft && !bef ? (
          <div className="text-[12px] text-ink-muted">
            해당 구간 가격 데이터가 없어 계산할 수 없습니다.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <WindowPerf title="리밸 전 1주 (직전 구성)" win={bef} />
            <WindowPerf title="리밸 후 1주 (신규 구성)" win={aft} />
          </div>
        )}
      </DetailBlock>

      {/* ③ 리밸 후 기여 top5 */}
      {aft && aft.top.length > 0 && (
        <DetailBlock n="03" title="리밸 후 1주 기여도 상위 종목">
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-ink-muted">
                  <th className="py-1 text-left font-semibold">종목</th>
                  <th className="py-1 text-left font-semibold">대분류</th>
                  <th className="py-1 text-right font-semibold">비중</th>
                  <th className="py-1 text-right font-semibold">수익률</th>
                  <th className="py-1 text-right font-semibold">기여도</th>
                </tr>
              </thead>
              <tbody>
                {aft.top.map((t) => (
                  <tr key={t.name} className="border-t border-hairline">
                    <td className="py-1 pr-2 font-semibold text-ge-navy">{t.name}</td>
                    <td className="py-1 pr-2 text-ink-muted">{t.cat1}</td>
                    <td className="py-1 text-right tabular-nums text-ink-secondary">
                      {t.weight_pct.toFixed(1)}%
                    </td>
                    <td
                      className="py-1 text-right tabular-nums"
                      style={{ color: signColor(t.ret_pct) }}
                    >
                      {signedPct(t.ret_pct, 1)}
                    </td>
                    <td
                      className="py-1 text-right font-bold tabular-nums"
                      style={{ color: signColor(t.contrib_pct) }}
                    >
                      {signedPct(t.contrib_pct, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-1 text-[10.5px] text-ink-faint">
            가격보유 {aft.priced_n}/{aft.total_n}종목 기준 · 기여도 = 비중 × 종목수익률
          </div>
        </DetailBlock>
      )}
    </div>
  );
}

function WindowPerf({
  title,
  win,
}: {
  title: string;
  win: RebalWindowPerf | null;
}) {
  if (!win) {
    return (
      <div className="rounded-xl border border-hairline bg-canvas-soft p-3">
        <div className="text-[11px] font-bold text-ink-secondary">{title}</div>
        <div className="mt-2 text-[12px] text-ink-muted">데이터 없음</div>
      </div>
    );
  }
  const maxAbs = Math.max(0.01, ...win.cats.map((c) => Math.abs(c.contrib_pct)));
  return (
    <div className="rounded-xl border border-hairline bg-canvas-soft p-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-bold text-ink-secondary">{title}</span>
        <span className="text-[10.5px] tabular-nums text-ink-faint">
          {dotDate(win.start).slice(5)}~{dotDate(win.end).slice(5)}
        </span>
      </div>
      <div
        className="mt-1 text-[18px] font-extrabold tabular-nums"
        style={{ color: signColor(win.ret_total) }}
      >
        {signedPct(win.ret_total, 2)}
      </div>
      <div className="mt-2 space-y-1">
        {win.cats.map((c) => {
          const frac = (Math.abs(c.contrib_pct) / maxAbs) * 50;
          const pos = c.contrib_pct >= 0;
          return (
            <div key={c.cat1} className="flex items-center gap-2 text-[11px]">
              <span className="w-24 shrink-0 truncate text-ink-secondary">
                {c.cat1}
              </span>
              <div className="relative h-3 flex-1">
                <div className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
                <div
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    background: pos ? POS : NEG,
                    left: pos ? "50%" : `${50 - frac}%`,
                    width: `${frac}%`,
                  }}
                />
              </div>
              <span
                className="w-12 shrink-0 text-right font-bold tabular-nums"
                style={{ color: signColor(c.contrib_pct) }}
              >
                {signedPct(c.contrib_pct, 2)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-1 text-[10px] text-ink-faint">
        가격 {win.priced_n}/{win.total_n}종목
      </div>
    </div>
  );
}

function DetailBlock({
  n,
  title,
  children,
}: {
  n: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-hairline bg-canvas p-3.5">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-5 w-5 place-items-center rounded bg-ge-navy text-[10px] font-bold text-white">
          {n}
        </span>
        <span className="text-[12.5px] font-extrabold text-ge-navy">{title}</span>
      </div>
      {children}
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-md bg-canvas-soft px-1.5 py-0.5 font-semibold tabular-nums">
      {children}
    </span>
  );
}

function DeltaCol({ title, items }: { title: string; items: DeltaItem[] }) {
  const shown = items.slice(0, 5);
  const more = items.length - shown.length;
  return (
    <div>
      <div className="mb-1 text-[11px] font-bold text-ink-secondary">{title}</div>
      {shown.length === 0 ? (
        <div className="text-[11.5px] text-ink-faint">변동 없음</div>
      ) : (
        <div className="space-y-1">
          {shown.map((it) => (
            <div
              key={`${it.kind}-${it.name}`}
              className="flex items-center justify-between gap-2 text-[11.5px]"
            >
              <span className="flex min-w-0 items-baseline gap-1.5">
                <span className="truncate font-semibold text-ge-navy">{it.name}</span>
                {it.cat1 && (
                  <span className="shrink-0 text-[10px] text-ink-faint">{it.cat1}</span>
                )}
                {it.kind === "new" && (
                  <span className="shrink-0 text-[9.5px] font-bold" style={{ color: POS }}>
                    신규
                  </span>
                )}
                {it.kind === "out" && (
                  <span className="shrink-0 text-[9.5px] font-bold" style={{ color: NEG }}>
                    편출
                  </span>
                )}
              </span>
              <span
                className="shrink-0 font-bold tabular-nums"
                style={{ color: signColor(it.delta) }}
              >
                {signedPct(it.delta, 1)}
              </span>
            </div>
          ))}
          {more > 0 && <div className="text-[10.5px] text-ink-faint">외 {more}종목</div>}
        </div>
      )}
    </div>
  );
}
