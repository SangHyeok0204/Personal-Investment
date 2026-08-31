"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getPriceGroupSeries,
  getPriceMetricSeries,
  type PriceCatKey,
  type PriceChartMode,
  type PriceChartSeries,
  type PriceGroupPayload,
  type PriceMetricPayload,
} from "@/lib/api";
import type { PriceSel } from "@/components/stock-monitor/price-tree-card";
import { cn } from "@/lib/utils";

// [지표 추이 차트] — 종목 모니터 2~5칸 × 2행. 왼쪽 목록에서 고른 것을 시계열로 그린다.
//
// ★★2026-08-31 전면 개편(사용자 지시). DtD·WtD·MtD·YtD **시계열을 전부 뺐다** —
//   달력 앵커라 월초·연초마다 0 으로 리셋되는 톱니여서 추세가 안 읽히고, 그 숫자는
//   우하단 요약 표(price-summary-card)가 이미 보여준다. 대신 2모드:
//     · 누적수익률 — 보는 구간 시작 = **100** 으로 리베이스(사용자 지시 8/31).
//                    레벨이 다른 지수를 한 축에 얹는 유일한 방법이다
//                    (SPX 7,700 vs KOSPI200 400). 채권만 0 기준 누적 bp.
//     · 롤링 3M    — 0선 교차 = 추세 전환. 서버가 계산해 준 그대로 그린다.
//   ★이평선은 넣지 않는다(사용자 확정): **가격 축**을 요구해서 레벨이 다른 지수를
//     겹칠 수 없다 — 이 화면의 주력인 묶음 비교와 원리적으로 안 맞는다.
//   ★'벤치마크 대비'(상대곡선) 모드도 같은 날 만들었다가 **제거**했다(사용자 지시).
//     되살릴 거면 서버 payload 에 벤치마크 계열부터 다시 실어야 한다.
//
// ★★누적수익률은 **여기서** 계산한다. 리베이스 기준점이 사용자가 헤더 날짜 칸으로
//   좁힌 구간의 첫 점이라 서버는 그걸 모른다. 서버는 가격 원본(price)만 실어 준다.
//   그래서 모드를 바꿔도 재요청이 없다 — 칩이 즉각 반응한다.
//
// ★두 선택이 **같은 차트**를 쓴다: 지수 하나(leaf) = 계열 1개, 묶음(group) = 계열 N개.
//   payload 모양이 같아서 차트는 계열 배열 하나만 받는다.
// ★묶음 모드의 범례는 계열 켜기/끄기다 — 유럽 11개처럼 많을 때 솎아 보라고 둔다.

const POLL_MS = 600_000;

// 지수 하나(leaf)일 때 선 색 — 모드마다 다르게 줘서 칩 색과 선 색이 맞물리게 한다.
// 묶음 모드는 계열마다 PALETTE 를 쓰므로 이 값을 안 본다.
const MODE_COLOR: Record<PriceChartMode, string> = {
  cum: "#4a7ab5",
  r3m: "#2aa876",
};

// 묶음 모드 계열색 — 흰 캔버스 기준 검증 통과(validate_palette.js: 명도대·채도·CVD
// 인접쌍 ΔE 8.7·정상시야 18.8 전부 PASS). 주황 #e8871e 만 대비 2.65:1 이라
// "라벨을 보이게 두라"는 조건이 붙는데, 아래 범례가 계열명을 항상 띄우므로 충족한다.
// ★9개를 넘는 묶음(유럽 11)은 색을 새로 만들지 않고 **점선으로 갈라 준다** —
//   hue 를 돌려 쓰면 두 시장이 같은 색이 되어 범례가 거짓말을 한다.
const PALETTE = [
  "#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7", "#d1495b",
  "#0a9bc4", "#b58b00", "#c2417a", "#6b8f3a",
];
const DASH = "5 3";

const GRID = "#EDF0F5";
const ZERO = "#B9C2CE";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";

const PAD_L = 48;
const PAD_R = 12;
const PAD_T = 10;
const XAXIS_H = 18;

const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;

// 기본 창(최근 1년)의 시작일. 달력 기준으로 1년 뒤로 물린다.
function minusYear(d: string): string {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCFullYear(t.getUTCFullYear() - 1);
  return t.toISOString().slice(0, 10);
}

type Line = {
  key: string;
  label: string;
  color: string;
  dash?: string;
  points: [string, number][];
};

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  if (!Number.isFinite(raw) || raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(Math.abs(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

// 값 표기 — 지수(100 기준)는 부호도 단위도 붙이지 않고, 변화율·bp 는 둘 다 붙인다.
function fmtVal(v: number, suffix: string, signed: boolean): string {
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(1)}${suffix}`;
}

function Chart({
  lines,
  suffix,
  signed,
  baseline,
  title,
  w,
  h,
}: {
  lines: Line[];
  suffix: string;
  signed: boolean;
  baseline: number; // 기준선 — 지수 모드 100, 변화율·bp 모드 0
  title: string;
  w: number;
  h: number;
}) {
  const [hoverX, setHoverX] = useState<string | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const plotH = Math.max(12, h - PAD_T - XAXIS_H);
  const py1 = PAD_T + plotH;

  const { x0, x1, yLo, yHi, dates, lookup } = useMemo(() => {
    const ds = lines.flatMap((s) => s.points.map((p) => day(p[0])));
    const vs = lines.flatMap((s) => s.points.map((p) => p[1]));
    // ★기준선을 y 범위에 **항상 포함**시킨다. 안 그러면 전 계열이 100 위에만 있을 때
    //   기준선이 화면 밖으로 밀려 "무엇 대비인지"가 사라진다.
    const lo = Math.min(...vs, baseline);
    const hi = Math.max(...vs, baseline);
    const pad = (hi - lo) * 0.06 || 1;
    const uniq = [...new Set(lines.flatMap((s) => s.points.map((p) => p[0])))].sort();
    return {
      x0: Math.min(...ds),
      x1: Math.max(...ds),
      yLo: lo - pad,
      yHi: hi + pad,
      dates: uniq,
      lookup: lines.map((s) => new Map(s.points)),
    };
  }, [lines, baseline]);

  const X = (d: number) => PAD_L + ((d - x0) / (x1 - x0 || 1)) * plotW;
  const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo)) * plotH;

  // x 눈금은 보는 구간 길이를 따라간다 — 기본이 최근 1년이 되면서 연도 눈금만으로는
  // 라벨이 0~1개밖에 남지 않는다.
  const xTicks = useMemo(() => {
    const at = (t: number) => new Date((t + 0.5) * 86_400_000);
    const s = at(x0);
    const e = at(x1);
    const out: { d: string; label: string }[] = [];

    if (x1 - x0 > 1100) {
      for (let y = s.getUTCFullYear() + 1; y <= e.getUTCFullYear(); y++)
        out.push({ d: `${y}-01-01`, label: `${y}` });
      return out;
    }
    if (x1 - x0 >= 55) {
      // 월 시작. 7개를 넘으면 건너뛴다.
      const m0 = s.getUTCFullYear() * 12 + s.getUTCMonth();
      const m1 = e.getUTCFullYear() * 12 + e.getUTCMonth();
      const stride = Math.max(1, Math.ceil((m1 - m0) / 7));
      for (let m = m0 + 1; m <= m1; m += stride) {
        const mm = (m % 12) + 1;
        out.push({
          d: `${Math.floor(m / 12)}-${String(mm).padStart(2, "0")}-01`,
          label: mm === 1 ? `${Math.floor(m / 12)}` : `${mm}월`,
        });
      }
      return out;
    }
    // 두 달 미만이면 실제 데이터 날짜에서 고르게 뽑는다.
    const step = Math.max(1, Math.ceil(dates.length / 5));
    for (let i = 0; i < dates.length; i += step)
      out.push({ d: dates[i], label: `${+dates[i].slice(5, 7)}/${+dates[i].slice(8, 10)}` });
    return out;
  }, [x0, x1, dates]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0 || dates.length === 0) return;
    const t = x0 + (((e.clientX - r.left) / r.width) * w - PAD_L) / plotW * (x1 - x0);
    let best = dates[0];
    let bd = Infinity;
    for (const d of dates) {
      const g = Math.abs(day(d) - t);
      if (g < bd) {
        bd = g;
        best = d;
      }
    }
    setHoverX(best);
  };

  const hx = hoverX ? X(day(hoverX)) : 0;
  const fmt = (v: number) => fmtVal(v, suffix, signed);

  // 툴팁은 그 시점 값이 큰 순서로 — 계열이 11개면 순위 자체가 읽을 거리다.
  const hovered = hoverX
    ? lines
        .map((s, i) => ({ s, v: lookup[i].get(hoverX) }))
        .filter((x) => x.v != null)
        .sort((a, b) => (b.v as number) - (a.v as number))
    : [];

  return (
    <div className="relative h-full w-full">
      <svg
        width="100%"
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        style={{ display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverX(null)}
        role="img"
        aria-label={title}
      >
        {niceTicks(yLo, yHi, 4).map((v) => {
          const y = Y(v);
          if (y < PAD_T - 0.5 || y > py1 + 0.5) return null;
          const isZero = Math.abs(v - baseline) < 1e-9;
          return (
            <g key={v}>
              <line
                x1={PAD_L}
                y1={y}
                x2={PAD_L + plotW}
                y2={y}
                stroke={isZero ? ZERO : GRID}
                strokeWidth={isZero ? 1.4 : 1}
              />
              <text
                x={PAD_L - 5}
                y={y + 3}
                fontSize={9.5}
                fill={AXIS_TEXT}
                textAnchor="end"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {v.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* 기준선 — 눈금이 우연히 이 값을 비껴가도 항상 그린다. 지수 모드에서 100 은
            "구간 시작"이라 이 선이 없으면 위/아래를 판단할 기준 자체가 사라진다. */}
        <line
          x1={PAD_L}
          y1={Y(baseline)}
          x2={PAD_L + plotW}
          y2={Y(baseline)}
          stroke={ZERO}
          strokeWidth={1.4}
        />

        {lines.map((s) => (
          <path
            key={s.key}
            d={s.points
              .map((p, i) => `${i ? "L" : "M"}${X(day(p[0])).toFixed(1)},${Y(p[1]).toFixed(1)}`)
              .join(" ")}
            fill="none"
            stroke={s.color}
            strokeWidth={1.5}
            strokeDasharray={s.dash}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {xTicks.map((t) => (
          <text
            key={t.d}
            x={X(day(t.d))}
            y={h - 5}
            fontSize={9.5}
            fill={AXIS_TEXT}
            textAnchor="middle"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {t.label}
          </text>
        ))}

        {hoverX ? (
          <g style={{ pointerEvents: "none" }}>
            <line x1={hx} y1={PAD_T} x2={hx} y2={py1} stroke={CROSS} strokeWidth={1} />
            {hovered.map(({ s, v }) => (
              <circle
                key={s.key}
                cx={hx}
                cy={Y(v as number)}
                r={3.4}
                fill="#ffffff"
                stroke={s.color}
                strokeWidth={2}
              />
            ))}
          </g>
        ) : null}
      </svg>

      {hoverX ? (
        <div
          className="pointer-events-none absolute top-1 z-10 max-h-[85%] overflow-hidden rounded-lg border border-hairline bg-canvas/95 px-2.5 py-1.5 shadow-panel"
          style={{
            left: hx,
            transform: hx > w / 2 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          }}
        >
          <div className="mb-0.5 text-[10px] tabular-nums text-ink-muted">{hoverX}</div>
          {hovered.map(({ s, v }) => (
            <div key={s.key} className="flex items-center gap-1.5 text-[11px] leading-tight">
              <span
                className="inline-block h-2 w-2 shrink-0 rounded-sm"
                style={{ background: s.color }}
              />
              <span className="text-ink-muted">{s.label}</span>
              <b className="ml-auto pl-2 tabular-nums text-ink">{fmt(v as number)}</b>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const MODES: { key: PriceChartMode; label: string }[] = [
  { key: "cum", label: "누적수익률" },
  { key: "r3m", label: "롤링 3M" },
];

export function PriceMetricChartCard({
  sel,
  cat,
}: {
  sel: PriceSel | null;
  cat: PriceCatKey;
}) {
  // 고른 모드. 기본 누적수익률 — 구간 승자를 바로 보여주는 화면이다(사용자 지시).
  const [mode, setMode] = useState<PriceChartMode>("cum");
  // 묶음 모드에서 꺼 둔 계열. 묶음이 바뀌면 비운다.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // 보는 구간. null 이면 기본값(최근 1년) — 헤더의 날짜 칸을 건드리면 그 값이 이긴다.
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);

  // 선택을 두 갈래로 좁혀 둔다 — 아래 쿼리·렌더가 매번 kind 를 다시 묻지 않게.
  const group = sel && sel.kind === "group" ? sel : null;
  const leaf = sel && sel.kind === "leaf" ? sel : null;
  const isGroup = group !== null;

  const groupId = group ? `${cat}|${group.l1}|${group.l2}` : null;
  useEffect(() => {
    setHidden(new Set());
  }, [groupId]);

  const leafQ = useQuery<PriceMetricPayload>({
    queryKey: ["price-metric-series", leaf?.key ?? null],
    queryFn: () => getPriceMetricSeries(leaf!.key),
    enabled: leaf !== null,
    refetchInterval: POLL_MS,
  });

  const groupQ = useQuery<PriceGroupPayload>({
    queryKey: ["price-group-series", cat, group?.l1 ?? null, group?.l2 ?? null],
    queryFn: () => getPriceGroupSeries(cat, group!.l1, group!.l2),
    enabled: isGroup,
    refetchInterval: POLL_MS,
    // 묶음을 옮길 때 차트가 빈 화면으로 깜빡이지 않게 이전 값을 물고 있는다.
    placeholderData: (prev) => prev,
  });

  const q = isGroup ? groupQ : leafQ;
  const data = q.data;

  // ★★누적수익률은 **구간 시작 = 100 인 지수**로 그린다(사용자 지시 2026-08-31).
  //   0 기준 %가 아니라 100 기준이라 부호(+)도 단위(%)도 붙이지 않는다 — "134.2" 는
  //   구간 시작 대비 1.342배라는 뜻이다.
  // ★단, **금리는 지수화하지 않는다.** 금리를 금리로 나눈 비율은 의미가 없어(4%→5%
  //   를 125 라 부를 수 없다) 채권 탭의 누적수익률은 0 기준 **누적 bp 변화**로 남는다.
  //   롤링 3M 도 변화량이라 언제나 0 기준이다.
  const indexed = mode === "cum" && !data?.is_yield;
  const suffix = indexed ? "" : data?.is_yield ? "bp" : "%";
  const baseline = indexed ? 100 : 0;

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

  // 모드가 고른 **원본 배열**. cum·rs 는 가격에서 만들고, r3m 은 서버 계산 그대로다.
  // 색은 여기서 정한다 — 계열 순서(=PALETTE 자리)가 범례와 맞아야 하므로 hidden
  // 필터보다 **먼저** 배정한다. 껐다 켜도 색이 안 바뀌는 게 그 이유다.
  const raw: Line[] = useMemo(() => {
    if (!data) return [];
    const src: PriceChartSeries[] = data.series;
    return src
      .map((s, i) => ({
        key: s.key,
        label: s.label,
        color: isGroup ? PALETTE[i % PALETTE.length] : MODE_COLOR[mode],
        dash: isGroup && i >= PALETTE.length ? DASH : undefined,
        points: mode === "r3m" ? s.r3m : s.price,
      }))
      .filter((s) => !hidden.has(s.key) && s.points.length > 0);
  }, [data, isGroup, mode, hidden]);

  // 데이터가 가진 날짜 폭 — 기본 창의 기준점이자 날짜 칸의 min/max.
  const extent = useMemo(() => {
    let lo: string | null = null;
    let hi: string | null = null;
    for (const s of raw)
      for (const [d] of s.points) {
        if (lo === null || d < lo) lo = d;
        if (hi === null || d > hi) hi = d;
      }
    return lo && hi ? { lo, hi } : null;
  }, [raw]);

  // ★기본은 최근 1년(사용자 지시 2026-08-28). 전 구간을 그리면 최근 움직임이 납작해진다.
  const view = useMemo(() => {
    if (!extent) return null;
    if (range) return range;
    const back = minusYear(extent.hi);
    return { from: back < extent.lo ? extent.lo : back, to: extent.hi };
  }, [extent, range]);

  // ★★여기가 이 카드의 핵심이다 — **구간을 먼저 자르고 그 다음에 리베이스**한다.
  //   순서를 바꾸면(전 구간 리베이스 후 자르기) 화면 왼쪽 끝이 0% 에서 시작하지 않아
  //   "이 구간에서 누가 이겼나"를 못 읽는다. 날짜 칸을 좁힐 때마다 기준점이 따라오는
  //   것이 이 차트의 값어치 전부다.
  const lines: Line[] = useMemo(() => {
    if (!view) return raw;
    const isYield = !!data?.is_yield;

    const out: Line[] = [];
    for (const s of raw) {
      const win = s.points.filter(([d]) => d >= view.from && d <= view.to);
      if (win.length === 0) continue;

      // 롤링 3M 은 구간과 무관한 값이라 자르기만 하면 된다.
      if (mode === "r3m") {
        out.push({ ...s, points: win });
        continue;
      }

      const base = win[0][1];
      // 금리는 비율이 아니라 **누적 bp 변화**다 — 4%→5% 를 125 라 하면 안 된다.
      if (!isYield && base === 0) continue;
      out.push({
        ...s,
        points: win.map(([d, v]) => [
          d,
          isYield ? (v - base) * 100 : (v / base) * 100,
        ]) as [string, number][],
      });
    }
    return out;
  }, [raw, view, mode, data?.is_yield]);

  // 범례 숫자는 **그린 선의** 마지막 값이어야 한다 — 리베이스된 값과 다른 숫자를
  // 띄우면 범례가 차트를 배신한다. 그래서 원본이 아니라 lines 에서 찾는다.
  const lastOf = (key: string) => {
    const l = lines.find((s) => s.key === key);
    return l && l.points.length ? l.points[l.points.length - 1][1] : null;
  };

  // 범례용 전체 목록(꺼진 것도 보여야 다시 켤 수 있다)
  const groupAll = isGroup && data ? data.series : [];

  const toggle = (k: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      // 마지막 하나까지 끄면 빈 차트가 된다 — 최소 1개는 남긴다.
      if (next.has(k)) next.delete(k);
      else if (groupAll.length - next.size > 1) next.add(k);
      return next;
    });

  const modeLabel = MODES.find((m) => m.key === mode)?.label ?? "";
  const modeNote =
    mode === "cum"
      ? indexed
        ? " (구간 시작 = 100)"
        : ` (구간 시작 대비 누적, ${suffix})`
      : ` (${suffix})`;
  const subtitle = `${data?.sub ? `${data.sub} · ` : ""}${modeLabel}${modeNote} · 일간`;

  return (
    // col-span-4 (2~5번째 열) — ETF 카드가 1칸으로 줄면서 넘겨받은 폭이다.
    // 테두리는 오른쪽 한 줄만(카드끼리 맞붙는 배치 규칙, page.tsx 주석 참고).
    <section className="lg:col-span-4 lg:row-span-2 flex min-h-0 flex-col border-r border-hairline bg-canvas">
      {/* 제목 띠 — 강조색(ge-header). 배경이 어두우니 글자를 흰색 계열로 뒤집는다. */}
      <header className="flex items-center gap-2 bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[13px] font-extrabold text-white">
          {data?.label ?? "지표 추이"}
        </h2>
        <span className="min-w-0 truncate text-[11px] text-white/70">{subtitle}</span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {!isGroup && (data as PriceMetricPayload | undefined)?.price != null ? (
            <span className="text-[12px] font-extrabold tabular-nums text-white">
              {data!.is_yield
                ? `${(data as PriceMetricPayload).price!.toFixed(2)}%`
                : (data as PriceMetricPayload).price!.toLocaleString("en-US", {
                    maximumFractionDigits: 2,
                  })}
            </span>
          ) : data?.asof ? (
            <span className="text-[11px] tabular-nums text-white/60">{data.asof} 기준</span>
          ) : null}

          {/* 보는 구간 — 기본 최근 1년, 여기서 시작일·종료일을 직접 잡는다. */}
          {view && extent ? (
            <>
              <DateBox
                label="시작일"
                value={view.from}
                min={extent.lo}
                max={view.to}
                onChange={(v) => setRange({ from: v || extent.lo, to: view.to })}
              />
              <span className="text-[11px] text-white/40">~</span>
              <DateBox
                label="종료일"
                value={view.to}
                min={view.from}
                max={extent.hi}
                onChange={(v) => setRange({ from: view.from, to: v || extent.hi })}
              />
            </>
          ) : null}
        </div>
      </header>

      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pt-0.5">
        {!sel ? (
          <Center msg="왼쪽 목록에서 지수 또는 묶음(미국·유럽 등)을 고르면 추이가 표시됩니다." />
        ) : q.isLoading ? (
          <Center msg="불러오는 중…" />
        ) : q.isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : data?.note ? (
          <Center msg={data.note} tone="text-amber-600" />
        ) : lines.length === 0 ? (
          <Center
            msg={
              raw.length
                ? "선택한 기간에 데이터가 없습니다 — 날짜를 넓혀 주세요."
                : "표시할 계열이 없습니다 — 아래 범례에서 켜 주세요."
            }
          />
        ) : box.w > 0 && box.h > 0 ? (
          <Chart
            lines={lines}
            suffix={suffix}
            signed={!indexed}
            baseline={baseline}
            title={`${data?.label ?? ""} 지표 추이`}
            w={box.w}
            h={box.h}
          />
        ) : null}
      </div>

      {/* 아래 조작부 — 위: 모드 3개 중 1개 / 아래: 묶음 모드의 계열 켜기·끄기 */}
      <div className="shrink-0 border-t border-hairline">
        <div className="flex flex-wrap items-center justify-center gap-1.5 px-3 py-1">
          <span className="mr-0.5 text-[10px] font-bold text-ink-muted">보기</span>
          {MODES.map((m) => {
            const on = mode === m.key;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => setMode(m.key)}
                title={
                  m.key === "cum"
                    ? "보는 구간 시작을 0 으로 맞춘 누적 곡선"
                    : "그 시점의 3개월 전 대비 — 0 선을 넘으면 추세 전환"
                }
                className={cn(
                  "flex items-baseline gap-1.5 rounded px-2 py-0.5 text-[11px] transition-colors",
                  on
                    ? "bg-ge-blue-bg font-extrabold text-ge-point"
                    : "text-ink-muted hover:bg-canvas-soft",
                )}
              >
                <span
                  className="inline-block h-[3px] w-4 shrink-0 translate-y-[-2px] rounded-full"
                  style={{ background: on ? MODE_COLOR[m.key] : "#c7cdd6" }}
                />
                {m.label}
              </button>
            );
          })}
        </div>

        {isGroup && groupAll.length > 1 ? (
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-0.5 border-t border-hairline/60 px-3 py-1">
            {groupAll.map((s, i) => {
              const on = !hidden.has(s.key);
              const color = PALETTE[i % PALETTE.length];
              const last = lastOf(s.key);
              return (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => toggle(s.key)}
                  title={on ? `${s.label} 숨기기` : `${s.label} 표시`}
                  className={cn(
                    "flex items-baseline gap-1 rounded px-1 py-0.5 text-[10.5px] transition-opacity hover:bg-canvas-soft",
                    !on && "opacity-35",
                  )}
                >
                  <svg width="16" height="6" className="shrink-0 translate-y-[-2px]">
                    <line
                      x1="0"
                      y1="3"
                      x2="16"
                      y2="3"
                      stroke={color}
                      strokeWidth={3}
                      strokeDasharray={i >= PALETTE.length ? "4 2" : undefined}
                      strokeLinecap="round"
                    />
                  </svg>
                  <span className="font-bold text-ink">{s.label}</span>
                  {last != null ? (
                    <span className="tabular-nums text-ink-muted">
                      {fmtVal(last, suffix, !indexed)}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}

// 제목 띠(어두운 배경) 위에 얹는 날짜 칸. color-scheme:dark 를 줘야 크롬 기본
// 달력 아이콘·글자가 검정으로 깔려 안 보이는 일이 없다.
function DateBox({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: string;
  min: string;
  max: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="date"
      aria-label={label}
      title={label}
      value={value}
      min={min}
      max={max}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-white/25 bg-white/10 px-1 py-px text-[11px] tabular-nums text-white outline-none [color-scheme:dark] focus:border-white/60"
    />
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <span className={cn("text-[12px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
