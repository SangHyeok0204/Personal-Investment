"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { AiLineChart, type ChartSeries } from "@/components/ai-key-data/ai-line-chart";
import { MacroChart } from "@/components/charts/macro-chart";
import { EMDASH } from "@/components/format";
import {
  CardEmpty,
  Cell,
  DataTable,
  HeaderChip,
  SourceDownBanner,
  StubCard,
} from "@/components/stub";
import {
  aiQueryKeys,
  getAiSource,
  getAiStatus,
  type AiPoint,
  type AiSourceKey,
  type AiSourcePayload,
  type AiSourceStatus,
} from "@/lib/api-ai";
import { getMacroSeries, type MacroHistorySeries } from "@/lib/api";
import { cn } from "@/lib/utils";

// AI Key Data — 모니터링 전용(입력 없음). 계획 §3.4 · §11 "화면" · §12-3.
//
// ★2026-09-27 S5: 구 화면(Epoch ml_hardware 표 + npm SDK 6종 막대, `/market/ai-data`)을
//   걷어내고 7개 라이브/스냅샷 소스(`/market/ai/{source}`)로 다시 세웠다. 섹션 네 개:
//   ① 코딩 에이전트 채택(npm·VS Code·PyPI) ② LLM 사용량(OpenRouter·tool_calling)
//   ③ 기업 도입(Ramp) ④ 인프라(Epoch). 맨 위 상태 띠는 `/market/ai/status` 한 번.
//
// ★색은 **엔티티가 정한다**(차트마다 고정 순서) — 순위로 칠하지 않는다. 브랜드 가이드 §8
//   (브라운/블루 계열) 안에서 채도만 올린 4색 + 다크 그레이, 나머지는 옅은 회색으로
//   접는다. 4색은 검증기(dataviz validate_palette)로 CVD·명도·채도를 통과한 값이다.
//   두 밝은 색(#D19552·#5FA0DB)은 흰 배경 대비가 3:1 미만이라 범례에 값을 글자로 같이 적는다.

const SLOTS = ["#8A4A24", "#2F6CA3", "#D19552", "#5FA0DB", "#595959"];
const MUTED = "#CFCFCF";
const TOTAL = "#1F1F1F";

/** order[i] 가 SLOTS[i] 를 받는다. order 밖은 옅은 회색. */
function paint(order: string[]): (key: string) => string {
  return (key) => {
    const i = order.indexOf(key);
    return i >= 0 && i < SLOTS.length ? SLOTS[i] : MUTED;
  };
}

const NPM_CLI_COLOR = paint([
  "@anthropic-ai/claude-code",
  "@openai/codex",
  "opencode-ai",
  "@anthropic-ai/claude-agent-sdk",
  "@github/copilot",
]);
const NPM_SDK_COLOR = paint(["@anthropic-ai/sdk", "openai", "@google/genai", "ai", "langchain"]);
const RAMP_COLOR = paint(["Anthropic", "OpenAI", "Google", "xAI"]);
const CHIP_COLOR = paint(["chip:Nvidia", "chip:Google", "chip:AMD", "chip:Amazon"]);
const ARR_COLOR = paint(["arr:Anthropic", "arr:OpenAI", "arr:Z.ai (Zhipu)", "arr:DeepSeek", "arr:xAI"]);

const SOURCE_NAME: Record<AiSourceKey, string> = {
  npm: "npm",
  vscode: "VS Code",
  pypi: "PyPI",
  openrouter: "OpenRouter",
  tool_calling: "Tool calling",
  ramp: "Ramp",
  epoch: "Epoch AI",
};

const SOURCE_URL: Record<AiSourceKey, string> = {
  npm: "https://www.npmjs.com",
  vscode: "https://marketplace.visualstudio.com",
  pypi: "https://pypistats.org",
  openrouter: "https://openrouter.ai/rankings",
  tool_calling: "https://openrouter.ai/rankings",
  ramp: "https://ramp.com/data/ai-index",
  epoch: "https://epoch.ai/data",
};

// ── 표기 ─────────────────────────────────────────────────────────────────────

function compact(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  const a = Math.abs(v);
  const f = (n: number, s: string) =>
    `${(v / n).toLocaleString("en-US", { maximumFractionDigits: digits })}${s}`;
  if (a >= 1e12) return f(1e12, "T");
  if (a >= 1e9) return f(1e9, "B");
  if (a >= 1e6) return f(1e6, "M");
  if (a >= 1e3) return f(1e3, "K");
  return Math.round(v).toLocaleString("en-US");
}

const usdCompact = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? EMDASH : `$${compact(v)}`;

function signedPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function signedPp(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}p`;
}

function shortTime(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ── 계산(화면 몫 — 수집기는 원값만 준다, §11) ─────────────────────────────────

/** 7일 이동평균 — 달력 7일 창에 점이 7개 다 있을 때만 낸다(결측을 0 으로 채우지 않는다). */
function movingAverage7(points: AiPoint[]): AiPoint[] {
  const out: AiPoint[] = [];
  const day = (d: string) => Date.parse(`${d}T00:00:00Z`) / 86_400_000;
  let sum = 0;
  let lo = 0;
  for (let i = 0; i < points.length; i++) {
    sum += points[i][1];
    const di = day(points[i][0]);
    while (day(points[lo][0]) <= di - 7) {
      sum -= points[lo][1];
      lo += 1;
    }
    if (i - lo + 1 === 7) out.push([points[i][0], sum / 7]);
  }
  return out;
}

function last(points: AiPoint[], back = 0): number | null {
  const p = points[points.length - 1 - back];
  return p ? p[1] : null;
}

function pctChange(now: number | null, prev: number | null): number | null {
  if (now == null || prev == null || prev === 0) return null;
  return ((now - prev) / prev) * 100;
}

/** 끝에서부터 이어진 "집계 미완" 분기의 첫 날짜 — 그 뒤를 점선으로. */
function trailingIncomplete(dates: string[], incomplete: string[]): string | null {
  const set = new Set(incomplete);
  let from: string | null = null;
  for (let i = dates.length - 1; i >= 0 && set.has(dates[i]); i--) from = dates[i];
  return from;
}

// ── 조회 ─────────────────────────────────────────────────────────────────────

// 서버가 라이브 소스를 6h 캐시한다(§12-3). 화면이 그보다 자주 물을 이유가 없다 —
// 30분 staleTime + 창 포커스 재조회 없음. 상태 띠만 조금 더 자주(5분).
const SOURCE_STALE = 30 * 60_000;

function useAiSource(source: AiSourceKey) {
  return useQuery({
    queryKey: aiQueryKeys.source(source),
    queryFn: () => getAiSource(source),
    staleTime: SOURCE_STALE,
    refetchOnWindowFocus: false,
  });
}

// ─────────────────────────────────────────────────────────────────────────────

export function AiKeyDataTab() {
  const status = useQuery({
    queryKey: aiQueryKeys.status,
    queryFn: getAiStatus,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const npm = useAiSource("npm");
  const vscode = useAiSource("vscode");
  const pypi = useAiSource("pypi");
  const openrouter = useAiSource("openrouter");
  const toolCalling = useAiSource("tool_calling");
  const ramp = useAiSource("ramp");
  const epoch = useAiSource("epoch");

  // ⚠️상태 조회는 소스 조회와 **동시에** 나간다. 서버 캐시가 비어 있던 첫 요청에서는
  //   라이브 소스가 아직 안 채워져 `unknown`(fetched=false)으로 온다. 같은 소스의
  //   본문 응답이 이미 와 있으면 그쪽 status·latest_date 가 더 새것이므로 덮어쓴다.
  const payloads: Partial<Record<AiSourceKey, AiSourcePayload | undefined>> = {
    npm: npm.data,
    vscode: vscode.data,
    pypi: pypi.data,
    openrouter: openrouter.data,
    tool_calling: toolCalling.data,
    ramp: ramp.data,
    epoch: epoch.data,
  };
  const pending: Partial<Record<AiSourceKey, boolean>> = {
    npm: npm.isPending,
    vscode: vscode.isPending,
    pypi: pypi.isPending,
    openrouter: openrouter.isPending,
    tool_calling: toolCalling.isPending,
    ramp: ramp.isPending,
    epoch: epoch.isPending,
  };
  const merged = (status.data?.items ?? []).map((s): AiSourceStatus => {
    const p = payloads[s.source];
    // 콜드 서버: 본문 조회가 아직 도는 중이면 "미확인"이 아니라 "조회 중"(첫 조회는 수십 초 걸린다).
    if (!p) return s.status === "unknown" && pending[s.source] ? { ...s, status: "fetching" } : s;
    return {
      ...s,
      status: p.status,
      ok: p.status === "ok",
      fetched: true,
      latest_date: p.latest_date ?? s.latest_date,
      last_ok: p.last_ok ?? s.last_ok,
      note: p.note ?? s.note,
      as_of: p.as_of ?? s.as_of,
      key_missing: s.key_missing || p.status === "key_missing",
    };
  });
  const byKey = new Map<AiSourceKey, AiSourceStatus>(merged.map((s) => [s.source, s]));
  const st = (k: AiSourceKey) => byKey.get(k);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto pb-2 pr-1">
      <div className="flex flex-col gap-4">
        {status.isError && (
          <SourceDownBanner source="AI Key Data API" detail="상태 조회(/market/ai/status)에 실패했습니다." />
        )}

        <StatusStrip items={status.data ? merged : null} loading={status.isLoading} />

        {/* ① ─────────────────────────────────────────────────────────── */}
        <Section
          no="①"
          title="AI 코딩 에이전트 채택"
          desc="패키지 다운로드·확장 설치"
          sources={[
            { key: "npm", status: st("npm") },
            { key: "vscode", status: st("vscode") },
            { key: "pypi", status: st("pypi") },
          ]}
        >
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
            <NpmCard
              title="npm · 코딩 에이전트 CLI"
              payload={npm.data}
              loading={npm.isLoading}
              group="cli"
              color={NPM_CLI_COLOR}
              height={318}
              legendSide
              defaultLog
            />
            <NpmCard
              title="npm · LLM SDK"
              payload={npm.data}
              loading={npm.isLoading}
              group="sdk"
              color={NPM_SDK_COLOR}
              height={150}
            />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <VsCodeCard payload={vscode.data} loading={vscode.isLoading} />
            <PypiCard payload={pypi.data} loading={pypi.isLoading} />
          </div>
        </Section>

        {/* ② ─────────────────────────────────────────────────────────── */}
        <Section
          no="②"
          title="LLM 사용량"
          desc="OpenRouter 경유 토큰 — 모델별 점유와 tool calling 비중"
          sources={[
            { key: "openrouter", status: st("openrouter") },
            { key: "tool_calling", status: st("tool_calling") },
          ]}
        >
          <LlmUsage
            openrouter={openrouter.data}
            toolCalling={toolCalling.data}
            loading={openrouter.isLoading || toolCalling.isLoading}
            keyMissing={
              st("openrouter")?.key_missing === true ||
              openrouter.data?.status === "key_missing"
            }
          />
        </Section>

        {/* ③ ─────────────────────────────────────────────────────────── */}
        <Section
          no="③"
          title="기업 AI 도입"
          desc="Ramp 법인카드·청구서 기준 — 유료로 쓰는 미국 기업의 비율(월간)"
          sources={[{ key: "ramp", status: st("ramp") }]}
        >
          <RampCard payload={ramp.data} loading={ramp.isLoading} />
        </Section>

        {/* ④ ─────────────────────────────────────────────────────────── */}
        <Section
          no="④"
          title="AI 인프라"
          desc="칩 누적 출하 · 랩 매출 · 데이터센터 · 투자 라운드"
          sources={[{ key: "epoch", status: st("epoch") }]}
        >
          <EpochBlock payload={epoch.data} loading={epoch.isLoading} />
        </Section>

        {/* ⑤ ─────────────────────────────────────────────────────────── */}
        <RateMacroSection />
      </div>
    </div>
  );
}

// ── 상태 띠 ──────────────────────────────────────────────────────────────────

const STATE_META: Record<string, { label: string; dot: string; text: string }> = {
  ok: { label: "정상", dot: "bg-emerald-500", text: "text-ink-secondary" },
  stale: { label: "지연", dot: "bg-amber-500", text: "text-amber-800" },
  key_missing: { label: "키 없음", dot: "bg-rose-500", text: "text-rose-700" },
  error: { label: "오류", dot: "bg-rose-500", text: "text-rose-700" },
  empty: { label: "비어 있음", dot: "bg-amber-500", text: "text-amber-800" },
  fetching: { label: "조회 중", dot: "bg-[#A6A6A6] animate-pulse", text: "text-ink-muted" },
};
const UNKNOWN_META = { label: "미확인", dot: "bg-[#A6A6A6]", text: "text-ink-muted" };
const meta = (s: string | undefined) => (s && STATE_META[s]) || UNKNOWN_META;

function StatusStrip({
  items,
  loading,
}: {
  items: AiSourceStatus[] | null;
  loading: boolean;
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-1.5 rounded-xl border border-hairline bg-canvas px-2.5 py-2 shadow-card">
      <span className="mr-1 text-[11px] font-extrabold tracking-wide text-ink-muted">
        소스 상태
      </span>
      {loading && <span className="text-[11px] text-ink-faint">불러오는 중…</span>}
      {(items ?? []).map((s) => {
        const m = meta(s.status);
        const updated = shortTime(s.last_ok);
        return (
          <span
            key={s.source}
            title={[s.note, updated && `마지막 정상 수집 ${updated}`, s.as_of && `as_of ${s.as_of}`]
              .filter(Boolean)
              .join(" · ")}
            className="inline-flex items-center gap-1.5 rounded-full bg-canvas-soft px-2.5 py-1 text-[11px]"
          >
            <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", m.dot)} aria-hidden />
            <b className="font-bold text-ink">{SOURCE_NAME[s.source] ?? s.source}</b>
            <span className={cn("font-semibold", m.text)}>{m.label}</span>
            {s.latest_date && (
              <span className="tabular-nums text-ink-muted">{s.latest_date}</span>
            )}
            {s.as_of && (
              <span className="tabular-nums text-ink-faint">as of {s.as_of.slice(0, 10)}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ── 섹션 머리 ────────────────────────────────────────────────────────────────

function Section({
  no,
  title,
  desc,
  sources,
  children,
}: {
  no: string;
  title: string;
  desc: string;
  sources: { key: AiSourceKey; status: AiSourceStatus | undefined }[];
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <header className="flex flex-wrap items-end gap-x-3 gap-y-1 border-b border-ink/80 pb-1.5">
        <h2 className="text-[15px] font-extrabold tracking-tight text-ge-navy">
          <span className="mr-1.5 text-ge-point">{no}</span>
          {title}
        </h2>
        <span className="pb-px text-[11.5px] font-medium text-ink-muted">{desc}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {sources.map(({ key, status }) => (
            <Freshness key={key} source={key} status={status} />
          ))}
        </div>
      </header>
      {children}
    </section>
  );
}

function Freshness({ source, status }: { source: AiSourceKey; status: AiSourceStatus | undefined }) {
  const m = meta(status?.status);
  const ok = status?.status === "ok";
  return (
    <a
      href={SOURCE_URL[source]}
      target="_blank"
      rel="noreferrer"
      className="group inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[11px] transition-colors hover:bg-canvas"
      title={status?.note ?? undefined}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", m.dot)} aria-hidden />
      <b className="font-bold text-ink-secondary group-hover:text-ink">{SOURCE_NAME[source]}</b>
      <span className={cn("tabular-nums", ok ? "text-ink-muted" : m.text)}>
        {ok ? (status?.latest_date ?? "—") : m.label}
      </span>
      <ExternalLink className="h-3 w-3 text-ink-faint group-hover:text-ge-point" aria-hidden />
      <span className="sr-only">(새 창)</span>
    </a>
  );
}

// ── 범례(값 포함, 클릭하면 숨김) ─────────────────────────────────────────────

interface LegendItem {
  key: string;
  label: string;
  color: string;
  value: string;
  change?: string | null;
  /** 변화의 부호 — 한국 관례(상승 빨강/하락 파랑). */
  sign?: number | null;
  sub?: string | null;
}

function Legend({
  items,
  hidden,
  onToggle,
  columns = 1,
}: {
  items: LegendItem[];
  hidden: Set<string>;
  onToggle: (key: string) => void;
  columns?: 1 | 2;
}) {
  return (
    <ul className={cn("grid gap-x-3", columns === 2 ? "grid-cols-2" : "grid-cols-1")}>
      {items.map((it) => {
        const off = hidden.has(it.key);
        return (
          <li key={it.key}>
            <button
              type="button"
              onClick={() => onToggle(it.key)}
              aria-pressed={!off}
              title={off ? "눌러서 다시 보기" : "눌러서 숨기기"}
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-1 py-[3px] text-left text-[11.5px] transition-colors hover:bg-canvas-soft",
                off && "opacity-35",
              )}
            >
              <span
                className="h-[3px] w-3 shrink-0 rounded-full"
                style={{ background: it.color }}
                aria-hidden
              />
              <span className="min-w-0 truncate font-semibold text-ink-secondary">{it.label}</span>
              {it.sub && <span className="shrink-0 text-[10px] text-ink-faint">{it.sub}</span>}
              <span className="ml-auto shrink-0 pl-2 font-bold tabular-nums text-ink">{it.value}</span>
              {it.change !== undefined && (
                <span
                  className={cn(
                    "w-[46px] shrink-0 text-right text-[10.5px] font-bold tabular-nums",
                    it.sign == null || it.sign === 0
                      ? "text-ink-faint"
                      : it.sign > 0
                        ? "text-bid"
                        : "text-ask",
                  )}
                >
                  {it.change ?? EMDASH}
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function useHidden() {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const toggle = (k: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  return { hidden, toggle };
}

/** 회색(배경) 계열을 먼저 그려 색 계열이 위에 오게. */
function paintOrder(a: ChartSeries, b: ChartSeries): number {
  return Number(a.color !== MUTED) - Number(b.color !== MUTED);
}

function Attribution({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 text-[10.5px] leading-snug text-ink-faint">{children}</p>;
}

function Placeholder({ loading, payload, height }: { loading: boolean; payload?: AiSourcePayload; height: number }) {
  return (
    <div style={{ height }}>
      <CardEmpty
        text={
          loading
            ? "불러오는 중…"
            : payload?.note ?? (payload ? `데이터 없음 (${payload.status})` : "응답을 받지 못했습니다")
        }
      />
    </div>
  );
}

// ── ① npm ────────────────────────────────────────────────────────────────────

function NpmCard({
  title,
  payload,
  loading,
  group,
  color,
  height,
  legendSide = false,
  defaultLog = false,
}: {
  title: string;
  payload: AiSourcePayload | undefined;
  loading: boolean;
  group: "cli" | "sdk";
  color: (key: string) => string;
  height: number;
  legendSide?: boolean;
  /** 처음 로그 축으로 볼지. CLI 는 1K~3M 이 한 판이고 하루짜리 스파이크(수천만)가 있어
   *  선형이면 13개 중 3개만 보인다 — 기본 로그. */
  defaultLog?: boolean;
}) {
  const [ma, setMa] = useState(true);
  const [log, setLog] = useState(defaultLog);
  const { hidden, toggle } = useHidden();

  const rows = useMemo(() => {
    const src = (payload?.series ?? []).filter((s) => s.group === group);
    return src.map((s) => {
      const avg = movingAverage7(s.points);
      const now = last(avg);
      return {
        s,
        avg,
        now,
        wow: pctChange(now, last(avg, 7)),
      };
    });
  }, [payload, group]);

  const chart: ChartSeries[] = rows
    .filter((r) => !hidden.has(r.s.key))
    .map((r) => {
      const c = color(r.s.key);
      return {
        key: r.s.key,
        label: r.s.label,
        color: c,
        points: ma ? r.avg : r.s.points,
        width: c === MUTED ? 1.1 : ma ? 1.9 : 1.25,
      };
    })
    .sort(paintOrder);

  const legend: LegendItem[] = [...rows]
    .sort((a, b) => (b.now ?? -1) - (a.now ?? -1))
    .map((r) => ({
      key: r.s.key,
      label: r.s.label,
      color: color(r.s.key),
      value: compact(r.now),
      change: signedPct(r.wow),
      sign: r.wow,
    }));

  const latest = payload?.latest_date;

  return (
    <StubCard
      title={title}
      subtitle={`일간 다운로드${ma ? " · 7일 이평" : ""}${log ? " · 로그 축" : ""}${latest ? ` · ~${latest}` : ""}`}
      action={
        <div className="flex items-center gap-0.5">
          <HeaderChip active={ma} onClick={() => setMa(true)}>
            7DMA
          </HeaderChip>
          <HeaderChip active={!ma} onClick={() => setMa(false)}>
            일간
          </HeaderChip>
          <span className="mx-1 h-3 w-px bg-white/25" aria-hidden />
          <HeaderChip active={!log} onClick={() => setLog(false)}>
            선형
          </HeaderChip>
          <HeaderChip active={log} onClick={() => setLog(true)}>
            로그
          </HeaderChip>
        </div>
      }
    >
      {rows.length === 0 ? (
        <Placeholder loading={loading} payload={payload} height={height} />
      ) : (
        <div className={cn(legendSide ? "grid gap-3 md:grid-cols-[minmax(0,1fr)_236px]" : "flex flex-col gap-2")}>
          <div>
            <AiLineChart
              series={chart}
              height={height}
              log={log}
              fmt={(v) => compact(v)}
              axisFmt={(v) => compact(v, 0)}
              ariaLabel={`${title} 일간 다운로드${ma ? " 7일 이동평균" : ""}`}
            />
          </div>
          <div>
            <div className="mb-0.5 flex items-center px-1 text-[10px] font-bold text-ink-faint">
              <span>최근 7DMA 순</span>
              <span className="ml-auto">7DMA</span>
              <span className="w-[46px] text-right">WoW</span>
            </div>
            <Legend
              items={legend}
              hidden={hidden}
              onToggle={toggle}
              columns={legendSide ? 1 : 2}
            />
          </div>
        </div>
      )}
      <Attribution>
        {payload?.attribution ?? "npm registry"} · 이평·증감은 화면에서 계산 · CI·미러 포함이라 추세로 읽는다
      </Attribution>
    </StubCard>
  );
}

// ── ① VS Code ────────────────────────────────────────────────────────────────

function VsCodeCard({ payload, loading }: { payload: AiSourcePayload | undefined; loading: boolean }) {
  const rows = useMemo(() => {
    const series = payload?.series ?? [];
    const delta = new Map(
      series.filter((s) => s.group === "delta").map((s) => [s.key.replace(/:delta$/, ""), s]),
    );
    return series
      .filter((s) => s.group === "install")
      .map((s) => {
        const d = delta.get(s.key);
        return {
          s,
          total: last(s.points),
          date: s.points[s.points.length - 1]?.[0] ?? null,
          delta: d ? last(d.points) : null,
          deltaSeries: d,
        };
      })
      .sort((a, b) => (b.total ?? -1) - (a.total ?? -1));
  }, [payload]);

  const depth = Math.max(0, ...rows.map((r) => r.s.points.length));
  const chartable = depth >= 7;
  const color = paint(rows.slice(0, SLOTS.length).map((r) => r.s.key));
  const { hidden, toggle } = useHidden();

  return (
    <StubCard
      title="VS Code 확장 설치"
      subtitle={`누적 설치 · 일증분${depth > 0 ? ` · 스냅샷 ${depth}일` : ""}`}
    >
      {rows.length === 0 ? (
        <Placeholder loading={loading} payload={payload} height={180} />
      ) : chartable ? (
        <div className="flex flex-col gap-2">
          <AiLineChart
            series={rows
              .filter((r) => !hidden.has(r.s.key))
              .map((r) => ({ key: r.s.key, label: r.s.label, color: color(r.s.key), points: r.s.points }))
              .sort(paintOrder)}
            height={170}
            fmt={(v) => compact(v, 2)}
            axisFmt={(v) => compact(v, 0)}
            ariaLabel="VS Code 확장 누적 설치"
          />
          <Legend
            columns={2}
            hidden={hidden}
            onToggle={toggle}
            items={rows.map((r) => ({
              key: r.s.key,
              label: r.s.label,
              color: color(r.s.key),
              value: compact(r.total, 2),
              change: r.delta == null ? null : `+${compact(r.delta)}`,
              sign: r.delta,
            }))}
          />
        </div>
      ) : (
        <>
          <DataTable columns={["확장", "누적 설치", "일증분", "기준일"]}>
            {rows.map((r) => (
              <tr key={r.s.key} className="border-b border-hairline">
                <Cell left strong>
                  {r.s.label}
                </Cell>
                <Cell strong>{r.total == null ? EMDASH : Math.round(r.total).toLocaleString("en-US")}</Cell>
                <Cell tone={r.delta == null ? "muted" : undefined}>
                  {r.delta == null ? "대기" : `${r.delta >= 0 ? "+" : ""}${Math.round(r.delta).toLocaleString("en-US")}`}
                </Cell>
                <Cell tone="muted">{r.date ?? EMDASH}</Cell>
              </tr>
            ))}
          </DataTable>
          <p className="mt-1.5 text-[10.5px] text-ink-faint">
            스냅샷 {depth}일치 · 7일부터 추이 차트 · 일증분은 이틀째부터
          </p>
        </>
      )}
      <Attribution>
        {payload?.attribution ?? "Visual Studio Marketplace"} · 하루 1회 스냅샷(놓친 날은 복구 불가) · 음수 증분은 MS 소급 정정 원값
      </Attribution>
    </StubCard>
  );
}

// ── ① PyPI ───────────────────────────────────────────────────────────────────

function PypiCard({ payload, loading }: { payload: AiSourcePayload | undefined; loading: boolean }) {
  const rows = useMemo(() => {
    const series = payload?.series ?? [];
    const month = new Map(
      series.filter((s) => s.group === "last_month").map((s) => [s.key.replace(/:month$/, ""), s]),
    );
    return series
      .filter((s) => s.group === "last_day")
      .map((s) => ({
        s,
        day: last(s.points),
        month: month.has(s.key) ? last(month.get(s.key)!.points) : null,
        date: s.points[s.points.length - 1]?.[0] ?? null,
      }))
      .sort((a, b) => (b.month ?? -1) - (a.month ?? -1));
  }, [payload]);

  const depth = Math.max(0, ...rows.map((r) => r.s.points.length));
  const chartable = depth >= 7;
  const color = paint(rows.slice(0, SLOTS.length).map((r) => r.s.key));

  return (
    <StubCard title="PyPI SDK 다운로드" subtitle={`전일 · 최근 30일${depth > 0 ? ` · 스냅샷 ${depth}일` : ""}`}>
      {rows.length === 0 ? (
        <Placeholder loading={loading} payload={payload} height={180} />
      ) : (
        <>
          {chartable && (
            <div className="mb-2">
              <AiLineChart
                series={rows
                  .map((r) => ({ key: r.s.key, label: r.s.label, color: color(r.s.key), points: r.s.points }))
                  .sort(paintOrder)}
                height={140}
                fmt={(v) => compact(v, 2)}
                axisFmt={(v) => compact(v, 0)}
                ariaLabel="PyPI 전일 다운로드 추이"
              />
            </div>
          )}
          <DataTable columns={["패키지", "전일", "최근 30일", "기준일"]}>
            {rows.map((r) => (
              <tr key={r.s.key} className="border-b border-hairline">
                <Cell left strong>
                  <span className="inline-flex items-center gap-1.5">
                    {chartable && (
                      <span className="h-[3px] w-3 rounded-full" style={{ background: color(r.s.key) }} />
                    )}
                    {r.s.label}
                  </span>
                </Cell>
                <Cell>{compact(r.day, 2)}</Cell>
                <Cell strong>{compact(r.month, 1)}</Cell>
                <Cell tone="muted">{r.date ?? EMDASH}</Cell>
              </tr>
            ))}
          </DataTable>
          {!chartable && (
            <p className="mt-1.5 text-[10.5px] text-ink-faint">
              스냅샷 {depth}일치 · 7일부터 추이 차트
            </p>
          )}
        </>
      )}
      <Attribution>{payload?.attribution ?? "pypistats.org"} · 미러 제외 집계</Attribution>
    </StubCard>
  );
}

// ── ② OpenRouter · tool calling ─────────────────────────────────────────────

function LlmUsage({
  openrouter,
  toolCalling,
  loading,
  keyMissing,
}: {
  openrouter: AiSourcePayload | undefined;
  toolCalling: AiSourcePayload | undefined;
  loading: boolean;
  keyMissing: boolean;
}) {
  const [ma, setMa] = useState(true);
  const { hidden, toggle } = useHidden();

  const models = useMemo(() => {
    const src = (openrouter?.series ?? []).filter((s) => s.group === "model");
    return src.map((s, i) => {
      const avg = movingAverage7(s.points);
      return { s, avg, now: last(avg), color: i < SLOTS.length ? SLOTS[i] : MUTED };
    });
  }, [openrouter]);

  const share = useMemo(() => {
    const series = toolCalling?.series ?? [];
    const total = series.find((s) => s.key === "total");
    const tool = series.find((s) => s.key === "tool");
    if (!total || !tool) return [] as AiPoint[];
    const t = new Map(tool.points);
    const raw: AiPoint[] = total.points
      .filter((p) => p[1] > 0)
      .map((p) => [p[0], ((t.get(p[0]) ?? 0) / p[1]) * 100]);
    return raw;
  }, [toolCalling]);

  if (keyMissing) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-dashed border-[#D9D9D9] bg-canvas px-4 py-3">
        <span className="rounded-md bg-rose-50 px-2 py-1 text-[11px] font-extrabold text-rose-700">
          키 없음
        </span>
        <p className="text-[12.5px] font-semibold text-ink-secondary">
          <code className="rounded bg-canvas-soft px-1 py-0.5 text-[12px] font-bold text-ink">
            OPENROUTER_API_KEY
          </code>{" "}
          미설정 — <code className="text-[12px]">.env.local</code>에 추가 후 API 재시작
        </p>
        <span className="ml-auto hidden text-[11px] text-ink-faint md:inline">
          모델별 토큰 · tool calling 비중이 여기 표시됩니다
        </span>
      </div>
    );
  }

  const asOf = openrouter?.as_of ?? toolCalling?.as_of ?? openrouter?.latest_date ?? "";
  const attribution = (openrouter?.attribution ?? "Source: OpenRouter (openrouter.ai/rankings)").replace(
    "{as_of}",
    asOf || "—",
  );
  const shareShown = ma ? movingAverage7(share) : share;
  const shareNow = last(movingAverage7(share));

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
      <StubCard
        title="모델별 일간 토큰"
        subtitle={`OpenRouter 상위 ${models.length}개${ma ? " · 7일 이평" : ""}`}
        action={
          <div className="flex gap-0.5">
            <HeaderChip active={ma} onClick={() => setMa(true)}>
              7DMA
            </HeaderChip>
            <HeaderChip active={!ma} onClick={() => setMa(false)}>
              일간
            </HeaderChip>
          </div>
        }
      >
        {models.length === 0 ? (
          <Placeholder loading={loading} payload={openrouter} height={240} />
        ) : (
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_236px]">
            <AiLineChart
              series={models
                .filter((m) => !hidden.has(m.s.key))
                .map((m) => ({
                  key: m.s.key,
                  label: m.s.label,
                  color: m.color,
                  points: ma ? m.avg : m.s.points,
                  width: m.color === MUTED ? 1.1 : 1.75,
                }))
                .sort(paintOrder)}
              height={240}
              fmt={(v) => compact(v)}
              axisFmt={(v) => compact(v, 0)}
              ariaLabel="OpenRouter 모델별 일간 토큰"
            />
            <Legend
              hidden={hidden}
              onToggle={toggle}
              items={[...models]
                .sort((a, b) => (b.now ?? -1) - (a.now ?? -1))
                .map((m) => ({ key: m.s.key, label: m.s.label, color: m.color, value: compact(m.now) }))}
            />
          </div>
        )}
        <Attribution>{attribution}</Attribution>
      </StubCard>
      <StubCard title="tool calling 비중" subtitle={`tool 토큰 ÷ 전체 토큰${ma ? " · 7일 이평" : ""}`}>
        {shareShown.length === 0 ? (
          <Placeholder loading={loading} payload={toolCalling} height={200} />
        ) : (
          <>
            <div className="mb-1 flex items-baseline gap-2">
              <span className="text-[22px] font-extrabold tabular-nums text-ge-navy">
                {shareNow == null ? EMDASH : `${shareNow.toFixed(1)}%`}
              </span>
              <span className="text-[11px] text-ink-muted">최근 7DMA</span>
            </div>
            <AiLineChart
              series={[{ key: "share", label: "tool calling 비중", color: SLOTS[1], points: shareShown, area: true }]}
              height={180}
              fmt={(v) => `${v.toFixed(1)}%`}
              axisFmt={(v) => `${v.toFixed(0)}%`}
              padLeft={36}
              ariaLabel="tool calling 토큰 비중"
            />
          </>
        )}
        <Attribution>전체 쪽 날짜 기준 · tool 값 없는 날은 0</Attribution>
      </StubCard>
    </div>
  );
}

// ── ③ Ramp ───────────────────────────────────────────────────────────────────

function RampCard({ payload, loading }: { payload: AiSourcePayload | undefined; loading: boolean }) {
  const { hidden, toggle } = useHidden();
  const rows = useMemo(
    () =>
      (payload?.series ?? []).map((s) => {
        const now = last(s.points);
        const prev = last(s.points, 1);
        return {
          s,
          now,
          mom: now != null && prev != null ? now - prev : null,
          color: s.key === "all" ? TOTAL : RAMP_COLOR(s.key),
        };
      }),
    [payload],
  );

  const latest = payload?.latest_date?.slice(0, 7);

  return (
    <StubCard
      title="Ramp AI Index"
      subtitle={`유료 AI 도입 기업 비율 · 월간${latest ? ` · ~${latest}` : ""}`}
    >
      {rows.length === 0 ? (
        <Placeholder loading={loading} payload={payload} height={250} />
      ) : (
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_236px]">
          <AiLineChart
            series={rows
              .filter((r) => !hidden.has(r.s.key))
              .map((r) => ({
                key: r.s.key,
                label: r.s.label,
                color: r.color,
                points: r.s.points,
                width: r.s.key === "all" ? 2.4 : r.color === MUTED ? 1.1 : 1.75,
              }))
              .sort(paintOrder)}
            height={250}
            fmt={(v) => `${v.toFixed(1)}%`}
            axisFmt={(v) => `${v.toFixed(0)}%`}
            padLeft={38}
            ariaLabel="Ramp AI 도입률 월간 — 전체와 벤더별"
          />
          <div>
            <div className="mb-0.5 flex items-center px-1 text-[10px] font-bold text-ink-faint">
              <span>{latest ?? "최근"} 기준</span>
              <span className="ml-auto">도입률</span>
              <span className="w-[46px] text-right">MoM</span>
            </div>
            <Legend
              hidden={hidden}
              onToggle={toggle}
              items={[...rows]
                .sort((a, b) =>
                  a.s.key === "all" ? -1 : b.s.key === "all" ? 1 : (b.now ?? -1) - (a.now ?? -1),
                )
                .map((r) => ({
                  key: r.s.key,
                  label: r.s.label,
                  color: r.color,
                  value: r.now == null ? EMDASH : `${r.now.toFixed(1)}%`,
                  change: signedPp(r.mom),
                  sign: r.mom,
                }))}
            />
            <p className="mt-2 px-1 text-[10.5px] leading-snug text-ink-faint">
              벤더 비율 중복 포함(2곳 이상 결제 기업) · 합계 100% 아님
            </p>
          </div>
        </div>
      )}
      <Attribution>
        Source: {payload?.attribution ?? "Ramp AI Index (ramp.com/data/ai-index)"}
      </Attribution>
    </StubCard>
  );
}

// ── ④ Epoch ──────────────────────────────────────────────────────────────────

const EPOCH_ATTR = "Source: Epoch AI (epoch.ai), CC-BY";

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function EpochBlock({ payload, loading }: { payload: AiSourcePayload | undefined; loading: boolean }) {
  const chips = useHidden();
  const arrs = useHidden();

  const incomplete = useMemo(() => {
    const raw = payload?.extra?.["incomplete_quarters"];
    return Array.isArray(raw) ? raw.filter((d): d is string => typeof d === "string") : [];
  }, [payload]);

  const chipRows = useMemo(() => {
    const src = (payload?.series ?? []).filter((s) => s.group === "chip_h100e");
    return src.map((s) => ({
      s,
      now: last(s.points),
      qoq: s.points.slice(-2).some(([date]) => incomplete.includes(date))
        ? null
        : pctChange(last(s.points), last(s.points, 1)),
      color: s.key === "chip_total" ? TOTAL : CHIP_COLOR(s.key),
      dashFrom: trailingIncomplete(
        s.points.map((p) => p[0]),
        incomplete,
      ),
    }));
  }, [payload, incomplete]);

  const arrRows = useMemo(() => {
    const src = (payload?.series ?? []).filter((s) => s.group === "lab_arr");
    return src
      .map((s) => ({ s, now: last(s.points), date: s.points[s.points.length - 1]?.[0] ?? null }))
      .sort((a, b) => (b.now ?? -1) - (a.now ?? -1))
      .slice(0, 8);
  }, [payload]);

  const dataCenters = payload?.tables.find((t) => t.key === "data_centers");
  const funding = useMemo(() => {
    const t = payload?.tables.find((x) => x.key === "funding_rounds");
    return [...(t?.rows ?? [])].sort((a, b) => String(b.date ?? "").localeCompare(String(a.date ?? "")));
  }, [payload]);

  const empty = !payload || payload.series.length === 0;
  const chipDash = chipRows.find((r) => r.s.key === "chip_total")?.dashFrom;

  return (
    <>
      <div className="grid gap-3 lg:grid-cols-2">
        <StubCard title="AI 칩 누적 출하" subtitle="H100 환산(H100e) · 분기">
          {empty ? (
            <Placeholder loading={loading} payload={payload} height={220} />
          ) : (
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_196px]">
              <AiLineChart
                series={chipRows
                  .filter((r) => !chips.hidden.has(r.s.key))
                  .map((r) => ({
                    key: r.s.key,
                    label: r.s.label,
                    color: r.color,
                    points: r.s.points,
                    area: r.s.key === "chip_total",
                    width: r.s.key === "chip_total" ? 2.2 : r.color === MUTED ? 1.1 : 1.6,
                    dashFrom: r.dashFrom,
                  }))
                  .sort(paintOrder)}
                height={220}
                fmt={(v) => compact(v, 2)}
                axisFmt={(v) => compact(v, 0)}
                ariaLabel="AI 칩 누적 출하 H100e — 전체와 제조사별"
              />
              <div>
                <div className="mb-0.5 flex items-center px-1 text-[10px] font-bold text-ink-faint">
                  <span>누적</span>
                  <span className="ml-auto">H100e</span>
                  <span className="w-[46px] text-right">QoQ</span>
                </div>
                <Legend
                  hidden={chips.hidden}
                  onToggle={chips.toggle}
                  items={[...chipRows]
                    .sort((a, b) => (b.now ?? -1) - (a.now ?? -1))
                    .map((r) => ({
                      key: r.s.key,
                      label: r.s.key === "chip_total" ? "전체" : r.s.label,
                      color: r.color,
                      value: compact(r.now),
                      change: r.s.points.slice(-2).some(([date]) => incomplete.includes(date))
                        ? "집계 중"
                        : signedPct(r.qoq),
                      sign: r.qoq,
                    }))}
                />
              </div>
            </div>
          )}
          <Attribution>
            {chipDash ? `점선 = 집계가 덜 끝난 분기(${chipDash.slice(0, 7)}~) · ` : ""}
            {EPOCH_ATTR}
          </Attribution>
        </StubCard>

        <StubCard title="AI 랩 연환산 매출(ARR)" subtitle="상위 8 · 공시 시점 계단 · 로그 축">
          {arrRows.length === 0 ? (
            <Placeholder loading={loading} payload={payload} height={220} />
          ) : (
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_196px]">
              <AiLineChart
                series={arrRows
                  .filter((r) => !arrs.hidden.has(r.s.key))
                  .map((r) => {
                    const c = ARR_COLOR(r.s.key);
                    return {
                      key: r.s.key,
                      label: r.s.label,
                      color: c,
                      points: r.s.points,
                      step: true,
                      width: c === MUTED ? 1.2 : 1.75,
                    };
                  })
                  .sort(paintOrder)}
                height={220}
                log
                fmt={usdCompact}
                axisFmt={(v) => usdCompact(v).replace(/\.0(?=[KMBT])/, "")}
                padLeft={44}
                ariaLabel="AI 랩 연환산 매출 계단 그래프, 로그 축"
              />
              <div>
                <div className="mb-0.5 flex items-center px-1 text-[10px] font-bold text-ink-faint">
                  <span>최근 공시</span>
                  <span className="ml-auto">ARR</span>
                </div>
                <Legend
                  hidden={arrs.hidden}
                  onToggle={arrs.toggle}
                  items={arrRows.map((r) => ({
                    key: r.s.key,
                    label: r.s.label,
                    color: ARR_COLOR(r.s.key),
                    value: usdCompact(r.now),
                    sub: r.date ? r.date.slice(2, 7).replace("-", ".") : null,
                  }))}
                />
              </div>
            </div>
          )}
          <Attribution>계단 = 다음 공시까지 직전 값 유지(보도·공시 기반 추정) · {EPOCH_ATTR}</Attribution>
        </StubCard>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <StubCard
          title="데이터센터 전력 상위 20"
          subtitle="MW · H100e · 누적 capex"
          className="max-h-[420px]"
          scrollBody
        >
          {!dataCenters ? (
            <Placeholder loading={loading} payload={payload} height={200} />
          ) : (
            <DataTable
              columns={["#", "데이터센터", "소유", "국가", "전력 MW", "H100e", "Capex"]}
              align={["right", "left", "left", "left", "right", "right", "right"]}
            >
              {dataCenters.rows.map((r, i) => (
                <tr
                  key={`${String(r.name)}-${i}`}
                  className="border-b border-hairline"
                  title={r.users ? `사용: ${String(r.users)}` : undefined}
                >
                  <Cell tone="muted">{i + 1}</Cell>
                  <Cell left strong>
                    <span className="block max-w-[180px] truncate">{String(r.name ?? EMDASH)}</span>
                  </Cell>
                  <Cell left>
                    <span className="block max-w-[120px] truncate">{String(r.owner ?? EMDASH)}</span>
                  </Cell>
                  <Cell left tone="muted">
                    {String(r.country ?? EMDASH).replace("United States", "US")}
                  </Cell>
                  <Cell strong>{num(r.power_mw) == null ? EMDASH : Math.round(num(r.power_mw)!).toLocaleString("en-US")}</Cell>
                  <Cell>{compact(num(r.h100e), 2)}</Cell>
                  <Cell>{num(r.capex_busd) == null ? EMDASH : `$${num(r.capex_busd)!.toFixed(1)}B`}</Cell>
                </tr>
              ))}
            </DataTable>
          )}
          <Attribution>{EPOCH_ATTR}</Attribution>
        </StubCard>

        <StubCard
          title="AI 랩 투자 라운드"
          subtitle={`최근 순 · ${funding.length}건`}
          className="max-h-[420px]"
          scrollBody
        >
          {funding.length === 0 ? (
            <Placeholder loading={loading} payload={payload} height={200} />
          ) : (
            <DataTable
              columns={["날짜", "기업", "유형", "지분", "기업가치"]}
              align={["left", "left", "left", "right", "right"]}
            >
              {funding.map((r, i) => (
                <tr
                  key={`${String(r.company)}-${String(r.date)}-${i}`}
                  className="border-b border-hairline"
                  title={
                    [r.status && `상태: ${String(r.status)}`, num(r.debt_usd) != null && `부채 ${usdCompact(num(r.debt_usd))}`]
                      .filter(Boolean)
                      .join(" · ") || undefined
                  }
                >
                  <Cell left tone="muted">
                    {String(r.date ?? EMDASH)}
                  </Cell>
                  <Cell left strong>
                    {String(r.company ?? EMDASH)}
                  </Cell>
                  <Cell left tone="muted">
                    {String(r.type ?? EMDASH)}
                  </Cell>
                  <Cell>{usdCompact(num(r.equity_usd))}</Cell>
                  <Cell strong>{usdCompact(num(r.valuation_usd))}</Cell>
                </tr>
              ))}
            </DataTable>
          )}
          <Attribution>{EPOCH_ATTR}</Attribution>
        </StubCard>
      </div>
    </>
  );
}


// ── ⑤ 금리·매크로 연계 ──────────────────────────────────────────────────────
// ★구 collector 금리 카드(정책금리·기대인플레·WTI·ADP)를 FRED 행으로 옮겼다(계획 2.1·2.2).
//   새 API 없이 /macro 와 같은 `/market/macro/series` 를 같은 queryKey 로 읽는다.

const RATE_IDS = ["DFEDTARU", "EXPINF1YR", "DCOILWTICO", "ADPMNUSNERSA"];

function fmtRate(s: MacroHistorySeries, v: number): string {
  if (s.transform === "mom_diff") return `${v > 0 ? "+" : ""}${Math.round(v).toLocaleString("en-US")}${s.unit}`;
  if (s.unit === "$") return `$${v.toFixed(2)}`;
  return `${v.toFixed(2)}${s.unit}`;
}

function RateMacroSection() {
  const q = useQuery({
    queryKey: ["macro-series", "5y"],
    queryFn: () => getMacroSeries("5y"),
    staleTime: 10 * 60_000,
  });
  const series = RATE_IDS.map((id) => q.data?.series.find((s) => s.series_id === id)).filter(
    (s): s is MacroHistorySeries => s != null,
  );
  return (
    <section className="flex flex-col gap-2.5">
      <header className="flex flex-wrap items-end gap-x-3 gap-y-1 border-b border-ink/80 pb-1.5">
        <h2 className="text-[15px] font-extrabold tracking-tight text-ge-navy">
          <span className="mr-1.5 text-ge-point">⑤</span>금리·매크로 연계
        </h2>
        <span className="pb-px text-[11.5px] font-medium text-ink-muted">
          FRED 월말 값 · 5년 · 전체 지표는 매크로 화면
        </span>
      </header>
      {q.isError && <SourceDownBanner source="FRED 매크로" detail="/market/macro/series 조회에 실패했습니다." />}
      {q.isLoading && <CardEmpty text="불러오는 중" />}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {series.map((s) => {
          const lastPt = s.points[s.points.length - 1];
          return (
            <StubCard key={s.series_id} title={s.name}>
              <div className="flex items-baseline justify-between px-1 text-[12px]">
                <b className="tabular-nums text-ink">{lastPt ? fmtRate(s, lastPt[1]) : EMDASH}</b>
                <span className="text-ink-muted">{lastPt ? `${lastPt[0]} · ${s.note ?? ""}` : s.note}</span>
              </div>
              <MacroChart
                points={s.points}
                start={q.data!.start}
                end={q.data!.end}
                bands={q.data!.recessions}
                height={110}
                zeroLine={s.transform === "mom_diff"}
                axisFormat={(v) => fmtRate(s, v)}
                tooltipFormat={(v) => fmtRate(s, v)}
              />
            </StubCard>
          );
        })}
      </div>
    </section>
  );
}
