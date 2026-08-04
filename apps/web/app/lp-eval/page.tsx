"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  getLpEval,
  getLpEvalTs,
  type LpEvalBand,
  type LpEvalBasisStat,
  type LpEvalEtf,
  type LpEvalTs,
  type LpEvalWindow,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { PageContainer } from "@/components/layout/page-header";
import { cn } from "@/lib/utils";

// LP 평가 — 인정 스프레드 틱 분포·통계(일별) + 분봉 추이 차트. 시장 모니터링 하위
// 독립 페이지(iNAV 모니터·WRAP 과 동급). 30초 폴링으로 장중 실시간 누적 반영.
// 화면은 카드 그리드 하나뿐이다 — 카드=틱 히스토그램 + bp 구간별(0~20/20~40/40↑/없음)
// 유지분수·비중·평균 통계표 + 대표값 2단(평균 유지 스프레드 bp / 평균 실제괴리 %).
// 카드를 누르면 그 종목의 분봉 추이(시간×인정스프레드 틱) 상세창이 열린다 — 구 카드/
// 차트 Topbar 토글은 폐기했다(2026-08-04). 기준 토글 LP(기본, 리테일 제외)/총호가.

const EMDASH = "−";

function fmtNum(value: number | null | undefined, min = 0, max = 2): string {
  if (value == null || !Number.isFinite(value)) return EMDASH;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
}

// 히스토그램 첫 막대 — 서버가 0~2틱을 한 칸으로 묶어 보내는 키.
const LOW_TICK_KEY = "0-2";
const LOW_TICK_MAX = 2;

// 차트 배경 밴드 색 — 히스토그램 막대색과 같은 뜻(초록=촘촘, 빨강=물량X).
const BAND_FILL = { low: "rgba(42,168,118,0.13)", none: "rgba(231,76,60,0.13)" };

// 스프레드가 넓을수록(=LP 부실) 진하게. 0~2틱은 '가장 촘촘'이라 초록.
function lpBucketColor(key: string): string {
  if (key === LOW_TICK_KEY) return "bg-emerald-400";
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

// 통계표 — bp 구간(0~20 / 20~40 / 40↑ / 없음)별 유지분수·비중·평균bp.
// 2026-07-30 사용자 요청으로 구 '평균/최빈/중앙 틱' 4칸을 대체했고, 2026-08-04 에
// '최빈' 칸을 '비중'(유지분수 / 총 장 기간 375분)으로 갈았다 — 최빈 bp 는 1bp 반올림
// 최다값이라 해석이 어렵고, "하루의 몇 %를 그 상태로 보냈나"가 LP 평가에 곧바로
// 쓰인다. 분모가 표본분수가 아니라 장 전체라 수신이 끊긴 만큼 합이 100% 에 못 닿는다.
function BandTable({ bands }: { bands: LpEvalBand[] }) {
  const fmtBp = (v: number | null) => (v == null ? "—" : fmtNum(v, 1, 1));
  return (
    <div className="border-t border-hairline pt-1.5">
      <table className="w-full table-fixed border-collapse text-[10.5px] tabular-nums">
        <thead>
          <tr className="text-ink-faint">
            <th className="w-[32%] py-0.5 text-left font-semibold">구간</th>
            <th className="py-0.5 text-right font-semibold">유지</th>
            <th className="py-0.5 text-right font-semibold">비중</th>
            <th className="py-0.5 text-right font-semibold">평균</th>
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
              <td className="py-[1px] text-right font-semibold text-ink-muted">
                {b.minutes}분
              </td>
              <td className="py-[1px] text-right font-extrabold text-ge-navy">
                {fmtNum(b.share, 1, 1)}%
              </td>
              <td className="py-[1px] text-right text-ink-muted">{fmtBp(b.mean)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 대표값 색 — 구간 경계와 같은 기준으로 평균 bp 를 물들인다(표의 구간 색과 일치).
function meanBpTone(bp: number | null, warnBp: number, critBp: number): string {
  if (bp == null) return "text-ink-faint";
  if (bp >= critBp) return "text-status-failed";
  if (bp >= warnBp) return "text-amber-600";
  return "text-emerald-600";
}

// 괴리 색 — iNAV 모니터의 DeviationValue 와 같은 경계·같은 뜻(배경만 뺐다).
// |값| 1% 넘어가면 크기가 먼저 눈에 띄어야 해서 부호색을 버리고 경고색으로 간다.
function devTone(pct: number | null): string {
  if (pct == null) return "text-ink-faint";
  const abs = Math.abs(pct);
  if (abs >= 2) return "text-status-failed";
  if (abs >= 1) return "text-amber-600";
  if (pct > 0) return "text-status-failed";
  if (pct < 0) return "text-status-running";
  return "text-ink";
}

// 괴리 표기 — iNAV 모니터 signedPct 와 동일(부호 + 소수 2자리).
function fmtSignedPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

// 카드 하단 통계 박스 — '평균 유지 스프레드'와 '평균 실제괴리'가 같은 뼈대를 쓴다.
// showWindows(Topbar '구간분석' 토글)면 5구간, 아니면 전 구간 단일 대표값 + 밑줄.
// 두 갈래·두 박스 모두 h-[64px] 로 묶어야 카드끼리 줄이 맞는다 (2026-08-04).
// 5구간 모드는 칸이 좁아 단위를 칸마다 붙이지 못하므로 제목에 '(bp)'·'(%)'로 낸다.
function CardStatBox({
  title,
  unit,
  showWindows,
  windows,
  value,
  sub,
  format,
  tone,
}: {
  title: string;
  unit: string;
  showWindows: boolean;
  windows: LpEvalWindow[];
  value: number | null;
  sub: string;
  format: (v: number | null) => string;
  tone: (v: number | null) => string;
}) {
  if (showWindows && windows.length > 0) {
    return (
      <div className="flex h-[64px] flex-col justify-center rounded-lg bg-canvas-soft px-1 py-1">
        <div className="text-center text-[10.5px] font-bold uppercase leading-[13px] tracking-wide text-ink">
          {title} ({unit})
        </div>
        <div className="mt-0.5 grid grid-cols-5 divide-x divide-hairline">
          {windows.map((w) => (
            <div
              key={w.key}
              className="overflow-hidden px-px text-center"
              title={`${w.label} · ${w.minutes}분 평균`}
            >
              <div className="whitespace-nowrap text-[8.5px] leading-[12px] tabular-nums text-ink-faint">
                {w.short}
              </div>
              <div
                className={cn(
                  "whitespace-nowrap text-[12.5px] font-extrabold leading-[18px] tabular-nums",
                  tone(w.mean),
                )}
              >
                {format(w.mean)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-[64px] flex-col justify-center rounded-lg bg-canvas-soft px-2 py-1.5 text-center">
      <div className="text-[10.5px] font-bold uppercase leading-[13px] tracking-wide text-ink">
        {title}
      </div>
      <div className="flex items-baseline justify-center gap-1">
        <span
          className={cn(
            "text-[19px] font-extrabold leading-[23px] tabular-nums",
            tone(value),
          )}
        >
          {format(value)}
        </span>
        <span className="text-[11px] font-bold text-ink-muted">{unit}</span>
      </div>
      <div className="text-[9.5px] leading-[13px] tabular-nums text-ink-faint">{sub}</div>
    </div>
  );
}

// 카드 = 틱 히스토그램(x=틱, y=체류분) + bp 구간별 통계표 + 대표값(일 평균 bp).
function LpEvalCard({
  etf,
  basis,
  warnBp,
  critBp,
  sessionMinutes,
  splitWindows,
  onOpen,
}: {
  etf: LpEvalEtf;
  basis: "lp" | "total";
  warnBp: number;
  critBp: number;
  sessionMinutes: number;
  splitWindows: boolean;
  onOpen: () => void;
}) {
  const stat: LpEvalBasisStat | undefined = etf.basis[basis];
  // 막대 = 0~2틱 묶음(있으면 맨 앞) + 3틱부터 틱별. 서버가 원시 틱 분포를 주므로
  // 20bp 미만이라 접혀 있던 촘촘한 구간까지 다 보인다. 시계열이 없는 과거일은
  // 서버가 구 집계 버킷(none/ok/틱)으로 폴백하는데, 그 땐 0-2 키가 없어 숫자 틱만 뜬다.
  const bars = useMemo(() => {
    const h = stat?.hist ?? {};
    const out: { key: string; label: string; count: number }[] = [];
    if (LOW_TICK_KEY in h) {
      out.push({ key: LOW_TICK_KEY, label: "0~2", count: h[LOW_TICK_KEY] ?? 0 });
    }
    Object.keys(h)
      .filter((k) => k !== "none" && k !== "ok" && k !== LOW_TICK_KEY)
      .map(Number)
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b)
      .forEach((t) =>
        out.push({ key: String(t), label: String(t), count: h[String(t)] ?? 0 }),
      );
    return out;
  }, [stat]);
  const maxCount = Math.max(1, ...bars.map((b) => b.count));
  const hasData = (stat?.total_min ?? 0) > 0;
  const bands = stat?.bands ?? [];
  const bandSum = bands.reduce((s, b) => s + b.minutes, 0);
  const unbanded = stat?.unbanded_min ?? 0;
  const meanBp = stat?.mean_bp ?? null;
  const bandedMin = stat?.banded_min ?? 0;
  const noneMin = stat?.none_min ?? 0;
  // 중국 바스켓 3종에만 서버가 채워 보낸다(나머지는 undefined → 단일 대표값).
  const windows = stat?.windows ?? [];
  // 실제괴리는 basis 토글과 무관해서 ETF 단위(etf.dev)로 온다.
  const dev = etf.dev;

  // 카드 전체가 클릭 대상 — 누르면 그 종목의 분봉 추이 상세창이 열린다(iNAV 모니터의
  // 구성종목 모달과 같은 동작). <button> 으로 감싸면 안쪽 <table> 이 버튼의 콘텐츠
  // 모델을 위반하므로 role="button" + 키보드 핸들러로 접근성만 맞춘다.
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      title={`${etf.name || etf.code} 분봉 추이 보기`}
      className="flex cursor-pointer flex-col gap-2 rounded-xl border border-hairline bg-canvas p-3 text-left transition hover:border-ge-navy/40 hover:shadow-card focus:outline-none focus-visible:ring-2 focus-visible:ring-ge-navy/50"
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-[13px] font-bold text-ge-navy">{etf.name || etf.code}</div>
        <div className="shrink-0 text-[10px] font-semibold tabular-nums text-ink-faint">{etf.code}</div>
      </div>
      {!hasData ? (
        <div className="py-6 text-center text-[11px] text-ink-faint">데이터 없음 (장중 누적)</div>
      ) : (
        <>
          {/* 세로 히스토그램 — x=틱, y=체류(분). 막대 위 숫자=분, 아래=틱.
              첫 막대는 0~2틱 묶음(초록). 막대가 하나도 없는 건 그 날 인정 스프레드가
              한 번도 안 잡힌 경우(전 구간 '없음')뿐이라 문구로 대체한다.
              슬롯을 h-[80px] 로 고정해야 그 종목만 아래 통계표·대표값이 위로 올라
              붙지 않고 카드끼리 줄이 맞는다 (2026-08-04). */}
          {bars.length > 0 ? (
            <div className="flex h-[80px] items-end justify-center gap-[3px] px-1">
              {bars.map(({ key, label, count }) => (
                <div
                  key={key}
                  title={`${label}틱 · ${count}분`}
                  className="flex min-w-0 flex-1 flex-col items-center justify-end gap-[2px]"
                  style={{ maxWidth: 24 }}
                >
                  <span className="text-[8.5px] leading-none tabular-nums text-ink-faint">{count}</span>
                  <div
                    className={cn("w-full rounded-t-[2px]", lpBucketColor(key))}
                    style={{ height: Math.max(3, (count / maxCount) * 54) }}
                  />
                  <span className="text-[9px] leading-none tabular-nums text-ink-muted">{label}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-[80px] items-center justify-center px-1 text-center text-[11px] font-semibold text-ink-faint">
              틱 표본 없음
            </div>
          )}
          {bands.length > 0 ? (
            <BandTable bands={bands} />
          ) : (
            <div className="border-t border-hairline pt-2 text-center text-[10.5px] text-ink-faint">
              구간 통계 없음 (bp 미기록일)
            </div>
          )}
          {/* 대표값 2단 — 위: LP 가 얼마나 좁게 깔았나(스프레드), 아래: 그 호가가
              공정가에서 얼마나 떨어져 있었나(실제괴리). 둘 다 있어야 LP 평가가 된다.
              스프레드는 '없음'(인정호가 부재) 분이 bp 가 없어 분모에서 빠지므로 그
              분수를 밑줄에 적고, 괴리는 부호 상쇄를 드러내려고 |평균|을 같이 적는다.
              Topbar '구간분석' 이 켜지면 둘 다 5구간으로 쪼갠다(전 종목). */}
          <CardStatBox
            title="평균 유지 스프레드"
            unit="bp"
            showWindows={splitWindows}
            windows={windows}
            value={meanBp}
            sub={`${bandedMin}분 평균${noneMin > 0 ? ` · 없음 ${noneMin}분 제외` : ""}`}
            format={(v) => (v == null ? EMDASH : fmtNum(v, 1, 1))}
            tone={(v) => meanBpTone(v, warnBp, critBp)}
          />
          <CardStatBox
            title="평균 실제괴리"
            unit="%"
            showWindows={splitWindows}
            windows={dev?.windows ?? []}
            value={dev?.mean ?? null}
            sub={
              dev?.abs_mean == null
                ? `${dev?.minutes ?? 0}분 평균`
                : `${dev.minutes}분 · |평균| ${dev.abs_mean.toFixed(2)}%`
            }
            format={fmtSignedPct}
            tone={devTone}
          />
          <div className="flex items-center justify-center gap-2 text-[10.5px] tabular-nums text-ink-muted">
            <span title={`총 장 기간 ${sessionMinutes}분 대비 표본이 쌓인 분수`}>
              구간 합 <b className="text-ink">{bandSum}</b>/{sessionMinutes}분
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

// focusCode 가 오면 그 종목만 켠 채로 시작한다 — 상세창은 한 종목을 보러 여는
// 자리라서다. 나머지 8종은 범례에 그대로 남아 있어 눌러서 겹쳐 볼 수 있다
// (구 '차트' 탭이 하던 종목 간 비교를 상세창 안에 그대로 남긴 것).
function LpEvalChart({ ts, focusCode }: { ts: LpEvalTs; focusCode?: string }) {
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

  const [hidden, setHidden] = useState<Set<string>>(() =>
    focusCode
      ? new Set(ts.series.map((s) => s.code).filter((c) => c !== focusCode))
      : new Set(),
  );
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

  // 배경 밴드 — 포커스 종목의 상태 구간을 칠한다. 두 가지를 구분하려는 것:
  //   · none : tick=null(인정호가 부재) = 선이 실제로 끊기는 구간. 왜 끊겼는지 표시.
  //   · low  : 0~2틱 = 끊긴 게 아니라 바닥에 붙어 그려지는 구간(가장 촘촘한 상태).
  // 포커스가 없으면(여러 종목 비교) 칠하지 않는다 — 9종 밴드가 겹치면 못 읽는다.
  // 표본 1건이 덮는 폭은 SAMPLE_SPAN_MIN 으로 막는다. 그래야 수신이 끊겨 표본 자체가
  // 없는 구간(오늘 실측 최장 2.7분, collector 재기동)을 밴드가 넘겨짚어 메우지 않는다.
  const SAMPLE_SPAN_MIN = 1.2;
  const bgBands = useMemo(() => {
    if (!focusCode) return [] as { x0: number; x1: number; kind: "low" | "none" }[];
    const pts = ts.series.find((s) => s.code === focusCode)?.points ?? [];
    const out: { x0: number; x1: number; kind: "low" | "none" }[] = [];
    let cur: { x0: number; x1: number; kind: "low" | "none" } | null = null;
    for (let i = 0; i < pts.length; i++) {
      const [t, v] = pts[i];
      const kind: "low" | "none" | null =
        v == null || !Number.isFinite(v) ? "none" : v <= LOW_TICK_MAX ? "low" : null;
      const m0 = hhmmssToMin(t);
      const next = i + 1 < pts.length ? hhmmssToMin(pts[i + 1][0]) : m0 + 1;
      const m1 = Math.min(next, m0 + SAMPLE_SPAN_MIN);
      if (kind == null) {
        if (cur) out.push(cur);
        cur = null;
        continue;
      }
      if (cur && cur.kind === kind && m0 - cur.x1 <= 0.3) cur.x1 = m1;
      else {
        if (cur) out.push(cur);
        cur = { x0: m0, x1: m1, kind };
      }
    }
    if (cur) out.push(cur);
    return out;
  }, [ts.series, focusCode]);

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
        {/* 상태 밴드는 격자·선보다 먼저 그려 뒤로 깔린다. */}
        {bgBands.map((b, i) => (
          <rect
            key={`bg${i}`}
            x={X(b.x0)}
            y={PAD_T}
            width={Math.max(0.5, X(b.x1) - X(b.x0))}
            height={CHART_H - PAD_T - PAD_B}
            fill={BAND_FILL[b.kind]}
          >
            <title>
              {b.kind === "none"
                ? `없음(인정호가 부재) ${minToHHMM(b.x0)}~${minToHHMM(b.x1)}`
                : `0~2틱 ${minToHHMM(b.x0)}~${minToHHMM(b.x1)}`}
            </title>
          </rect>
        ))}
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
      {bgBands.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[10px] text-ink-muted">
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-5 rounded-[2px]"
              style={{ background: BAND_FILL.none }}
            />
            없음 — 인정호가 부재, 선이 끊기는 구간
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-5 rounded-[2px]"
              style={{ background: BAND_FILL.low }}
            />
            0~2틱 — 가장 촘촘, 선은 바닥에 붙어 이어짐
          </span>
          <span className="text-ink-faint">
            밴드 기준 ={" "}
            {shortName(
              focusCode ?? "",
              ts.series.find((s) => s.code === focusCode)?.name ?? "",
            )}{" "}
            · 흰 구간에 선까지 없으면 수신 끊김
          </span>
        </div>
      )}
    </div>
  );
}

/* ── 상세창 — 카드 클릭 시 그 종목의 분봉 추이 (구 '차트' 탭을 여기로 옮김) ──── */

function LpEvalDetailModal({
  etf,
  basis,
  tradeDate,
  ts,
  isError,
  onClose,
}: {
  etf: LpEvalEtf;
  basis: "lp" | "total";
  tradeDate: string;
  ts: LpEvalTs | null;
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

  const stat = etf.basis[basis];
  const sub: string[] = [tradeDate, basis === "lp" ? "LP 물량" : "총호가"];
  if (stat?.mean_bp != null) sub.push(`평균 스프레드 ${fmtNum(stat.mean_bp, 1, 1)}bp`);
  if (etf.dev?.mean != null) sub.push(`평균 실제괴리 ${fmtSignedPct(etf.dev.mean)}%`);

  // 이 종목에 점이 하나도 없으면 차트를 띄우는 의미가 없다. 시계열은 2026-07-28
  // 부터라 그 전 날짜를 고른 경우가 대부분이다.
  const points = ts?.series.find((s) => s.code === etf.code)?.points ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-canvas shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-extrabold text-ge-navy">
              {(etf.name || etf.code) + " · " + etf.code}
            </h2>
            <div className="mt-0.5 text-[12px] tabular-nums text-ink-muted">
              {sub.join(" · ")}
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
          {isError ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오지 못했습니다.</p>
          ) : !ts ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오는 중…</p>
          ) : points.length === 0 ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              {tradeDate} 시간 기록이 없습니다. 분단위 시계열은 2026-07-28 부터 쌓입니다.
            </p>
          ) : (
            <>
              <LpEvalChart ts={ts} focusCode={etf.code} />
              <div className="mt-3 border-t border-hairline pt-2 text-[11px] text-ink-faint">
                x=시간(분) · y=인정 스프레드(틱) · 배경 밴드=그 종목 상태(아래 범례) ·
                상단 범례 클릭=다른 종목 겹쳐 보기
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LpEvalPage() {
  const [date, setDate] = useState<string | null>(null); // null = 서버 기본(최근 누적일)
  const [basis, setBasis] = useState<"lp" | "total">("lp");
  // 구간분석 — off(기본)면 카드가 전 구간 평균 하나씩만, on 이면 5구간으로 쪼갠다.
  // 기본을 off 로 둔 건 9종을 훑을 땐 종목당 숫자 2개가 제일 빨리 읽히기 때문이다.
  const [splitWindows, setSplitWindows] = useState(false);
  // 카드 클릭으로 열리는 상세창의 종목. null = 닫힘 (2026-08-04: 구 카드/차트 토글을
  // 폐기하고 차트를 이 상세창으로 옮겼다 — 페이지는 항상 카드로 진입한다).
  const [modalCode, setModalCode] = useState<string | null>(null);

  // 서버 표본이 60초마다 1점 쌓이므로 폴링도 1분 주기 — 그보다 자주 불러도 새
  // 데이터가 없어 낭비다(2026-07-28 사용자 요청: 1분 1회 리뉴얼). React Query 는
  // 탭이 백그라운드면 폴링을 자동 중단하고, 시계열 조회는 상세창이 열렸을 때만 돈다.
  const query = useQuery({
    queryKey: ["lpEval", date],
    queryFn: () => getLpEval(date ?? undefined),
    refetchInterval: 60_000,
  });
  const tsQuery = useQuery({
    queryKey: ["lpEvalTs", date, basis],
    queryFn: () => getLpEvalTs(date ?? undefined, basis),
    refetchInterval: 60_000,
    enabled: modalCode != null,
  });

  const d = query.data ?? null;
  const tsData = tsQuery.data ?? null;
  const empty =
    d != null && d.etfs.every((e) => (e.basis[basis]?.total_min ?? 0) === 0);

  const dropdownDates = d?.available_dates ?? [];
  const curDate = date ?? d?.trade_date ?? "";
  const modalEtf = modalCode
    ? d?.etfs.find((e) => e.code === modalCode) ?? null
    : null;

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
            <button
              onClick={() => setSplitWindows((v) => !v)}
              title="구간분석 — 09:05~10:30 / 10:30~13:00 / 13:00~14:00 / 14:00~15:30 / 전체"
              className={cn(
                "rounded-lg border border-hairline px-2.5 py-1 text-[12px] font-bold transition-colors",
                splitWindows
                  ? "bg-ge-navy text-white"
                  : "bg-canvas text-ink-muted hover:bg-canvas-soft",
              )}
            >
              구간분석 {splitWindows ? "ON" : "OFF"}
            </button>
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
        {query.isError ? (
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
              <LpEvalCard
                key={etf.code}
                etf={etf}
                basis={basis}
                warnBp={d.warn_bp}
                critBp={d.crit_bp}
                sessionMinutes={d.session_minutes}
                splitWindows={splitWindows}
                onOpen={() => setModalCode(etf.code)}
              />
            ))}
          </div>
        )}
        <div className="mt-4 border-t border-hairline pt-2 text-[11px] text-ink-faint">
          기준{" "}
          {basis === "lp"
            ? "LP 물량 — 리테일 제외, LP 성실도"
            : "총호가 — 화면 알림 전광판과 동일"}{" "}
          ·{" "}
          {`카드 클릭 = 그 종목 분봉 추이 · 통계표 = bp 구간별 유지시간(분)·비중(유지분 / 총 장 기간 ${d?.session_minutes ?? 375}분)·평균bp · 카드 대표값 = 평균 유지 스프레드(bp, '없음' 제외) / 평균 실제괴리(%, 자체 iNAV 기준·부호는 프리미엄+/디스카운트−) · 히스토그램 = 원시 틱 분포(0~2틱 한 막대 + 3틱부터 틱별, '없음' 제외)`}
          {splitWindows && (
            <>
              {" "}
              · 구간분석 ON — 숫자 위 라벨은 <b className="text-ink-muted">구간 시작시각</b>
              (09:05→10:30 / 10:30→13:00 / 13:00→14:00 / 14:00→15:30 / 전체=09:05~15:20).
              14:00 구간은 표본이 LP 의무 종료인 15:20 에서 끊긴다
            </>
          )}
        </div>
      </PageContainer>
      {modalEtf && (
        <LpEvalDetailModal
          key={modalEtf.code}
          etf={modalEtf}
          basis={basis}
          tradeDate={curDate}
          ts={tsData}
          isError={tsQuery.isError}
          onClose={() => setModalCode(null)}
        />
      )}
    </>
  );
}
