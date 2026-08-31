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
import { cn } from "@/lib/utils";

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

const POLL_MS = 1_800_000; // 30분 — 원천이 하루 1회 갱신이라 그 이상은 무의미

const PALETTE = ["#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7"];
const RAW_COLOR = "#c7cedb"; // raw 톱니는 옅게 — ma7 이 주역

type Tab = "openrouter" | "npm" | "vscode";
const TABS: { key: Tab; label: string }[] = [
  { key: "openrouter", label: "OpenRouter 토큰" },
  { key: "npm", label: "npm 다운로드" },
  { key: "vscode", label: "VS Code 설치" },
];

function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US");
}

export function AiUsageCard({ colSpan = 2 }: { colSpan?: number }) {
  const [tab, setTab] = useState<Tab>("openrouter");
  const [showRaw, setShowRaw] = useState(false);

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
    if (d?.totals) {
      const ma7: AiSeries = {
        key: "ma7",
        label: "7일 평균",
        kind: "line",
        last: lastValue(d.totals.daily_ma7),
        points: d.totals.daily_ma7,
      };
      raw = [
        {
          key: "raw",
          label: "일별",
          kind: "line",
          last: lastValue(d.totals.daily),
          points: d.totals.daily,
        },
      ];
      plotted = showRaw ? [...raw, ma7] : [ma7];
    }
    badges = (d?.vendors ?? [])
      .slice()
      .sort((a, b) => b.tokens - a.tokens)
      .slice(0, 4)
      .map((v) => ({ key: v.key, label: v.name, value: fmtCompact(v.tokens) }));
    // ★★전수가 아니다(top-50 + other) — "점유율" 대신 실측 필드를 그대로 노출한다.
    if (d) footnote = `${d.coverage} · other ${d.other_share_pct.toFixed(1)}%`;
  } else if (tab === "npm") {
    const d = npmQ.data;
    asof = d?.asof ?? null;
    note = d?.note ?? null;
    if (d?.totals) {
      const ma7: AiSeries = {
        key: "ma7",
        label: "7일 평균",
        kind: "line",
        last: lastValue(d.totals.daily_ma7),
        points: d.totals.daily_ma7,
      };
      raw = [
        {
          key: "raw",
          label: "일별",
          kind: "line",
          last: lastValue(d.totals.daily),
          points: d.totals.daily,
        },
      ];
      plotted = showRaw ? [...raw, ma7] : [ma7];
    }
    badges = (d?.packages ?? [])
      .slice()
      .sort((a, b) => b.stats.last - a.stats.last)
      .slice(0, 4)
      .map((p) => ({ key: p.key, label: p.name, value: fmtCompact(p.stats.last) }));
    if (d) footnote = `${d.n_packages}개 패키지 합계 · 상위 4개만 뱃지 표시`;
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
        anomaly_dates: e.delta_marks.filter((m) => m.negative).map((m) => m.date),
      }));
    badges = plotted.map((s) => ({ key: s.key, label: s.label, value: fmtCompact(s.last ?? 0) }));

    // ★span_days — 데몬이 하루 이상 꺼졌다 켜지면 다음 delta 는 "하루 증분"이
    //   아니라 그 일수만큼의 누적분이다. 그대로 "전일대비"라고 적으면 틀린
    //   숫자가 되므로 span_days>1 이면 누적값과 일평균 환산을 같이 보여준다.
    const deltas = d?.totals.delta ?? [];
    const lastDelta = deltas[deltas.length - 1];
    if (lastDelta) {
      const negative = lastDelta.value < 0;
      const sign = lastDelta.value > 0 ? "+" : "";
      if (lastDelta.span_days === 1) {
        increment = { text: `전일대비 ${sign}${fmtCompact(lastDelta.value)}`, negative };
      } else {
        const perDay = lastDelta.value / lastDelta.span_days;
        increment = {
          text: `${lastDelta.span_days}일 누적 ${sign}${fmtCompact(lastDelta.value)} (일평균 환산 ${
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
    if (d && d.gaps.length > 0) gapsNote = `과거 결측 ${d.gaps.length}건 — 복구 불가`;
  }

  colors =
    tab !== "vscode" && showRaw
      ? plotted.map((s) => (s.key === "ma7" ? PALETTE[0] : RAW_COLOR))
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
        "flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
        // 정적 클래스로 적어야 tailwind 가 스캔한다(rate-chart-card.tsx:285-286 선례).
        colSpan === 1 ? "lg:col-span-1" : colSpan === 3 ? "lg:col-span-3" : "lg:col-span-2",
      )}
    >
      {/* 제목 띠 강조색(ge-header) — 2026-08-28 사용자 지시로 페이지 카드가 전부 같은 색.
          칩도 어두운 배경용으로 뒤집혀 공용 TabChips 로 옮겼다. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[13px] font-extrabold text-white">AI 사용량</h2>
        <TabChips tabs={TABS} value={tab} onChange={setTab} />
        <StaleBadge source={active.data?.source} />
        {asof ? (
          <span className="ml-auto shrink-0 text-[11px] tabular-nums text-white/60">
            {asof} 기준
          </span>
        ) : null}
      </header>

      {plotted.length > 0 || badges.length > 0 ? (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0 px-3 pt-1 text-[11px]">
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
          {tab !== "vscode" && raw.length > 0 ? (
            <button
              type="button"
              onClick={() => setShowRaw((v) => !v)}
              className="text-[10.5px] font-semibold text-ge-point underline decoration-dotted"
            >
              {showRaw ? "raw 숨기기" : "raw 보기"}
            </button>
          ) : null}
          {badges.length > 0 ? (
            <span className="flex flex-wrap items-baseline gap-x-1.5 text-[10px] text-ink-muted">
              {badges.map((b) => (
                <span key={b.key}>
                  {b.label} {b.value}
                </span>
              ))}
            </span>
          ) : null}
          {footnote ? <span className="text-[10px] text-ink-muted">{footnote}</span> : null}
        </div>
      ) : null}

      {/* VS Code 전용 — 증분(span_days 환산)·정정(revisions)·영구 결측(gaps).
          음수 델타·소급 정정을 색으로 숨기지 않고 그대로 드러낸다(팀 지시). */}
      {tab === "vscode" && (increment || revisionLines.length > 0 || gapsNote) ? (
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 px-3 pb-0.5 text-[10.5px]">
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
          <TimeSeriesChart series={plotted} w={box.w} h={box.h} fmt={fmtCompact} colors={colors} />
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
      <span className={cn("text-[12px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
