"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getMacroPanels,
  type MacroCollection,
  type MacroCrosscheck,
  type MacroFomc,
  type MacroSeries,
  type MacroSeriesPoint,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

const REFETCH = 600000; // 10분 — 상류가 하루 몇 번 굽는 데이터라 자주 볼 이유가 없다

/* ── 화면 규약 ────────────────────────────────────────────────────────────
   1페이지 4분할, 스크롤 없음(2026-08-13 사용자 지정).
     2사분면(좌상) FOMC 금리확률 표   1사분면(우상) 물가 추이
     3사분면(좌하) 고용·유동성 추이   4사분면(우하) 비움
   높이는 뷰포트에서 Topbar(h-16)를 뺀 나머지를 grid-rows-2 로 반씩 나눈다.
   각 셀은 min-h-0 + overflow-hidden 이라야 내용이 넘쳐도 페이지가 안 늘어난다. */

/* ── 선그래프 ─────────────────────────────────────────────────────────────
   외부 차트 라이브러리를 쓰지 않는다 — 이 앱은 스파크라인도 손으로 그린다.
   컨테이너 크기에 맞추기 위해 viewBox + preserveAspectRatio="none" 대신
   고정 좌표계(1000×h)에 그리고 CSS 로 늘린다. 축 라벨은 늘어나면 찌그러지므로
   vector-effect 대신 폰트 크기를 좌표계 기준으로 잡는다. */

const VB_W = 1000;
const VB_H = 380;
// 오른쪽 여백은 우축 라벨 자리 — 우축을 안 쓰는 그래프에서도 같은 값이라 폭이 흔들리지 않는다
const PAD = { t: 14, r: 52, b: 34, l: 52 };

function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return [lo];
  const raw = (hi - lo) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw))));
  // '이상' 중 최솟값을 고르면 눈금이 성겨진다(범위 42 에 step 20 → 눈금 2개).
  // raw 에 가장 가까운 값을 고르면 의도한 개수에 근접한다.
  const step = [1, 2, 2.5, 5, 10]
    .map((m) => m * mag)
    .reduce((a, b) => (Math.abs(b - raw) < Math.abs(a - raw) ? b : a));
  const start = Math.ceil(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

// 커서 시점에 함께 보여줄 부가 항목(선으로는 안 그린다) — 물가의 세부내역이 이 자리다
type DetailSeries = { label: string; unit: string; points: MacroSeriesPoint[] };

function fmtMonth(d: string) {
  return `${d.slice(0, 4)}년 ${Number(d.slice(5, 7))}월`;
}

function LineChart({
  series,
  details,
  detailTitle,
}: {
  series: MacroSeries[];
  details?: DetailSeries[];
  detailTitle?: string;
}) {
  const [hover, setHover] = useState<{ t: number; xPct: number } | null>(null);

  const all = series.flatMap((s) => s.points);
  if (all.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-[12px] text-ink-faint">
        표시할 시계열이 없습니다
      </div>
    );
  }

  // x축은 실제 날짜 간격으로 — 주간/월간 시리즈가 섞여도 시간축이 어긋나지 않는다
  const ts = all.map((p) => new Date(p.d).getTime());
  const tMin = Math.min(...ts);
  const tMax = Math.max(...ts);

  // 좌/우 축을 따로 잡는다. 축을 안 쓰는 쪽은 null.
  const range = (side: "left" | "right") => {
    const vs = series
      .filter((s) => (s.axis ?? "left") === side)
      .flatMap((s) => s.points.map((p) => p.v));
    if (!vs.length) return null;
    let lo = Math.min(...vs);
    let hi = Math.max(...vs);
    const pad = (hi - lo || 1) * 0.12;
    lo -= pad;
    hi += pad;
    return { lo, hi };
  };
  const L = range("left");
  const R = range("right");
  const hasRight = R != null;

  const X = (t: number) =>
    PAD.l + ((VB_W - PAD.l - PAD.r) * (t - tMin)) / (tMax - tMin || 1);
  const mkY = (r: { lo: number; hi: number } | null) => (v: number) =>
    r == null
      ? VB_H / 2
      : VB_H - PAD.b - ((VB_H - PAD.t - PAD.b) * (v - r.lo)) / (r.hi - r.lo || 1);
  const YL = mkY(L);
  const YR = mkY(R);
  const yOf = (s: MacroSeries) => ((s.axis ?? "left") === "right" ? YR : YL);

  // 격자는 좌축 기준 하나만 — 두 축의 눈금을 다 그리면 선보다 격자가 많아진다.
  // 0 이 범위 안에 있으면 반드시 눈금에 넣는다(금리 커브에선 0 이 역전 경계라 의미가 있다).
  const baseTicks = L ? niceTicks(L.lo, L.hi, 4) : R ? niceTicks(R.lo, R.hi, 4) : [];
  const zeroRange = L ?? R;
  const gridTicks =
    zeroRange && zeroRange.lo < 0 && zeroRange.hi > 0 && !baseTicks.some((v) => Math.abs(v) < 1e-9)
      ? [...baseTicks, 0].sort((a, b) => a - b)
      : baseTicks;
  const rightTicks = hasRight ? niceTicks(R.lo, R.hi, 4) : [];
  const years = Array.from(new Set(all.map((p) => p.d.slice(0, 4)))).sort();
  const xTicks = years.map((y) => {
    const t = new Date(`${y}-01-01`).getTime();
    return { t: Math.max(t, tMin), label: `${y.slice(2)}년` };
  });

  // 커서에 가장 가까운 시점 — 계열마다 관측 주기가 달라 계열별로 따로 찾는다
  const nearest = (pts: MacroSeriesPoint[], t: number) => {
    let best = pts[0];
    let bestD = Infinity;
    for (const p of pts) {
      const d = Math.abs(new Date(p.d).getTime() - t);
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  };

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width; // 0~1
    const plotFrom = PAD.l / VB_W;
    const plotTo = (VB_W - PAD.r) / VB_W;
    if (px < plotFrom || px > plotTo) {
      setHover(null);
      return;
    }
    const frac = (px - plotFrom) / (plotTo - plotFrom);
    setHover({ t: tMin + (tMax - tMin) * frac, xPct: px * 100 });
  };

  const hoverRows = hover
    ? series.map((s) => ({ s, p: nearest(s.points, hover.t) }))
    : [];
  const hoverDetail =
    hover && details
      ? details.map((d) => ({ d, p: nearest(d.points, hover.t) }))
      : [];
  // 툴팁이 오른쪽 끝에서 잘리지 않게 방향을 뒤집는다
  const flip = (hover?.xPct ?? 0) > 58;

  return (
    <div
      className="relative h-full w-full"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="h-full w-full"
        preserveAspectRatio="none"
      >
        {/* y 격자 + 좌축 라벨 */}
        {gridTicks.map((v) => (
          <g key={`g${v}`}>
            <line
              x1={PAD.l}
              y1={YL(v)}
              x2={VB_W - PAD.r}
              y2={YL(v)}
              stroke={Math.abs(v) < 1e-9 ? "#B9C2CE" : "#E8ECF1"}
              strokeWidth={Math.abs(v) < 1e-9 ? 2 : 1.5}
            />
            <text x={PAD.l - 8} y={YL(v) + 5} textAnchor="end" fontSize={15} fill="#8A94A6">
              {v.toFixed(v % 1 === 0 ? 0 : 1)}
            </text>
          </g>
        ))}
        {/* 우축 라벨 — 색으로 어느 축인지 구분한다 */}
        {rightTicks.map((v) => (
          <text
            key={`r${v}`}
            x={VB_W - PAD.r + 8}
            y={YR(v) + 5}
            textAnchor="start"
            fontSize={15}
            fill="#3A6EA5"
          >
            {v.toFixed(v % 1 === 0 ? 0 : 1)}
          </text>
        ))}
        {/* x 라벨 */}
        {xTicks.map((t) => (
          <text
            key={t.label}
            x={X(t.t)}
            y={VB_H - 10}
            textAnchor="middle"
            fontSize={15}
            fill="#8A94A6"
          >
            {t.label}
          </text>
        ))}
        {/* 커서 세로선 */}
        {hover && (
          <line
            x1={X(hover.t)}
            y1={PAD.t}
            x2={X(hover.t)}
            y2={VB_H - PAD.b}
            stroke="#8A94A6"
            strokeWidth={1.5}
            strokeDasharray="4,3"
          />
        )}
        {/* 선 + 최신점 + 커서점 */}
        {series.map((s) => {
          const Y = yOf(s);
          const pts = s.points
            .map((p) => `${X(new Date(p.d).getTime()).toFixed(1)},${Y(p.v).toFixed(1)}`)
            .join(" ");
          const last = s.points[s.points.length - 1];
          const hp = hover ? nearest(s.points, hover.t) : null;
          return (
            <g key={s.series_id}>
              <polyline
                fill="none"
                stroke={s.color}
                strokeWidth={2.6}
                strokeLinejoin="round"
                strokeLinecap="round"
                points={pts}
              />
              <circle cx={X(new Date(last.d).getTime())} cy={Y(last.v)} r={4} fill={s.color} />
              {hp && (
                <circle
                  cx={X(new Date(hp.d).getTime())}
                  cy={Y(hp.v)}
                  r={5.5}
                  fill="#fff"
                  stroke={s.color}
                  strokeWidth={3}
                />
              )}
            </g>
          );
        })}
      </svg>

      {/* 툴팁 — SVG 밖 HTML 이라 글자가 늘어나지 않는다 */}
      {hover && hoverRows.length > 0 && (
        <div
          data-testid="chart-tooltip"
          className="pointer-events-none absolute top-1 z-10 min-w-[168px] rounded-lg border border-hairline bg-canvas/97 px-2.5 py-1.5 shadow-card"
          style={flip ? { right: `${100 - hover.xPct + 1.5}%` } : { left: `${hover.xPct + 1.5}%` }}
        >
          <div className="mb-1 text-[10.5px] font-extrabold text-ink-muted">
            {fmtMonth(hoverRows[0].p.d)}
          </div>
          {hoverRows.map(({ s, p }) => (
            <div key={s.series_id} className="flex items-baseline gap-2 text-[11px] leading-[1.5]">
              <span
                className="inline-block h-[3px] w-3 shrink-0 rounded-full"
                style={{ background: s.color }}
              />
              <span className="flex-1 whitespace-nowrap font-bold text-ge-navy">{s.label}</span>
              <span className="font-extrabold tabular-nums" style={{ color: s.color }}>
                {p.v > 0 ? "+" : ""}
                {p.v.toFixed(2)}
                {s.unit}
              </span>
            </div>
          ))}
          {hoverDetail.length > 0 && (
            <>
              <div className="mt-1 border-t border-hairline pt-1 text-[10px] font-extrabold text-ink-muted">
                {detailTitle ?? "세부내역"}
              </div>
              {hoverDetail.map(({ d, p }) => (
                <div key={d.label} className="flex items-baseline gap-2 text-[10.5px] leading-[1.45]">
                  <span className="flex-1 whitespace-nowrap text-ink-muted">{d.label}</span>
                  <span
                    className="font-bold tabular-nums"
                    style={{ color: p.v > 0 ? "#B23A1E" : p.v < 0 ? "#3A6EA5" : "#8A94A6" }}
                  >
                    {p.v > 0 ? "+" : ""}
                    {p.v.toFixed(2)}
                    {d.unit}
                  </span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Legend({ series }: { series: MacroSeries[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
      {series.map((s) => (
        <span key={s.series_id} className="inline-flex items-baseline gap-1.5 text-[11px]">
          <span
            className="inline-block h-[3px] w-3.5 shrink-0 rounded-full"
            style={{ background: s.color }}
          />
          <span className="font-bold text-ge-navy">{s.label}</span>
          <span className="font-extrabold tabular-nums" style={{ color: s.color }}>
            {s.latest > 0 ? "+" : ""}
            {s.latest.toFixed(2)}
            {s.unit}
          </span>
        </span>
      ))}
    </div>
  );
}

/* ── 사분면 셸 ────────────────────────────────────────────────────────── */

function Quad({
  title,
  sub,
  children,
  className,
}: {
  title: string;
  sub?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card",
        className,
      )}
    >
      <div className="h-1.5 shrink-0 rounded-t-2xl bg-ge-point" />
      <div className="flex min-h-0 flex-1 flex-col px-3.5 pb-2.5 pt-2">
        <div className="mb-1.5 flex shrink-0 flex-wrap items-baseline gap-x-2">
          <span className="text-[13.5px] font-extrabold text-ge-navy">{title}</span>
          {sub && <span className="text-[10.5px] font-semibold text-ink-muted">{sub}</span>}
        </div>
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </section>
  );
}

function ChartQuad({
  title,
  sub,
  series,
  details,
  detailTitle,
  loading,
}: {
  title: string;
  sub: string;
  series?: MacroSeries[];
  details?: DetailSeries[];
  detailTitle?: string;
  loading: boolean;
}) {
  return (
    <Quad title={title} sub={sub}>
      {loading ? (
        <Skeleton className="h-full w-full rounded-xl" />
      ) : !series?.length ? (
        <NotReady />
      ) : (
        <div className="flex h-full min-h-0 flex-col">
          <div className="min-h-0 flex-1">
            <LineChart series={series} details={details} detailTitle={detailTitle} />
          </div>
          <div className="shrink-0 pt-1">
            <Legend series={series} />
          </div>
        </div>
      )}
    </Quad>
  );
}

/* ── 2사분면 · FOMC 금리확률 표 ─────────────────────────────────────────── */

// 형광 하이라이트 — 1위/2위를 색으로 구분한다(회의별로 어디에 몰렸는지 한눈에).
const RANK_BG: Record<number, string> = { 1: "#FFF176", 2: "#B9F6CA" };

function FomcTable({ fomc }: { fomc: MacroFomc }) {
  const bands = fomc.bands ?? [];
  const meetings = fomc.meetings ?? [];
  if (!bands.length || !meetings.length) return <NotReady />;
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-[11.5px]">
        <thead className="sticky top-0 bg-canvas-soft">
          <tr className="text-[10.5px] text-ink-muted">
            <th className="px-2 py-1 text-left font-semibold">회의일</th>
            {bands.map((b) => (
              <th key={b.label} className="px-2 py-1 text-right font-semibold">
                {b.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {meetings.map((m) => (
            <tr key={m.date} className="border-t border-hairline">
              <td className="whitespace-nowrap px-2 py-[3px] font-bold text-ge-navy">
                {m.date}
              </td>
              {m.cells.map((c, i) => (
                <td
                  key={bands[i]?.label ?? i}
                  className={cn(
                    "px-2 py-[3px] text-right tabular-nums",
                    c.rank ? "font-extrabold text-ge-navy" : "text-ink-muted",
                  )}
                  style={c.rank ? { background: RANK_BG[c.rank] } : undefined}
                >
                  {c.prob == null ? "—" : `${(c.prob * 100).toFixed(2)}%`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── 페이지 ───────────────────────────────────────────────────────────── */

export default function MacroPage() {
  // 계산은 S: 매크로모니터가 끝낸 상태로 온다(macro_panels.json). 여기서 다시 구하지 않는다.
  const q = useQuery({
    queryKey: ["macroPanels"],
    queryFn: getMacroPanels,
    refetchInterval: REFETCH,
    retry: false,
  });
  const p = q.data;
  const warn =
    p && (p.collection?.stale || p.collection?.failed?.length || p.crosscheck?.some((c) => !c.match));

  return (
    <>
      <Topbar
        title="매크로"
        subtitle="Quant · 물가 · 고용 · 유동성 · FOMC"
        status={
          p ? (
            <span className="truncate text-[11px] text-slate-400">
              기준 {p.asof} · 갱신 {p.generatedAt?.slice(0, 16).replace("T", " ")}
            </span>
          ) : undefined
        }
      />
      {/* 스크롤 없는 한 화면 — Topbar(h-16)를 뺀 높이를 2×2 로 나눈다 */}
      <div className="flex h-[calc(100vh-4rem)] min-h-0 flex-col gap-2.5 px-4 py-3">
        {q.isError && <ApiErrorBanner error={q.error} />}
        {warn && p && <StaleBanner col={p.collection} crosscheck={p.crosscheck} />}

        <div className="grid min-h-0 flex-1 grid-cols-2 grid-rows-2 gap-2.5">
          {/* 2사분면 — FOMC 금리확률 */}
          <Quad
            title="FOMC 금리확률"
            sub={
              p?.fomc?.snapshot_date
                ? `CME FedWatch · 스냅샷 ${p.fomc.snapshot_date} · 회의 ${p.fomc.meetings?.length ?? 0}개`
                : "CME FedWatch"
            }
          >
            {q.isPending ? (
              <Skeleton className="h-full w-full rounded-xl" />
            ) : !p?.fomc?.meetings?.length ? (
              <NotReady />
            ) : (
              <FomcTable fomc={p.fomc} />
            )}
          </Quad>

          {/* 1사분면 — 물가. 커서 시점의 CPI 세부내역을 툴팁에 함께 띄운다 */}
          <ChartQuad
            title="물가"
            sub="근원 CPI · PPI · PCE · YoY % · 선 위에 커서를 올리면 세부내역"
            series={p?.price_series}
            details={p?.price_detail_series}
            detailTitle="CPI 세부내역"
            loading={q.isPending}
          />

          {/* 3사분면 — 고용·유동성. 한 그래프에 두되 좌축(실업률 수준)/우축(YoY)으로
              스케일을 갈랐다. 한 축이면 실업률이 직선이 된다. */}
          <ChartQuad
            title="고용 · 유동성"
            sub="좌축 실업률(수준) · 우축 M2/지급준비금(YoY) · %"
            series={p?.labor_liq_series}
            loading={q.isPending}
          />

          {/* 4사분면 — 금리 커브. 스프레드만으로는 스티프닝의 원인(장기물↑ vs 단기물↓)을
              알 수 없어 금리 수준을 우축에 함께 얹는다. */}
          <ChartQuad
            title="금리 커브"
            sub="좌축 10Y-2Y 스프레드(%p) · 우축 국채 10년/2년(%) · 0선 아래는 역전"
            series={p?.rate_series}
            loading={q.isPending}
          />
        </div>
      </div>
    </>
  );
}

function NotReady() {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center text-[12px] leading-relaxed text-ink-muted">
      데이터 준비 중 — S: 매크로모니터에서 매크로수집.bat 실행 후 표시됩니다.
    </div>
  );
}

// 경고는 한 밴드에 모은다 — 여럿으로 쌓이면 사람이 하나만 보고 넘긴다.
function StaleBanner({
  col,
  crosscheck,
}: {
  col?: MacroCollection;
  crosscheck?: MacroCrosscheck[];
}) {
  const lines: string[] = [];
  if (col?.stale) lines.push(`${col.reason || "수집 지연"} — 매크로수집.bat 실행 필요`);
  if (col?.failed?.length) lines.push(`수집 실패: ${col.failed.join(", ")}`);
  for (const c of (crosscheck ?? []).filter((x) => !x.match)) {
    lines.push(
      `${c.label} 발표값 불일치 — investing ${c.theirs}${c.unit} vs 원천 ${c.ours_rounded}${c.unit} [${c.series_id}]`,
    );
  }
  return (
    <div className="shrink-0 rounded-xl border-l-[6px] border-[#E0A800] bg-[#FFF3CD] px-3 py-2 text-[12px] font-semibold text-[#6B5310]">
      <span className="mr-2 text-[10.5px] font-extrabold tracking-wide text-[#A07800]">
        점검
      </span>
      {lines.join(" · ")}
    </div>
  );
}
