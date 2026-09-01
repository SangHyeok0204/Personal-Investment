"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getNpmDownloads,
  getOpenRouterTokenUsage,
  getVscodeInstalls,
  type AiSeries,
  type NpmDownloads,
  type OpenRouterTokenUsage,
  type VscodeInstalls,
} from "@/lib/api";
import { TimeSeriesChart, lastValue } from "@/components/ai-key-data/timeseries-chart";
import { StaleBadge } from "@/components/ai-key-data/stale-badge";
import { TabChips } from "@/components/ai-key-data/tab-chips";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [AI Key Data] AI 사용량 — 메인 페이지 D2안(2026-08-28 사용자 승인: "ADP·FOMC
// 내재확률을 메인에서 내리고 그 2칸에 AI 사용량 카드를 넣어도 되는가" → 예)으로
// 신설. 그리드는 무변경(`lg:grid-cols-6 lg:grid-rows-2`) — 이 카드가 정확히
// 비워진 2칸(구 ADP colSpan=1 + 구 fomc_prob colSpan=1)을 그대로 물려받는다.
// ADP·fomc_prob 은 삭제되지 않았다 — 사용자 지시로 하위 페이지 `/ai-key-data/epoch`
// 자체가 없어지면서(page.tsx 주석 참조) 메인의 "매크로" 탭으로 편입됐다(데이터 소실 0).
//
// 탭: OpenRouter 토큰 / npm 다운로드 / VS Code 설치 — 전부 "AI 채택·사용량
// 프록시"라 한 카드로 묶었다(ws2 설계 §2.4). Epoch(산업 구조 통계)과는 성격이
// 달라 여기 섞지 않는다.
// ★방문한 탭만 fetch — price-board-card.tsx:80-87 탭 선례와 같은 이유로 비활성
//   탭은 `enabled: false`. 전환 후 재방문은 캐시라 즉시.
// ★신규 쿼리에만 `refetchOnWindowFocus:true` — 전역 providers.tsx 기본값(false)은
//   그대로 둔다. 배경 탭이 no-op refetch 로 밤새 어제 데이터를 보여주는 문제
//   (query-core queryObserver.ts, ws2 설계 §5.2)의 처방은 신규 쿼리 한정이다.
//
// ★★2026-08-28 실제 백엔드로 검증(curl) — OpenRouter·npm 은 `totals.daily`/
//   `totals.daily_ma7` 를 준다(둘 다 총합 시계열). 벤더/패키지별 목록은 시계열이
//   아니라 스냅샷(최근 창 합계 1개)이라 차트에 선으로 넣지 않고 숫자 뱃지로만
//   보여준다 — 10여 개 선을 2칸 카드에 욱여넣으면 안 읽힌다.

const PALETTE = ["#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7"];
const RAW_COLOR = "#c7cedb"; // raw 톱니는 옅게 — ma7 이 주역
const ANOM_COLOR = "#e11d48"; // 이상치 보간 구간 — rose. 색 규약: rose=주목
// 모델별 10계열용. 4색으로는 구분이 안 돼 색상환을 넓게 쓴다(흰 캔버스 기준 명도 검증).
const MODEL_PALETTE = [
  "#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7", "#c0392b",
  "#16a085", "#d4a017", "#5d6d7e", "#8e44ad", "#2e86c1",
];

type Tab = "openrouter" | "npm" | "vscode";
const TABS: { key: Tab; label: string }[] = [
  { key: "openrouter", label: "OpenRouter 토큰" },
  { key: "npm", label: "npm 다운로드" },
  { key: "vscode", label: "VS Code 설치" },
];

function fmtCompact(v: number): string {
  // ★2026-08-31 방어 추가. 계약이 어긋나 undefined 가 들어오면 마지막 줄의
  //   `v.toLocaleString()` 이 TypeError 로 카드를 통째로 죽인다(실제 사고).
  //   숫자가 아니면 조용히 대시로 떨어뜨리고, 원인은 타입 쪽에서 고친다.
  if (!Number.isFinite(v)) return EMDASH;
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US");
}

export function AiUsageCard({ colSpan = 2 }: { colSpan?: number }) {
  const { zoomed, toggle, zoomCls } = useCardZoom();
  const [tab, setTab] = useState<Tab>("openrouter");
  const [showRaw, setShowRaw] = useState(false);
  // ★2026-09-01 사용자 지시 — OpenRouter 토큰 탭의 **기본은 전체 합계**다.
  //   `showRaw` 를 같이 쓰면 npm 탭의 "raw 보기" 기본값까지 뒤집힌다(뜻이 다른 토글이다).
  //   그래서 이 탭 전용 상태로 분리한다.
  const [orTotal, setOrTotal] = useState(true);

  const orQ = useQuery<OpenRouterTokenUsage>({
    queryKey: ["ai-token-usage"],
    queryFn: getOpenRouterTokenUsage,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "openrouter",
  });
  const npmQ = useQuery<NpmDownloads>({
    queryKey: ["npm-downloads"],
    queryFn: getNpmDownloads,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "npm",
  });
  const vsQ = useQuery<VscodeInstalls>({
    queryKey: ["vscode-installs"],
    queryFn: getVscodeInstalls,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "vscode",
  });

  const active = tab === "openrouter" ? orQ : tab === "npm" ? npmQ : vsQ;
  const { isLoading, isError } = active;

  let plotted: AiSeries[] = [];
  let colors: string[] = PALETTE;
  let asof: string | null = null;
  let note: string | null = null;
  let raw: AiSeries[] = [];
  // 스냅샷 뱃지(벤더/패키지 상위) — 차트가 아니라 숫자로만 노출한다.
  let badges: { key: string; label: string; value: string }[] = [];
  let footnote: string | null = null;
  // VS Code 전용 — 증분(span_days 환산)·정정(revisions)·영구 결측(gaps).
  let increment: { text: string; negative: boolean } | null = null;
  let revisionLines: string[] = [];
  let gapsNote: string | null = null;

  if (tab === "openrouter") {
    const d = orQ.data;
    asof = d?.asof ?? null;
    note = d?.note ?? null;
    // ★★2026-08-31 사용자 지시 — **모델별로 분리해서 그린다.** 서버가 이미 최근 창(30일)
    //   상위 10개 모델의 시계열(`models[].points`)을 주고 있었는데 화면이 총합만 그리고
    //   있었다. 총합 한 줄로는 "어느 모델이 끌어올렸는지"가 안 보인다.
    // ⚠️총합(605일)과 벤더별(전 구간)은 계열 수가 크게 달라 같이 그리면 총합이 묻힌다.
    //   토글(`orTotal`)로 갈라 둔다. **기본은 전체 합계**(2026-09-01 사용자 지시) —
    //   먼저 "전체가 얼마나 늘었나"를 보고, 필요할 때 벤더별로 쪼개 본다.
    // ⚠️`points` 의 null 은 "그날 top-50 밖"이지 0이 아니다 — 차트가 선을 끊는다.
    if (d?.vendor_series?.length) {
      plotted = d.vendor_series.map((v) => ({
        key: v.key,
        label: v.name,
        kind: "line" as const,
        last: lastValue(v.points),
        points: v.points,
      }));
    }
    if (d?.totals) {
      raw = [
        {
          key: "ma7",
          label: "전체 합계 7일 평균",
          kind: "line",
          last: lastValue(d.totals.daily_ma7),
          points: d.totals.daily_ma7,
        },
      ];
      if (orTotal) plotted = raw;
    }
    badges = (d?.vendors ?? [])
      .slice()
      .sort((a, b) => b.tokens - a.tokens)
      .slice(0, 4)
      .map((v) => ({ key: v.key, label: v.name, value: fmtCompact(v.tokens) }));
    // ★★전수가 아니다(top-50 + other) — "점유율" 대신 실측 필드를 그대로 노출한다.
    if (d)
      footnote = orTotal
        ? `${d.coverage} · other ${d.other_share_pct.toFixed(1)}% · 전체 합계 ${d.totals.daily.length}일`
        : `벤더별 ${d.vendor_series?.length ?? 0}개 · 전 구간 · ${d.coverage} · 활성 모델 ${d.active_models_30d}개`;
  } else if (tab === "npm") {
    const d = npmQ.data;
    asof = d?.asof ?? null;
    note = d?.note ?? null;
    if (d?.totals) {
      // ★★2026-08-31(2차) 사용자 지시 — **7일평균선 한 개만** 그린다.
      //   이상치(2026-04-30~05-11 `@openai/codex`)에 오염된 구간은 서버가 이미 선형보간해
      //   `daily_ma7_interp` 로 준다. 보정 계열을 따로 그어 두 줄로 만들지 않는다.
      const ma7: AiSeries = {
        key: "ma7",
        label: "7일 평균",
        kind: "line",
        last: lastValue(d.totals.daily_ma7_interp),
        points: d.totals.daily_ma7_interp,
      };
      raw = [
        {
          key: "raw",
          label: "일별",
          kind: "line",
          last: lastValue(d.totals.daily),
          points: d.totals.daily,
          // ★이상치로 판정된 날 — 차트가 rose 점으로 강조한다(값은 원값 그대로 둔다).
          anomaly_dates: d.totals_anomaly_dates,
        },
      ];
      // ★빨간 구간 — **같은 선 위에 색만 다르게** 덧그린다(별도의 두 번째 선이 아니다).
      //   보간된 날짜만 값을 두고 나머지는 null 이라 차트가 그 구간에서만 선을 그린다.
      //   ⚠️양 끝을 한 점씩 넓혀 성한 값과 물리게 한다 — 안 그러면 파란 선과 빨간 선
      //     사이에 한 칸짜리 흰 틈이 생긴다.
      const marked = new Set(d.ma7_interp_dates);
      const pts = d.totals.daily_ma7_interp;
      const edge = new Set<string>();
      pts.forEach(([dt], i) => {
        if (!marked.has(dt)) return;
        if (i > 0) edge.add(pts[i - 1][0]);
        if (i + 1 < pts.length) edge.add(pts[i + 1][0]);
      });
      const anomalySeg: AiSeries = {
        key: "anomaly",
        label: "이상치 보간 구간",
        kind: "line",
        last: null,
        points: pts.map(([dt, v]) => [dt, marked.has(dt) || edge.has(dt) ? v : null]),
      };
      plotted = showRaw ? [...raw, ma7, anomalySeg] : [ma7, anomalySeg];
    }
    badges = (d?.packages ?? [])
      .slice()
      .sort((a, b) => b.stats.last - a.stats.last)
      .slice(0, 4)
      .map((p) => ({ key: p.key, label: p.name, value: fmtCompact(p.stats.last) }));
    if (d) {
      const n = d.totals_anomaly_dates?.length ?? 0;
      const worst = (d.anomalies ?? [])
        .slice()
        .sort((a, b) => b.value - b.expected - (a.value - a.expected))[0];
      footnote =
        n > 0 && worst
          ? `${d.n_packages}개 패키지 합계 · ⚠ 이상치 ${n}일 — 최대 ${worst.date} ${worst.package} ${fmtCompact(worst.value)}(평시 ${fmtCompact(worst.expected)}, ${worst.ratio.toFixed(0)}배)`
          : `${d.n_packages}개 패키지 합계 · 상위 4개만 뱃지 표시`;
    }
  } else {
    // VS Code — 2026-08-28 라우트 개통·실제 계약으로 배선. `measure:"stock"`
    // (시점 누적) — 결측일은 과거 조회 API 가 없어 영구 손실(source.irrecoverable).
    // ★현재 스냅샷이 1일치뿐이라(n_snapshots:1) delta/delta_marks/revisions/gaps
    //   가 전부 비어 있다 — note 그대로 "내일 수집분부터 자동으로 생깁니다".
    //   아래 증분·정정 로직은 계약대로 미리 짜 둔 것이고 실 데이터로는 미검증.
    const d = vsQ.data;
    asof = d?.asof ?? null;
    note = d?.note ?? null;
    const exts = d?.extensions ?? [];
    plotted = [...exts]
      .sort((a, b) => b.install - a.install)
      .slice(0, 4)
      .map((e) => ({
        key: e.key,
        label: e.short,
        kind: e.kind,
        last: e.install,
        points: e.stock,
        // 음수 델타(MS 소급 정정)가 있던 날짜 — rose 로 강조해 숨기지 않는다.
        // ★marks 는 자기 날짜를 갖지 않는다. delta 와 인덱스 1:1 이라 날짜는 delta[i][0].
        anomaly_dates: e.delta_marks
          .map((m, i) => (m.negative ? e.delta[i]?.[0] : null))
          .filter((x): x is string => x != null),
      }));
    badges = plotted.map((s) => ({ key: s.key, label: s.label, value: fmtCompact(s.last ?? 0) }));

    // ★span_days — 데몬이 하루 이상 꺼졌다 켜지면 다음 delta 는 "하루 증분"이
    //   아니라 그 일수만큼의 누적분이다. 그대로 "전일대비"라고 적으면 틀린
    //   숫자가 되므로 span_days>1 이면 누적값과 일평균 환산을 같이 보여준다.
    const deltas = d?.totals.delta ?? [];
    const snaps = d?.snapshots ?? [];
    const li = deltas.length - 1;
    if (li >= 0) {
      const [dDate, dVal] = deltas[li];
      // ★`totals.delta` 에는 span 이 안 실린다. 콜렉터가 `zip(tdays, tdays[1:])` 로 만들어
      //   delta[i] 가 snapshots[i] -> snapshots[i+1] 차분이므로 간격을 여기서 되짚는다.
      const prev = snaps[li]?.date;
      const span =
        prev != null
          ? Math.max(1, Math.round((Date.parse(dDate) - Date.parse(prev)) / 86_400_000))
          : 1;
      const negative = dVal < 0;
      const sign = dVal > 0 ? "+" : "";
      if (span === 1) {
        increment = { text: `전일대비 ${sign}${fmtCompact(dVal)}`, negative };
      } else {
        const perDay = dVal / span;
        increment = {
          text: `${span}일 누적 ${sign}${fmtCompact(dVal)} (일평균 환산 ${
            perDay > 0 ? "+" : ""
          }${fmtCompact(perDay)})`,
          negative,
        };
      }
    }
    // 음수 정정 원값 — 0으로 자르거나 숨기지 않고 from→to 그대로 노출한다
    // (MS 쪽 소급 정정이라 그 자체가 관측 대상).
    revisionLines = (d?.revisions ?? [])
      .slice(-2)
      .map(
        (r) =>
          `${r.extension} ${r.date} ${r.from.toLocaleString("en-US")}→${r.to.toLocaleString("en-US")} (${
            r.delta > 0 ? "+" : ""
          }${r.delta.toLocaleString("en-US")})`,
      );
    // 영구 손실 구간 — irrecoverable 과 묶어 "이 구간은 이제 못 메운다"를 드러낸다.
    // gaps 는 결측 **날짜 문자열** 배열이다. 몇 건인지보다 어느 날인지가 중요해서 같이 적는다.
    if (d && d.gaps.length > 0) {
      const shown = d.gaps.slice(0, 3).join(", ");
      const more = d.gaps.length > 3 ? ` 외 ${d.gaps.length - 3}일` : "";
      gapsNote = `결측 ${d.gaps.length}일(${shown}${more}) — 복구 불가`;
    }
  }

  // ★모델별(openrouter 기본)은 계열이 10개라 팔레트를 순환시킨다. raw/보정 토글이 걸린
  //   경우에만 "주역=파랑, 보조=옅은 회색" 규칙을 적용한다.
  colors =
    tab === "openrouter" && !orTotal
      ? MODEL_PALETTE
      : tab !== "vscode"
        ? plotted.map((s) =>
            s.key === "ma7"
              ? PALETTE[0]
              : s.key === "anomaly"
                ? ANOM_COLOR
                : RAW_COLOR,
          )
        : PALETTE;

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

  return (
    <section
      className={cn(
        zoomCls,
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(rate-chart-card.tsx:285-286 선례).
        colSpan === 1 ? "lg:col-span-1" : colSpan === 3 ? "lg:col-span-3" : "lg:col-span-2",
      )}
    >
      {/* 제목 띠 강조색(ge-header) — 2026-08-28 사용자 지시로 페이지 카드가 전부 같은 색.
          칩도 어두운 배경용으로 뒤집혀 공용 TabChips 로 옮겼다. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">AI 사용량</h2>
        <TabChips tabs={TABS} value={tab} onChange={setTab} />
        {/* ★2026-08-31 사용자 지시로 아래 범례 줄을 확대 전까지 감췄다. 토글은 컨트롤이라
            같이 숨기면 전환이 막히므로 제목 띠로 올린다(축소 상태에서도 눌러야 한다). */}
        {tab !== "vscode" && raw.length > 0 ? (
          <button
            type="button"
            onClick={() =>
              tab === "openrouter" ? setOrTotal((v) => !v) : setShowRaw((v) => !v)
            }
            className="shrink-0 rounded bg-white/15 px-1.5 py-0.5 text-[12px] font-bold text-white/85 transition-colors hover:bg-white/30"
          >
            {tab === "openrouter"
              ? orTotal
                ? "벤더별 보기"
                : "전체 합계 보기"
              : showRaw
                ? "raw 숨기기"
                : "raw 보기"}
          </button>
        ) : null}
        <StaleBadge source={active.data?.source} />
        {asof ? (
          <span className="ml-auto shrink-0 text-[13px] tabular-nums text-white/60">
            {asof} 기준
          </span>
        ) : null}
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      {/* ★★확대했을 때만 보인다(2026-08-31 사용자 지시). 축소 상태에서는 계열이 15개까지
          늘어 3~4줄로 접히는데, 글자가 11px 라 읽히지도 않으면서 차트 높이만 먹는다.
          계열 식별은 확대해서 보고, 축소 상태에서는 차트 모양만 본다. */}
      {zoomed && (plotted.length > 0 || badges.length > 0) ? (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0 px-3 pt-1 text-[13px]">
          {plotted.map((s, i) => (
            <span key={s.key} className="flex items-baseline gap-1">
              <span
                className="inline-block h-2 w-2 shrink-0 translate-y-[-1px] rounded-sm"
                style={{ background: colors[i % colors.length] }}
              />
              <span className="text-ink-muted">{s.label}</span>
              <b className="font-bold tabular-nums text-ink">
                {s.last == null ? "—" : fmtCompact(s.last)}
              </b>
            </span>
          ))}
          {badges.length > 0 ? (
            <span className="flex flex-wrap items-baseline gap-x-1.5 text-[12px] text-ink-muted">
              {badges.map((b) => (
                <span key={b.key}>
                  {b.label} {b.value}
                </span>
              ))}
            </span>
          ) : null}
          {footnote ? <span className="text-[12px] text-ink-muted">{footnote}</span> : null}
        </div>
      ) : null}

      {/* VS Code 전용 — 증분(span_days 환산)·정정(revisions)·영구 결측(gaps).
          음수 델타·소급 정정을 색으로 숨기지 않고 그대로 드러낸다(팀 지시). */}
      {tab === "vscode" && (increment || revisionLines.length > 0 || gapsNote) ? (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 px-3 pb-0.5 text-[12px]">
          {increment ? (
            <span className={increment.negative ? "font-bold text-rose-600" : "text-ink-muted"}>
              {increment.negative ? "⚠ " : ""}
              {increment.text}
            </span>
          ) : null}
          {revisionLines.map((line, i) => (
            <span key={i} className="font-semibold text-rose-600">
              ⚠ 정정 {line}
            </span>
          ))}
          {gapsNote ? <span className="font-semibold text-amber-600">⚠ {gapsNote}</span> : null}
        </div>
      ) : null}

      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-0.5 pt-0.5">
        {isLoading ? (
          <Center msg="불러오는 중…" />
        ) : isError ? (
          <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
        ) : plotted.length === 0 ? (
          <Center
            msg={note ?? "판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
            tone={note ? "text-amber-600" : undefined}
          />
        ) : box.w > 0 && box.h > 0 ? (
          <TimeSeriesChart
            series={plotted}
            w={box.w}
            h={box.h}
            fmt={fmtCompact}
            colors={colors}
            /* 모델별은 10계열이라 헤더 가로 범례에 다 안 들어간다 — 차트 안에 그린다. */
            /* rect 범례도 같은 이유로 확대했을 때만(사용자 지시). 축소 상태에선
               반투명 판이 차트를 가리기만 한다. */
            legend={zoomed && tab === "openrouter" && !orTotal}
          />
        ) : null}
      </div>
    </section>
  );
}

// ★2026-08-28 팀 지시(코드 주석 수준으로만 남긴다 — 화면에 띄울 사안이 아니다).
// npm `cline` 패키지가 2025-10-13 에 이름을 재사용했다(impl-fetcher 실측).
// 재사용 직전(2025-09) 주간 다운로드는 2,463 — 현재(2026-08) 168,622 대비 약
// 1.5%. 이 카드의 다른 어떤 노이즈(요일 효과만 3.3배 스윙)보다도 작아
// "비교 불가"/"오염됨" 같은 라벨을 붙일 근거가 안 된다 — 경계 판정(2025-10-13
// 이전 트래픽 제외, 이건 유지)만으로 충분하다. 특정 패키지에만 유난히 경고를
// 걸면 나머지 지표가 실측인 것처럼 보이는 잘못된 인상을 준다 — 이 카드가 다루는
// 세 지표(OpenRouter 토큰·npm 다운로드·VS Code 설치)는 전부 대리지표(proxy)지
// 실사용자 수가 아니다(npm 은 CI 재빌드가 섞이고, 그건 cline 만의 문제가 아니다).

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <span className={cn("text-[13.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
