"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
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
// 리밸런싱_히스토리 시트에만 있다). 위 차트에서는 SELF_ID 를 처음 보여 줄 기본 펀드로만
// 쓴다(범례에서 다른 펀드를 고르면 그쪽으로 바뀐다).
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

/* ── 펀드 그룹: 펀드와 그 참조지수를 한 쌍으로 묶는다 ─────────────────────
   적재 규약이 `{id}` · `{id}-bm` 이라(funds_map) 접미사만 떼면 짝이 나온다. */
const BM_SUFFIX = "-bm";
function groupOf(id: string): string {
  return id.endsWith(BM_SUFFIX) ? id.slice(0, -BM_SUFFIX.length) : id;
}
/** 등록 순서(인셉션순) 그대로의 그룹 키 목록. */
function groupsOf(funds: { id: string }[]): string[] {
  const out: string[] = [];
  for (const f of funds) {
    const g = groupOf(f.id);
    if (!out.includes(g)) out.push(g);
  }
  return out;
}

/* 동시 표시 예외 — 아래 그룹끼리는 한 화면에 같이 올릴 수 있다.
 * 근거(2026-08-06 실측):
 *  ① 참조지수가 같은 지수다. 공통 첫날(2026-03-10) 기준으로 리베이스하면 두 참조지수의
 *     경로차가 최대 0.0000041%p — 저장된 누적수익률 반올림 수준이다. 그래서 참조지수는
 *     하나만 그린다(아래 buildModel 의 dedup).
 *  ② 날짜축이 겹친다. aicoretech 의 106 영업일이 torus 의 128 영업일에 전부 들어 있고,
 *     torus 에만 있는 22일은 모두 aicoretech 인셉션 이전이라 중간 결측이 없다. 둘 다
 *     주말 0일(전기차 펀드는 주말 60일 — 그래서 여전히 같이 못 올린다).
 * 새 펀드를 여기 넣기 전에 위 두 가지를 반드시 실측할 것. */
const COVIEW_GROUPS = ["torus", "aicoretech"];
const canCoview = (gs: string[]) => gs.every((g) => COVIEW_GROUPS.includes(g));

/** 등록된 펀드 → 비교 모델. 기본은 **한 그룹(펀드 + 그 참조지수)만** 그린다.
 *
 * 여러 펀드를 한 번에 올리면 날짜축이 서로 다른 계열의 합집합이 된다. 달력일이 다 들어
 * 있는 소스가 하나라도 끼면(전기차 기준가 CSV 는 주말도 들고 있다) 그 날짜만큼 축이
 * 늘어나고, 거래일만 있는 나머지 선은 그 자리에서 값이 없어 끊겨 보인다. 그래서 한 번에
 * 한 쌍만 그린다. 펀드와 그 참조지수는 같은 소스라 날짜가 같아 축에 구멍이 안 생긴다.
 *
 * 예외는 COVIEW_GROUPS — 거기 적힌 근거대로 날짜축이 겹치는 그룹끼리는 같이 올린다.
 * 이때 참조지수가 같은 지수이므로 **맨 앞 그룹의 것 하나만** 남기고 나머지는 버린다
 * (같은 선을 두 번 겹쳐 그리면 색만 덮어쓰고 범례에 중복으로 뜬다).
 *
 * 축을 합집합으로 두는 것 자체는 그대로다(교집합으로 자르면 인셉션이 늦은 계열이 구간
 * 전체를 잘라 버린다). 값이 없는 구간은 null 로 비우고, buildPlot 이 각 선을 자기 첫
 * 데이터부터 그리면서 창 시작 기준으로 리베이스한다.
 */
function buildModel(
  data: FundSeriesResponse | undefined,
  groups: string[],
): Model | null {
  // 색은 **등록된 전체** 기준으로 배정한다. 보이는 것만으로 배정하면 그룹을 바꿀 때마다
  // 남은 선들의 색이 바뀌어 버린다.
  const colors = assignColors((data?.funds ?? []).map((f) => f.id));
  let seenBm = false;
  const funds = (data?.funds ?? []).filter((f) => {
    if (!groups.includes(groupOf(f.id))) return false;
    if (!f.id.endsWith(BM_SUFFIX)) return true;
    if (seenBm) return false; // 공통 참조지수 — 첫 번째 것만 그린다
    seenBm = true;
    return true;
  });
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

  // 범례에서 고른 펀드 그룹. 기본은 하나만 그리고(그 펀드 + 그 참조지수),
  // COVIEW_GROUPS 끼리는 여러 개를 같이 그린다.
  const [picked, setPicked] = useState<string[] | null>(null);
  const groups = useMemo(() => groupsOf(data?.funds ?? []), [data]);
  // 고른 적이 없거나 고른 것이 목록에서 사라졌으면 자사 펀드로, 그것도 없으면 첫 그룹으로
  // 떨어진다. 상태를 effect 로 맞추지 않고 여기서 되짚어야 펀드 목록이 바뀌는 순간에도
  // 빈 화면이 생기지 않는다.
  const shown = useMemo(() => {
    const alive = (picked ?? []).filter((g) => groups.includes(g));
    if (alive.length) {
      // 범례·차트 순서는 언제나 등록 순서를 따른다(고른 순서가 아니다).
      return groups.filter((g) => alive.includes(g));
    }
    return groups.includes(SELF_ID) ? [SELF_ID] : groups.slice(0, 1);
  }, [picked, groups]);

  /* 범례 클릭 — 기본은 '갈아 끼우기', 동시 표시가 허용된 조합일 때만 '더하기/빼기'.
   * 마지막 하나는 빼지 않는다(빈 차트가 되어 버린다). */
  const onPick = (g: string) => {
    setPicked(
      shown.includes(g)
        ? shown.length > 1
          ? shown.filter((x) => x !== g)
          : shown
        : canCoview([...shown, g])
          ? [...shown, g]
          : [g],
    );
  };

  const model = useMemo(() => buildModel(data, shown), [data, shown]);
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

  // 리밸 상세는 차트의 ▲ 마커로만 연다. 페이지에 상설 패널을 두지 않는다.
  const [selEvent, setSelEvent] = useState<{ key: string; date: string } | null>(null);

  // 마커는 차트에 그려진 펀드에서 나온다(다른 펀드를 고르면 마커도 바뀐다). 편입 구성까지
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
                {groups.length > 0 && (
                  <span
                    className="text-[11.5px] text-ink-faint"
                    title="범례에서 펀드를 고릅니다. 날짜축이 달라 기본은 한 번에 하나만 그리고, 참조지수가 같고 거래일이 겹치는 펀드끼리만 함께 그립니다."
                  >
                    펀드 {groups.length}개 · 보는 중 {shown.length}개
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
                  <span>그릴 수 있는 계열이 없습니다. 점이 2개 이상이어야 합니다.</span>
                )}
              </div>
            ) : (
              <ReadyChart
                plot={plot}
                funds={data?.funds ?? []}
                shown={shown}
                onPick={onPick}
                markers={markers}
                selEvent={selEvent}
                onSelectMarker={onSelectMarker}
              />
            )}
          </div>
        </section>

        {/* 성과보고 (월=위클리 / 화~금=데일리) — S: bat 이 만든 HTML 을 iframe 렌더 */}
        <PerfReportCard />
      </PageContainer>

      {/* 리밸런싱 성과분석 — 차트의 ▲ 를 누르면 겹쳐 뜬다. 페이지에 상설 자리를 두지
          않는 이유는 볼 일이 있을 때만 보는 화면이기 때문이다. PageContainer 바깥에
          두어야 카드의 overflow-hidden 이나 스크롤에 걸리지 않는다. */}
      {selEvent && (
        <RebalModal
          detail={detail}
          isLoading={rebalQuery.isLoading}
          isError={rebalQuery.isError}
          onClose={() => setSelEvent(null)}
        />
      )}
    </>
  );
}

/* ── 준비 완료 상태: 헤더 스트립 + 컨트롤 + 차트 + 범례 ───────────────── */

function ReadyChart({
  plot,
  funds,
  shown,
  onPick,
  markers,
  selEvent,
  onSelectMarker,
}: {
  plot: Plot;
  funds: { id: string; label: string; inception: string; lastDate: string }[];
  shown: string[];
  onPick: (g: string) => void;
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

      {/* 범례 = **펀드** 선택기. 고르는 단위는 펀드 하나뿐이고, 참조지수는 그 펀드를
          고르면 따라 붙는다(선택지가 아니라 딸림 정보라서 버튼이 아닌 글자로 둔다).
          클릭은 껐다 켜기가 아니라 갈아 끼우기다. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline pt-3">
        {groupsOf(funds).map((g) => {
          // 그룹의 본체(펀드)와 딸린 참조지수. 참조지수만 등록된 그룹이면 본체가 없으니
          // 그때는 그 계열을 본체로 세운다.
          const main = funds.find((f) => f.id === g) ?? funds.find((f) => groupOf(f.id) === g);
          if (!main) return null;
          const off = !shown.includes(g);
          // 참조지수 칩은 **차트에 실제로 그려진** 것만 단다. 공통 참조지수는 buildModel 이
          // 하나로 합쳐 버리므로, 합쳐지면서 빠진 쪽에는 칩이 붙지 않는다(값 없는 "—" 방지).
          const bmId = g + BM_SUFFIX;
          const bm = funds.find((f) => f.id === bmId);
          const bmDrawn = plot.lines.some((l) => l.id === bmId);
          // 여러 펀드를 같이 보고 있으면 그 참조지수는 공통이다 — 라벨로 그렇게 알린다.
          const bmShared = shown.length > 1;
          const retOf = (id: string) => {
            const finite = (plot.lines.find((l) => l.id === id)?.vals ?? []).filter(
              (v): v is number => v != null && Number.isFinite(v),
            );
            return finite.length ? finite[finite.length - 1] : null;
          };
          const colorOf = (id: string) =>
            plot.lines.find((l) => l.id === id)?.color ?? "#c9d1dd";
          return (
            <span key={g} className="flex items-center gap-2">
              <button
                type="button"
                aria-pressed={!off}
                onClick={() => onPick(g)}
                title={
                  off
                    ? canCoview([...shown, g])
                      ? "클릭하면 지금 보는 펀드와 함께 그립니다 (참조지수가 같아 하나로 그림)"
                      : "클릭하면 이 펀드로 갈아 끼웁니다 (날짜축이 달라 같이 못 올립니다)"
                    : shown.length > 1
                      ? `클릭하면 이 펀드를 뺍니다 · ${dotDate(main.inception)} ~ ${dotDate(main.lastDate)}`
                      : `${dotDate(main.inception)} ~ ${dotDate(main.lastDate)}`
                }
                className={cn(
                  "flex items-center gap-2 rounded-md px-1.5 py-0.5 transition hover:bg-canvas-soft",
                  off && "opacity-40",
                )}
              >
                <span
                  className="inline-block h-2.5 w-4 rounded-full"
                  style={{ background: off ? "#c9d1dd" : colorOf(main.id) }}
                />
                <span className="text-[12.5px] font-bold text-ge-navy">{main.label}</span>
                {off ? (
                  <span className="text-[11px] text-ink-faint">보기</span>
                ) : (
                  <span
                    className="text-[13px] font-extrabold tabular-nums"
                    style={{ color: signColor(retOf(main.id)) }}
                  >
                    {signedPct(retOf(main.id))}
                  </span>
                )}
              </button>
              {/* 참조지수는 고른 펀드에만 딸려 나온다. 누를 수 없다. */}
              {!off && bm && bmDrawn && (
                <span className="flex items-center gap-1.5 border-l border-hairline pl-3">
                  <span
                    className="inline-block h-2.5 w-4 rounded-full"
                    style={{ background: colorOf(bm.id) }}
                  />
                  <span
                    className="text-[12px] font-semibold text-ink-secondary"
                    title={
                      bmShared
                        ? "지금 보고 있는 펀드들의 공통 참조지수 (같은 지수라 하나만 그립니다)"
                        : bm.label
                    }
                  >
                    참조지수{bmShared && " (공통)"}
                  </span>
                  <span
                    className="text-[12.5px] font-bold tabular-nums"
                    style={{ color: signColor(retOf(bm.id)) }}
                  >
                    {signedPct(retOf(bm.id))}
                  </span>
                </span>
              )}
            </span>
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

/* ── 리밸런싱 성과분석 모달 ───────────────────────────────────────────────
   차트의 ▲(리밸 시점)를 누르면 겹쳐 뜬다. 페이지에 상설 자리를 주지 않는 이유는 평소에는
   곡선만 보고, 특정 리밸을 따질 때만 여는 화면이기 때문이다. 배경 클릭·ESC·✕ 로 닫는다.
   구조는 이 대시보드의 다른 모달(LP평가 상세)과 같게 맞췄다. */

function RebalModal({
  detail,
  isLoading,
  isError,
  onClose,
}: {
  detail: RebalDetailData | null;
  isLoading: boolean;
  isError: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const who = detail ? (detail.key === SELF_ID ? "자사(AI코어테크랩)" : "TORUS(BM)") : "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-canvas shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-extrabold text-ge-navy">
              리밸런싱 성과분석
            </h2>
            <div className="mt-0.5 text-[12px] tabular-nums text-ink-muted">
              {detail ? `${dotDate(detail.date)} · ${who}` : "불러오는 중…"}
            </div>
          </div>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-muted transition hover:bg-canvas-soft hover:text-ink"
          >
            <X className="h-4 w-4" strokeWidth={2} />
          </button>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {isLoading ? (
            <Skeleton className="h-40 w-full rounded-xl" />
          ) : isError ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              리밸런싱 데이터를 불러올 수 없습니다.
            </p>
          ) : !detail ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              이 시점의 편입 구성 이력이 없습니다. 구성 이력은 리밸런싱_히스토리 시트가 있는
              AI코어테크랩·TORUS 만 있습니다.
            </p>
          ) : (
            <RebalDetail detail={detail} />
          )}
        </div>
      </div>
    </div>
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
