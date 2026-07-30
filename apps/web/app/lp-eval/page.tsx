"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getLpEval,
  getLpEvalTs,
  type LpEvalBand,
  type LpEvalBasisStat,
  type LpEvalEtf,
  type LpEvalTs,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { PageContainer } from "@/components/layout/page-header";
import { cn } from "@/lib/utils";

// LP 평가 — 인정 스프레드 틱 분포·통계(일별) + 분봉 추이 차트. 시장 모니터링 하위
// 독립 페이지(iNAV 모니터·WRAP 과 동급). 30초 폴링으로 장중 실시간 누적 반영.
// 카드=틱 히스토그램 + bp 구간별(0~20/20~40/40↑/없음) 유지분수·평균·최빈 통계표,
// 차트=시간(분)×인정스프레드(틱) ETF별 추이.
// 기준 토글 LP(기본, 리테일 제외)/총호가.

const EMDASH = "−";

function fmtNum(value: number | null | undefined, min = 0, max = 2): string {
  if (value == null || !Number.isFinite(value)) return EMDASH;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
}

// 스프레드가 넓을수록(=LP 부실) 진하게.
function lpBucketColor(key: string): string {
  const t = Number(key);
  if (t >= 6) return "bg-rose-500";
  if (t === 5) return "bg-amber-600";
  if (t === 4) return "bg-amber-500";
  return "bg-amber-400"; // 3틱
}

// 구간별 색 — 요약 바(lib/hoga.ts SEVERITY_TEXT)와 같은 뜻의 색을 쓴다.
const BAND_TEXT: Record<string, string> = {
  calm: "text-ink-faint",
  warn: "text-amber-600",
  crit: "text-status-failed",
  none: "text-status-failed",
};

// 통계표 — bp 구간(0~20 / 20~40 / 40↑ / 없음)별 유지분수·평균bp·최빈bp.
// 2026-07-30 사용자 요청으로 구 '평균/최빈/중앙 틱' 4칸을 대체했다. 구간을 나눈 이유:
// 하루 전체 평균 하나로는 "얼마나 오래 나빴는지"가 안 보인다 — 구간별 체류시간이
// 그걸 직접 말해준다. '없음'은 bp 가 없어 유지분수만 센다.
function BandTable({ bands }: { bands: LpEvalBand[] }) {
  const fmtBp = (v: number | null) => (v == null ? "—" : fmtNum(v, 1, 1));
  return (
    <div className="border-t border-hairline pt-1.5">
      <table className="w-full table-fixed border-collapse text-[10.5px] tabular-nums">
        <thead>
          <tr className="text-ink-faint">
            <th className="w-[34%] py-0.5 text-left font-semibold">구간</th>
            <th className="py-0.5 text-right font-semibold">유지</th>
            <th className="py-0.5 text-right font-semibold">평균</th>
            <th className="py-0.5 text-right font-semibold">최빈</th>
          </tr>
        </thead>
        <tbody>
          {bands.map((b) => (
            <tr key={b.key} className={b.minutes === 0 ? "opacity-45" : undefined}>
              <td
                className={cn(
                  "py-[1px] text-left font-bold",
                  BAND_TEXT[b.key] ?? "text-ink",
                )}
              >
                {b.label}
              </td>
              <td className="py-[1px] text-right font-extrabold text-ge-navy">
                {b.minutes}분
              </td>
              <td className="py-[1px] text-right text-ink-muted">{fmtBp(b.mean)}</td>
              <td className="py-[1px] text-right text-ink-muted">{fmtBp(b.mode)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 카드 = 틱 히스토그램(x=틱, y=체류분) + bp 구간별 통계표.
function LpEvalCard({ etf, basis }: { etf: LpEvalEtf; basis: "lp" | "total" }) {
  const stat: LpEvalBasisStat | undefined = etf.basis[basis];
  const bars = useMemo(() => {
    const h = stat?.hist ?? {};
    return Object.keys(h)
      .filter((k) => k !== "none" && k !== "ok")
      .map(Number)
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b)
      .map((t) => ({ tick: t, count: h[String(t)] ?? 0 }));
  }, [stat]);
  const maxCount = Math.max(1, ...bars.map((b) => b.count));
  const hasData = (stat?.total_min ?? 0) > 0;
  const bands = stat?.bands ?? [];
  const bandSum = bands.reduce((s, b) => s + b.minutes, 0);
  const unbanded = stat?.unbanded_min ?? 0;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-canvas p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-[13px] font-bold text-ge-navy">{etf.name || etf.code}</div>
        <div className="shrink-0 text-[10px] font-semibold tabular-nums text-ink-faint">{etf.code}</div>
      </div>
      {!hasData ? (
        <div className="py-6 text-center text-[11px] text-ink-faint">데이터 없음 (장중 누적)</div>
      ) : (
        <>
          {/* 세로 히스토그램 — x=틱, y=체류(분). 막대 위 숫자=분, 아래=틱.
              막대가 없는 날(전 구간 20bp 미만)은 히스토그램을 접고 표만 보여준다. */}
          {bars.length > 0 ? (
            <div className="flex h-[80px] items-end justify-center gap-[3px] px-1">
              {bars.map(({ tick, count }) => (
                <div
                  key={tick}
                  title={`${tick}틱 · ${count}분`}
                  className="flex min-w-0 flex-1 flex-col items-center justify-end gap-[2px]"
                  style={{ maxWidth: 24 }}
                >
                  <span className="text-[8.5px] leading-none tabular-nums text-ink-faint">{count}</span>
                  <div
                    className={cn("w-full rounded-t-[2px]", lpBucketColor(String(tick)))}
                    style={{ height: Math.max(3, (count / maxCount) * 54) }}
                  />
                  <span className="text-[9px] leading-none tabular-nums text-ink-muted">{tick}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-3 text-center text-[11px] font-semibold text-emerald-600">
              20bp 이상 없음 · 전 구간 정상
            </div>
          )}
          {bands.length > 0 ? (
            <BandTable bands={bands} />
          ) : (
            <div className="border-t border-hairline pt-2 text-center text-[10.5px] text-ink-faint">
              구간 통계 없음 (bp 미기록일)
            </div>
          )}
          <div className="flex items-center justify-center gap-2 text-[10.5px] tabular-nums text-ink-muted">
            <span>
              구간 합 <b className="text-ink">{bandSum}</b>분
            </span>
            {unbanded > 0 && (
              <>
                <span className="text-ink-faint">·</span>
                <span title="2026-07-30 이전 표본은 bp 를 기록하지 않아 구간 분류에서 빠집니다">
                  bp 미기록 {unbanded}분
                </span>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ── 시계열 차트 (분봉) — x=시간(분), y=인정 스프레드(틱), ETF별 라인 ───────── */

const CHART_H = 440;
const PAD_L = 34;
const PAD_R = 16;
const PAD_T = 12;
const PAD_B = 30;

// 9종 구분 색.
const SERIES_COLORS = [
  "#4a7ab5", "#e74c3c", "#0a9bc4", "#e8871e", "#7b5ea7",
  "#2aa876", "#c2417a", "#5b7f95", "#b58b00",
];

// 상단 버튼 바용 짧은 이름 (없으면 'ACE ' 접두 제거·코드).
const SHORT_NAMES: Record<string, string> = {
  "414270": "글자", "457480": "테밸", "483320": "엔밸", "483330": "마밸",
  "483340": "구밸", "0079X0": "비밸", "0118Z0": "AI테크", "0180V0": "우주테크",
  "0199C0": "고배당",
};
function shortName(code: string, name: string): string {
  return SHORT_NAMES[code] ?? (name ? name.replace(/^ACE\s*/, "") : code);
}

function hhmmssToMin(ts: string): number {
  const [h, m, s] = ts.split(":").map(Number);
  return (h || 0) * 60 + (m || 0) + (s || 0) / 60;
}
function hhmmToMin(hm: string): number {
  const [h, m] = hm.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}
function minToHHMM(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function LpEvalChart({ ts }: { ts: LpEvalTs }) {
  // 컨테이너 실폭 측정 → viewBox 폭으로 써서 카드 안을 가로로 꽉 채운다(양옆 여백 X).
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(1000);
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

  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const toggle = (code: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const chartW = Math.max(320, w);
  const x0 = hhmmToMin(ts.session.start);
  const x1 = hhmmToMin(ts.session.end);
  const spanX = Math.max(1, x1 - x0);

  // y = 틱. 보이는 시리즈의 min/max (없음=null 은 제외). 이상치 종목을 숨기면 재스케일.
  const { yMin, yMax } = useMemo(() => {
    let mx = 3;
    let mn = 0;
    for (const s of ts.series) {
      if (hidden.has(s.code)) continue;
      for (const [, t] of s.points) {
        if (t == null || !Number.isFinite(t)) continue;
        if (t > mx) mx = t;
        if (t < mn) mn = t;
      }
    }
    return { yMin: mn, yMax: Math.ceil(mx / 2) * 2 };
  }, [ts.series, hidden]);
  const spanY = Math.max(1, yMax - yMin);

  const iw = chartW - PAD_L - PAD_R;
  const ih = CHART_H - PAD_T - PAD_B;
  const X = (min: number) => PAD_L + (iw * (min - x0)) / spanX;
  const Y = (v: number) => PAD_T + (ih * (yMax - v)) / spanY;

  // null=선 끊김.
  const segsOf = (points: [string, number | null][]): string[] => {
    const segs: string[] = [];
    let cur: string[] = [];
    for (const [t, v] of points) {
      if (v == null || !Number.isFinite(v)) {
        if (cur.length) {
          segs.push(cur.join(" "));
          cur = [];
        }
      } else {
        cur.push(`${X(hhmmssToMin(t)).toFixed(1)},${Y(v).toFixed(1)}`);
      }
    }
    if (cur.length) segs.push(cur.join(" "));
    return segs;
  };

  const yStep = Math.max(1, Math.round(spanY / 6));
  const yTicks: number[] = [];
  for (let v = Math.ceil(yMin / yStep) * yStep; v <= yMax + 1e-9; v += yStep) yTicks.push(v);
  const xTicks: number[] = [];
  for (let m = Math.ceil(x0 / 60) * 60; m < x1; m += 60) xTicks.push(m);

  return (
    <div ref={wrapRef}>
      {/* 표시 토글 = 풀폭 N등분 세그먼트 버튼(위, NAV 스타일). 활성=색·네이비 / 비활성=회색. */}
      <div className="mb-3 flex overflow-hidden rounded-lg border border-hairline">
        {ts.series.map((s, i) => {
          const on = !hidden.has(s.code);
          const color = SERIES_COLORS[i % SERIES_COLORS.length];
          return (
            <button
              key={s.code}
              onClick={() => toggle(s.code)}
              title={s.name || s.code}
              className={cn(
                "flex min-w-0 flex-1 items-center justify-center gap-1 border-r border-hairline px-1 py-1.5 text-[11px] font-bold transition-colors last:border-r-0",
                on ? "bg-canvas text-ge-navy" : "bg-canvas-soft text-ink-faint",
              )}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                style={{ background: on ? color : "#cbd3dd" }}
              />
              <span className="truncate">{shortName(s.code, s.name)}</span>
            </button>
          );
        })}
      </div>
      <svg width="100%" height={CHART_H} viewBox={`0 0 ${chartW} ${CHART_H}`} style={{ display: "block" }}>
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={PAD_L} y1={Y(v)} x2={chartW - PAD_R} y2={Y(v)} stroke="#eceff3" strokeWidth={1} />
            <text x={PAD_L - 5} y={Y(v) + 3} textAnchor="end" fontSize={10} fill="#8a95a5">{v}</text>
          </g>
        ))}
        {xTicks.map((m) => (
          <g key={`x${m}`}>
            <line x1={X(m)} y1={PAD_T} x2={X(m)} y2={CHART_H - PAD_B} stroke="#f4f6f8" strokeWidth={1} />
            <text x={X(m)} y={CHART_H - PAD_B + 15} textAnchor="middle" fontSize={10} fill="#8a95a5">
              {minToHHMM(m)}
            </text>
          </g>
        ))}
        {ts.series.map((s, i) =>
          hidden.has(s.code)
            ? null
            : segsOf(s.points).map((pts, j) => (
                <polyline
                  key={`${s.code}-${j}`}
                  points={pts}
                  fill="none"
                  stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                  strokeWidth={1.4}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  opacity={0.9}
                />
              )),
        )}
      </svg>
    </div>
  );
}

export default function LpEvalPage() {
  const [date, setDate] = useState<string | null>(null); // null = 서버 기본(최근 누적일)
  const [basis, setBasis] = useState<"lp" | "total">("lp");
  const [view, setView] = useState<"cards" | "chart">("cards");

  // 서버 표본이 60초마다 1점 쌓이므로 폴링도 1분 주기 — 그보다 자주 불러도 새
  // 데이터가 없어 낭비다(2026-07-28 사용자 요청: 1분 1회 리뉴얼). React Query 는
  // 탭이 백그라운드면 폴링을 자동 중단하고, 차트 조회는 차트 뷰일 때만 돈다.
  const query = useQuery({
    queryKey: ["lpEval", date],
    queryFn: () => getLpEval(date ?? undefined),
    refetchInterval: 60_000,
  });
  const tsQuery = useQuery({
    queryKey: ["lpEvalTs", date, basis],
    queryFn: () => getLpEvalTs(date ?? undefined, basis),
    refetchInterval: 60_000,
    enabled: view === "chart",
  });

  const d = query.data ?? null;
  const tsData = tsQuery.data ?? null;
  const empty =
    d != null && d.etfs.every((e) => (e.basis[basis]?.total_min ?? 0) === 0);
  const chartEmpty =
    tsData != null && tsData.series.every((s) => s.points.length === 0);

  // 차트 뷰에선 시간이 기록된 날(28일~)만 선택지에 — 27일자는 시간 미기록이라 제외.
  const dropdownDates = view === "chart" ? tsData?.available_dates ?? [] : d?.available_dates ?? [];
  const activeTradeDate = view === "chart" ? tsData?.trade_date : d?.trade_date;
  const curDate = date ?? activeTradeDate ?? "";

  return (
    <>
      <Topbar
        title="LP 평가"
        subtitle="시장 모니터링 · LP 인정 스프레드 bp 구간별 통계 / 추이"
        status={
          d ? (
            <span className="truncate text-[11px] tabular-nums text-slate-400">
              {curDate} · 표본 {d.session.start}~{d.session.end}({d.session_minutes}분) · 1,000주↑ 인정호가 · 구간 {d.warn_bp}/{d.crit_bp}bp · 없음=인정호가 부재
            </span>
          ) : undefined
        }
        actions={
          <>
            <div className="flex overflow-hidden rounded-lg border border-hairline text-[12px] font-bold">
              {(["cards", "chart"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={cn(
                    "px-2.5 py-1 transition-colors",
                    view === v
                      ? "bg-ge-navy text-white"
                      : "bg-canvas text-ink-muted hover:bg-canvas-soft",
                  )}
                >
                  {v === "cards" ? "카드" : "차트"}
                </button>
              ))}
            </div>
            <div className="flex overflow-hidden rounded-lg border border-hairline text-[12px] font-bold">
              {(["lp", "total"] as const).map((b) => (
                <button
                  key={b}
                  onClick={() => setBasis(b)}
                  className={cn(
                    "px-2.5 py-1 transition-colors",
                    basis === b
                      ? "bg-ge-navy text-white"
                      : "bg-canvas text-ink-muted hover:bg-canvas-soft",
                  )}
                >
                  {b === "lp" ? "LP" : "총호가"}
                </button>
              ))}
            </div>
            {dropdownDates.length > 0 && (
              <select
                value={curDate}
                onChange={(e) => setDate(e.target.value)}
                className="rounded-lg border border-hairline bg-canvas px-2 py-1 text-[12px] font-semibold text-ink-muted"
              >
                {dropdownDates.map((dt) => (
                  <option key={dt} value={dt}>
                    {dt}
                  </option>
                ))}
              </select>
            )}
          </>
        }
      />
      <PageContainer wide>
        {view === "chart" ? (
          tsQuery.isError ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오지 못했습니다.</p>
          ) : !tsData ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오는 중…</p>
          ) : chartEmpty ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              {curDate} 시간 기록이 없습니다. 분단위 시계열은 2026-07-28 부터 쌓입니다.
            </p>
          ) : (
            <div className="rounded-2xl border border-hairline bg-canvas p-4 shadow-card">
              <LpEvalChart ts={tsData} />
            </div>
          )
        ) : query.isError ? (
          <p className="py-10 text-center text-sm text-ink-muted">불러오지 못했습니다.</p>
        ) : !d ? (
          <p className="py-10 text-center text-sm text-ink-muted">불러오는 중…</p>
        ) : empty ? (
          <p className="py-10 text-center text-sm text-ink-muted">
            {curDate} 누적 데이터가 없습니다. 정규장({d.session.start}~{d.session.end}) 중 자동으로 쌓입니다.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {d.etfs.map((etf) => (
              <LpEvalCard key={etf.code} etf={etf} basis={basis} />
            ))}
          </div>
        )}
        <div className="mt-4 border-t border-hairline pt-2 text-[11px] text-ink-faint">
          기준{" "}
          {basis === "lp"
            ? "LP 물량 — 리테일 제외, LP 성실도"
            : "총호가 — 화면 알림 전광판과 동일"}{" "}
          ·{" "}
          {view === "chart"
            ? "x=시간(분) · y=인정 스프레드(틱) · 선 끊김=없음(인정호가 부재) · 범례 클릭=표시 토글"
            : `통계표 = bp 구간별 유지시간(분)·평균bp·최빈bp(1bp 단위 반올림 최다) · 구간 합 = 그 날 표본 분수 · 히스토그램은 ≥${d?.warn_bp ?? 20}bp 틱만`}
        </div>
      </PageContainer>
    </>
  );
}
