"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getComputeIndex, type ComputeIndexSeries } from "@/lib/api";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [컴퓨팅 지수 모니터링] — [AI Key Data] 탭 좌상단 3칸.
// (2026-08-26 종목 모니터 상단에 신설 → 2026-08-27 이 탭으로 이사. 형식·크기 그대로.)
// Silicon Data GPU 렌탈 지수를 **세대별로 한 패널씩** 세로 분할로 그린다.
// 원천은 AI Key Data의 GPU임대지수_주가_통합.xlsx — collector compute_index.py
// 가 판독하고 지수 목록 정본도 그쪽 INDICES(현재 H100·B200·A100).
//
// ★★왜 나누는가: 단가를 한 차트에 여러 y축으로 겹치면 세대별 스케일이 2배씩 달라
//   없는 상관을 만든다(dual-axis 금지). 각자 자기 축을 갖는 패널로 나누고 x 도메인만
//   공유해 세로로 눈이 맞게 한다 — 크로스헤어가 모든 패널을 동시에 지난다.
// ★패널 수는 payload 가 정한다: 기초 파일에 없는 지수는 series 에서 빠지므로
//   화면도 그만큼만 그린다(A100 블록이 들어오면 세 번째 패널이 자동으로 생긴다).
//
// 렌더 관례는 이 레포의 다른 시계열(track-record PerfChart · lp-eval)과 같다:
// ResizeObserver 로 컨테이너를 재고 viewBox 를 px 와 1:1 로 맞춘다(글자 안 늘어남).
// SVG 속성은 raw hex, 바깥 HTML 은 tailwind 토큰.

// 원천 xlsx 가 일간이라 30초로 조를 이유가 없다. 다른 카드(30초)와 다른 주기다.
// 계열색 — 하우스 팔레트에서 고름(ge-point / lp-eval 팔레트의 주황·초록).
// 흰 캔버스(#ffffff) 기준 CVD·명도 검증 통과. 주황은 대비 2.65:1 이라 색만으로
// 두지 않고 패널마다 이름·현재값을 글자로 같이 띄운다(색맹·저대비 보완).
const COLOR: Record<string, string> = {
  h100: "#4a7ab5",
  b200: "#e8871e",
  a100: "#2aa876", // 2026-08-27 배수 패널이 있던 자리 — 같은 슬롯을 A100 이 물려받는다
};

const GRID = "#EDF0F5";
const AXIS_TEXT = "#8a94a6";
const CROSS = "#B7C0CE";
const INK = "#3a4150";
const UP = "#e11d48"; // 한국 관례 — 상승 빨강 / 하락 파랑 (format.moveColor 와 같은 짝)
const DOWN = "#2563eb";

// ★2026-08-31 글자 상향(9~9.5 -> 11~11.5px)에 맞춰 축 여백도 넓혔다 —
//   안 넓히면 y 라벨이 잘리고 x 날짜가 서로 겹친다.
const PAD_L = 52; // y 라벨
const PAD_R = 10;
const XAXIS_H = 20;
// ★2026-08-31 사용자 지시로 키움(17 -> 26). 4사분면으로 갈라져 패널 폭은 넓어졌는데
//   제목 줄 글자는 10~11px 그대로라 '지금 값·등락률'이 안 읽혔다.
const TITLE_H = 26; // 패널마다 이름·현재값 한 줄

const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  if (!Number.isFinite(raw) || raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function fmtVal(_kind: string, v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function Chart({ series, w, h }: { series: ComputeIndexSeries[]; w: number; h: number }) {
  const [hoverX, setHoverX] = useState<string | null>(null);

  const plotW = Math.max(1, w - PAD_L - PAD_R);
  const panelH = (h - XAXIS_H) / series.length;
  const plotH = Math.max(12, panelH - TITLE_H);

  // x 도메인은 전 계열 공유 — 산출 시작일이 달라도(B200 이 먼저) 세로로 눈이 맞는다.
  const { x0, x1, dates, lookup } = useMemo(() => {
    const all = series.flatMap((s) => s.points.map((p) => p[0]));
    const uniq = [...new Set(all)].sort();
    return {
      x0: day(uniq[0]),
      x1: day(uniq[uniq.length - 1]),
      dates: uniq,
      lookup: series.map((s) => new Map(s.points)),
    };
  }, [series]);

  const X = (d: string) => PAD_L + ((day(d) - x0) / (x1 - x0 || 1)) * plotW;

  const panels = series.map((s, i) => {
    const top = i * panelH;
    const py0 = top + TITLE_H;
    const py1 = py0 + plotH;
    const vals = s.points.map((p) => p[1]);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    // 2026-08-28 14%→5%("빈 공간 없이" 지시) — 패널 3장이라 여백이 세 번 쌓인다.
    const pad = (hi - lo) * 0.05 || Math.abs(hi) * 0.02 || 1;
    const yLo = lo - pad;
    const yHi = hi + pad;
    const Y = (v: number) => py1 - ((v - yLo) / (yHi - yLo)) * plotH;
    return { s, py0, py1, Y, yLo, yHi };
  });

  // x축 눈금 — 2개월 간격, 맨 아래 한 번만(소형 다중 관용구).
  const xTicks = useMemo(() => {
    const out: string[] = [];
    const end = new Date(`${dates[dates.length - 1]}T00:00:00Z`);
    let cur = new Date(`${dates[0]}T00:00:00Z`);
    cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + 1, 1));
    while (cur <= end) {
      out.push(cur.toISOString().slice(0, 10));
      cur = new Date(Date.UTC(cur.getUTCFullYear(), cur.getUTCMonth() + 2, 1));
    }
    return out;
  }, [dates]);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
    // viewBox 가 px 와 1:1 이라 비율만 되돌리면 그대로 도메인 좌표다.
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

  const hx = hoverX ? X(hoverX) : 0;
  const tipRight = hx > w / 2;

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
        aria-label="GPU 렌탈 지수 3분할 — SDH100RT, SDB200RT, 배수"
      >
        {panels.map(({ s, py0, py1, Y, yLo, yHi }) => {
          const color = COLOR[s.key] ?? INK;
          const t = s.stats;
          const d = s.points
            .map((p, j) => `${j ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`)
            .join(" ");
          return (
            <g key={s.key}>
              {/* 패널 제목 줄 — 계열이 1개라 범례 없이 이름이 곧 식별자다.
                  글자는 ink 색으로 두고 색 식별은 왼쪽 스와치가 진다. */}
              <rect x={PAD_L} y={py0 - 19} width={4} height={13} rx={2} fill={color} />
              <text x={PAD_L + 10} y={py0 - 8} fontSize={13} fontWeight={800} fill={INK}>
                {s.name}
              </text>
              <text
                x={PAD_L + 10 + s.name.length * 7.8 + 7}
                y={py0 - 8}
                fontSize={11}
                fill={AXIS_TEXT}
              >
                {s.label} · {s.unit}
              </text>
              {/* ★값은 오른쪽 끝, 등락률은 그 왼쪽. 등락률 x 를 **값 길이로 계산**한다 —
                  예전엔 `w - PAD_R - 52` 고정이었는데, 글자를 16px 로 키우면 값이 그 자리를
                  넘어와 둘이 겹친다(단위가 index 면 `1.0524` 처럼 자릿수도 늘어난다). */}
              <text
                x={w - PAD_R}
                y={py0 - 8}
                fontSize={16}
                fontWeight={800}
                fill={INK}
                textAnchor="end"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmtVal(s.kind, t.last)}
              </text>
              <text
                x={w - PAD_R - (fmtVal(s.kind, t.last).length * 8.8 + 10)}
                y={py0 - 8}
                fontSize={13}
                fontWeight={700}
                fill={t.chg_1d_pct == null ? AXIS_TEXT : t.chg_1d_pct > 0 ? UP : DOWN}
                textAnchor="end"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {fmtPct(t.chg_1d_pct)}
              </text>

              {/* 눈금 2개면 스케일을 읽을 수 있다 — count=2 로는 패널당 1개만
                  걸려(범위가 좁아 step 이 한 단계 위로 뛴다) 축이 안 읽힌다. */}
              {niceTicks(yLo, yHi, 3).map((v) => {
                const y = Y(v);
                if (y < py0 - 0.5 || y > py1 + 0.5) return null;
                return (
                  <g key={v}>
                    <line x1={PAD_L} y1={y} x2={PAD_L + plotW} y2={y} stroke={GRID} strokeWidth={1} />
                    <text
                      x={PAD_L - 5}
                      y={y + 3}
                      fontSize={11}
                      fill={AXIS_TEXT}
                      textAnchor="end"
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      {fmtVal(s.kind, v)}
                    </text>
                  </g>
                );
              })}

              <path
                d={d}
                fill="none"
                stroke={color}
                strokeWidth={1.6}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {/* 끝점 — 현재 위치를 선 위에서도 짚어 준다(값은 제목 줄이 이미 크게 띄운다) */}
              <circle
                cx={X(t.last_date)}
                cy={Y(t.last)}
                r={2.6}
                fill={color}
                stroke="#ffffff"
                strokeWidth={1.4}
              />
            </g>
          );
        })}

        {/* x축 — 맨 아래 한 번만 */}
        {xTicks.map((d) => (
          <text
            key={d}
            x={X(d)}
            y={h - 4}
            fontSize={11}
            fill={AXIS_TEXT}
            textAnchor="middle"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {d.slice(2, 7).replace("-", ".")}
          </text>
        ))}

        {/* 크로스헤어 — 세 패널을 동시에 지나야 같은 날짜를 비교할 수 있다 */}
        {hoverX
          ? panels.map(({ s, py0, py1, Y }, i) => {
              const v = lookup[i].get(hoverX);
              return (
                <g key={s.key} style={{ pointerEvents: "none" }}>
                  <line x1={hx} y1={py0} x2={hx} y2={py1} stroke={CROSS} strokeWidth={1} />
                  {v == null ? null : (
                    <circle
                      cx={hx}
                      cy={Y(v)}
                      r={3.4}
                      fill="#ffffff"
                      stroke={COLOR[s.key] ?? INK}
                      strokeWidth={2}
                    />
                  )}
                </g>
              );
            })
          : null}
      </svg>

      {hoverX ? (
        // 툴팁은 SVG 밖 HTML — 카드가 좁아 오른쪽 절반에서는 왼쪽으로 뒤집는다.
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-lg border border-hairline bg-canvas/95 px-2.5 py-1.5 shadow-panel"
          style={{
            left: hx,
            transform: tipRight ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
          }}
        >
          <div className="mb-0.5 text-[12px] tabular-nums text-ink-muted">{hoverX}</div>
          {series.map((s, i) => {
            const v = lookup[i].get(hoverX);
            return (
              <div key={s.key} className="flex items-center gap-1.5 text-[13px] leading-tight">
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-sm"
                  style={{ background: COLOR[s.key] ?? INK }}
                />
                <span className="text-ink-muted">{s.name}</span>
                <b className="ml-auto pl-2 tabular-nums text-ink">
                  {v == null ? EMDASH : fmtVal(s.kind, v)}
                </b>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

// 사분면 한 칸 — 자기 크기를 재서 `Chart` 를 계열 하나로 그린다.
// ★2026-08-31 사용자 지시로 세로 스택 -> **2x2 사분면**. SDLLMTK 가 들어와 계열이 4개가
//   됐는데 세로로 쌓으면 한 패널 높이가 1/4 로 줄어 선이 뭉갠다.
// ★계열마다 축을 따로 갖는 건 그대로다 — GPU 렌탈($1.6~5.7/GPU-hr)과 LLM 토큰 지수(1.05)는
//   단위 자체가 달라 한 축에 겹치면 없는 상관을 만든다(dual-axis 금지).
function QuadPanel({ s }: { s: ComputeIndexSeries }) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} className="min-h-0 min-w-0">
      {box.w > 0 && box.h > 0 ? <Chart series={[s]} w={box.w} h={box.h} /> : null}
    </div>
  );
}

export function ComputeIndexCard() {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["compute-index"],
    queryFn: getComputeIndex,
    refetchInterval: POLL_MS,
  });
  const series = data?.series ?? [];

  // 컨테이너 실측 — 이 카드는 그리드 칸에 맞춰 높이까지 변한다(폭만 재는 다른
  // 차트와 다른 점). 패널 3개가 남은 높이를 3등분한다.
  return (
    <section
      className={cn(
        zoomCls,
        "lg:col-span-3 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
      )}
    >
      {/* 제목 띠 강조색(ge-header) — 2026-08-28 사용자 지시로 페이지 카드가 전부 같은 색. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">컴퓨팅 지수 모니터링</h2>
        <span className="min-w-0 truncate text-[13px] text-white/70">
          Silicon Data GPU 렌탈 지수 · CME 컴퓨트 선물(10/5 상장 예정) 기초지수
        </span>
        {data?.asof ? (
          <span className="ml-auto shrink-0 text-[13px] tabular-nums text-white/60">
            {data.asof} 기준
          </span>
        ) : null}
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      <div className="min-h-0 flex-1 px-1 py-0.5">
        {isLoading ? (
          <Center msg="불러오는 중…" />
        ) : isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : series.length === 0 ? (
          // 서버가 사유를 주면 그대로 띄운다 — "원천 파일이 없습니다 — /srv/..." 처럼
          // 어느 층이 비었는지 카드가 직접 말해야 엉뚱한 데를 뒤지지 않는다.
          <Center
            msg={
              data?.note ??
              "GPU선물지수.xlsx 판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."
            }
            tone={data?.note ? "text-amber-600" : undefined}
          />
        ) : (
          // 사분면 2x2. 계열이 3개면 한 칸이 비고, 5개가 들어오면 자동으로 3행이 된다
          // (`grid-rows-2` 를 박지 않는 이유 — 지수가 늘어도 화면이 안 깨진다).
          <div className="grid h-full min-h-0 grid-cols-1 gap-x-2 gap-y-1 md:grid-cols-2">
            {series.map((s2) => (
              <QuadPanel key={s2.key} s={s2} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <span className={cn("text-[13.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
