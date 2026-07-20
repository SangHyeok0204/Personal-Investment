"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  Flame,
  LayoutGrid,
  Table2,
  X,
} from "lucide-react";
import {
  ApiError,
  getInavComponents,
  getInavHoga,
  getInavSnapshot,
  type HogaEtf,
  type InavComponentRow,
  type InavComponentsPayload,
  type InavEtf,
  type InavSnapshot,
  type InavSums,
} from "@/lib/api";
import { formatKrw, formatRate, formatRelativeTime } from "@/lib/format";
import { RollingText } from "@/components/rolling-text";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// Age thresholds (초): 각 소스 refresh 주기의 3~4배를 넘으면 경고.
const FX_WARN_S = 180;
const PRICE_WARN_S = 180;
const KR_ETF_WARN_S = 60;
const TWSE_WARN_S = 900;
const COMPUTE_WARN_S = 10;

// KRW 기준(=1.0)은 제외하고 표시할 통화 순서.
const FX_ORDER = ["USD", "CNY", "HKD", "JPY", "EUR", "CAD", "TWD"];

// 무버 전광판: 구성종목 전일比 등락 절대값 기준(%).
const MOVERS_THRESHOLD_PCT = 5;

// iNAV 총액 → 좌당 환산 제수 (구 대시보드와 동일).
const INAV_DIVISOR = 50000;

// 호가카드: 수신/소스 나이 임계(초) — 초과 시 "호가 지연/끊김" 배지 (Step B staleness).
const HOGA_STALE_S = 10;
// 구 뷰어와 동일 인덱스 매핑: asks[0]=매도5 … asks[4]=매도1, bids[0]=매수1 … bids[4]=매수5.
const ASK_LABELS = ["매도5", "매도4", "매도3", "매도2", "매도1"] as const;
const BID_LABELS = ["매수1", "매수2", "매수3", "매수4", "매수5"] as const;

const EMDASH = "−";

// 카드 미니 지표 — 표시 순서 = 이 배열 순서 (2026-07-20 사용자 지정, iNAV 는 고정 3번째).
const CARD_METRICS = [
  { key: "deviation", label: "실제괴리", live: true },
  { key: "intraday", label: "장중괴리", live: true },
  { key: "aum", label: "AUM(억)", live: true },
  { key: "expense", label: "보수율", live: true },
  { key: "trade", label: "거래대금(억)", live: true },
  { key: "components", label: "구성종목", live: true },
  { key: "weight", label: "반영비중", live: true },
  { key: "lp", label: "LP대금(억)", live: false },
] as const;
type MetricKey = (typeof CARD_METRICS)[number]["key"];
const DEFAULT_METRICS: MetricKey[] = [
  "deviation",
  "aum",
  "trade",
  "components",
  "weight",
];

// 카드 그리드 고정 우선순서 (2026-07-20 사용자 지정) — 나머지는 스냅샷 순서 유지.
const CARD_TICKER_ORDER = [
  "414270", // ACE 글로벌자율주행액티브
  "457480", // ACE 테슬라밸류체인액티브
  "483320", // ACE 엔비디아밸류체인액티브
  "483330", // ACE 마이크로소프트밸류체인액티브
  "483340", // ACE 구글밸류체인액티브
  "0079X0", // ACE BYD밸류체인액티브
  "0118Z0", // ACE 미국AI테크핵심산업액티브
  "0199C0", // ACE 고배당주Plus커버드콜액티브
];

type ViewMode = "cards" | "table";

/* ── 포맷 헬퍼 ───────────────────────────────────────────────────────── */

function formatAge(age: number | null | undefined): string {
  if (age == null || Number.isNaN(age)) return "—";
  if (age < 90) return `${Math.round(age)}s`;
  return `${Math.round(age / 60)}m`;
}

function formatBasisDate(raw: string | null | undefined): string {
  if (!raw) return "—";
  if (/^\d{8}$/.test(raw)) {
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }
  return raw;
}

function fmtNum(value: number | null | undefined, min = 0, max = 2): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
}

// 원 → 억 (2자리).
function fmtEok(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EMDASH;
  return fmtNum(value / 1e8, 2, 2);
}

function signedPct(pct: number, digits = 2): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

/* ── 페이지 ──────────────────────────────────────────────────────────── */

export default function InavPage() {
  const query = useQuery({
    queryKey: ["inavSnapshot"],
    queryFn: getInavSnapshot,
    refetchInterval: 1000,
  });
  const componentsQuery = useQuery({
    queryKey: ["inavComponents"],
    queryFn: getInavComponents,
    refetchInterval: 2000,
    retry: false,
  });
  const hogaQuery = useQuery({
    queryKey: ["inavHoga"],
    queryFn: getInavHoga,
    refetchInterval: 1000,
    retry: false,
  });

  const [view, setView] = useState<ViewMode>("cards");
  const [metrics, setMetrics] = useState<MetricKey[]>(DEFAULT_METRICS);
  const [modalTicker, setModalTicker] = useState<string | null>(null);

  // localStorage는 hydration 후에만 읽는다 (SSR 불일치 방지).
  useEffect(() => {
    const storedView = window.localStorage.getItem("inav-view-mode");
    if (storedView === "cards" || storedView === "table") setView(storedView);
    const storedMetrics = window.localStorage.getItem("inav-card-metrics");
    if (storedMetrics) {
      try {
        const parsed = JSON.parse(storedMetrics) as MetricKey[];
        if (Array.isArray(parsed)) setMetrics(parsed);
      } catch {
        /* 무시 — 기본값 유지 */
      }
    }
  }, []);

  const changeView = useCallback((next: ViewMode) => {
    setView(next);
    window.localStorage.setItem("inav-view-mode", next);
  }, []);

  const toggleMetric = useCallback((key: MetricKey) => {
    setMetrics((prev) => {
      const next = prev.includes(key)
        ? prev.filter((k) => k !== key)
        : [...prev, key];
      window.localStorage.setItem("inav-card-metrics", JSON.stringify(next));
      return next;
    });
  }, []);

  const data = query.data;
  const componentsData = componentsQuery.data ?? null;
  const collectorDown =
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 503;

  const movers = useMemo(() => buildMovers(componentsData), [componentsData]);

  // 카드 뷰: ACE 지정 8종 우선, 나머지는 스냅샷 순서 유지 (stable sort).
  const orderedEtfs = useMemo(() => {
    const etfs = query.data?.etfs ?? [];
    const rank = new Map(CARD_TICKER_ORDER.map((t, i) => [t, i]));
    return [...etfs].sort(
      (a, b) =>
        (rank.get(a.ticker) ?? CARD_TICKER_ORDER.length) -
        (rank.get(b.ticker) ?? CARD_TICKER_ORDER.length),
    );
  }, [query.data]);

  const hoga = hogaQuery.data ?? null;
  const hogaByCode = useMemo(() => {
    const map = new Map<string, HogaEtf>();
    for (const e of hoga?.payload?.etfs ?? []) map.set(e.code, e);
    return map;
  }, [hoga]);
  // 수신 age 또는 source_timestamp(Excel/VBA 피드) age 초과 — 단일 "지연/끊김" 배지.
  const hogaStale =
    hoga != null &&
    ((hoga.hoga_last_received_age_s ?? Infinity) > HOGA_STALE_S ||
      (hoga.hoga_source_age_s ?? Infinity) > HOGA_STALE_S);

  return (
    <>
      <Topbar
        title="iNAV 모니터"
        subtitle="시장 모니터링 · ETF 실시간 iNAV / 괴리율"
        status={
          data ? (
            <span className="truncate text-[11px] text-slate-400">
              {formatRelativeTime(data.generated_at)} 갱신
            </span>
          ) : undefined
        }
        actions={
          <>
            <SumPills sums={data?.sums ?? null} />
            <SysStatus data={data} collectorDown={collectorDown} />
            <ViewSwitch view={view} onChange={changeView} />
            <MetricSelect visible={metrics} onToggle={toggleMetric} />
          </>
        }
      />

      {/* 급등락 전광판 — Topbar(h-16) 바로 아래, 우→좌 무한 마퀴 */}
      {movers.length > 0 && <MoversTicker items={movers} />}

      <PageContainer wide>
        {/* API 자체가 죽은 경우(네트워크 오류)만 상단 에러 배너. collector 미기동은 아래 전용 배너로. */}
        {query.isError && !collectorDown && (
          <div className="mb-4">
            <ApiErrorBanner error={query.error} />
          </div>
        )}

        {collectorDown && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-amber-400/40 bg-amber-400/[0.08] px-5 py-4 text-amber-700">
            <AlertTriangle className="h-5 w-5 shrink-0" strokeWidth={2} />
            <div>
              <div className="text-sm font-bold">collector 미기동</div>
              <div className="mt-0.5 text-[13px] text-amber-700/80">
                수집 서비스가 실행 중이 아닙니다. 재기동 시 자동으로 다시
                표시됩니다.
              </div>
            </div>
          </div>
        )}

        {query.isLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-10 w-64 rounded-xl" />
            <Skeleton className="h-[520px] w-full rounded-2xl" />
          </div>
        ) : data ? (
          <div className="space-y-4">
            {view === "cards" ? (
              <EtfCardGrid
                etfs={orderedEtfs}
                visibleMetrics={metrics}
                onOpen={setModalTicker}
                hogaByCode={hogaByCode}
                hogaStale={hogaStale}
              />
            ) : (
              <EtfTable etfs={data.etfs} onOpen={setModalTicker} />
            )}

            <FxPanel fx={data.fx} />
          </div>
        ) : (
          !collectorDown && (
            <p className="text-sm text-ink-muted">
              스냅샷 데이터를 표시할 수 없습니다.
            </p>
          )
        )}

        {modalTicker && (
          <ComponentModal
            ticker={modalTicker}
            payload={componentsData}
            etf={data?.etfs.find((e) => e.ticker === modalTicker) ?? null}
            onClose={() => setModalTicker(null)}
          />
        )}
      </PageContainer>
    </>
  );
}

/* ── Topbar 통합: 합계 pill (ACE 프리픽스만 합산) ────────────────────── */

function SumPills({ sums }: { sums: InavSums | null }) {
  const items = [
    { label: "총 NAV", value: sums?.aum_krw },
    { label: "총 거래대금", value: sums?.trade_value_krw },
    { label: "연 보수 합계", value: sums?.annual_fee_krw },
  ];
  return (
    <div
      className="hidden items-center gap-2 min-[1440px]:flex"
      title="ACE 계열 합산 · AUM=상장좌수×iNAV 근사"
    >
      {items.map((it) => (
        <span
          key={it.label}
          className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas-soft px-2.5 py-1"
        >
          <span className="text-[10px] font-semibold text-ink-muted">
            {it.label}
          </span>
          <span className="text-[12px] font-extrabold tabular-nums text-ge-navy">
            {fmtEok(it.value)}
            <span className="ml-0.5 font-semibold text-ink-muted">억</span>
          </span>
        </span>
      ))}
    </div>
  );
}

/* ── Topbar 통합: 시스템 상태 (hover 상세) ───────────────────────────── */

type StatusLevel = "ok" | "warn" | "bad";

function SysStatus({
  data,
  collectorDown,
}: {
  data: InavSnapshot | undefined;
  collectorDown: boolean;
}) {
  const s = data?.staleness;
  let level: StatusLevel;
  let label: string;
  if (collectorDown || !data) {
    level = "bad";
    label = collectorDown ? "수집기 꺼짐" : "확인 중...";
  } else if (
    !s?.token_valid ||
    (s?.compute_age_s ?? Infinity) > COMPUTE_WARN_S
  ) {
    level = "bad";
    label = "오류발생";
  } else if (
    (s?.fx_age_s ?? 0) > FX_WARN_S ||
    (s?.price_age_s ?? 0) > PRICE_WARN_S ||
    (s?.kr_etf_age_s ?? 0) > KR_ETF_WARN_S ||
    (s?.twse_age_s ?? 0) > TWSE_WARN_S
  ) {
    level = "warn";
    label = "주의";
  } else {
    level = "ok";
    label = "정상작동중";
  }

  const dot =
    level === "ok"
      ? "bg-status-success"
      : level === "warn"
        ? "bg-amber-500"
        : "bg-status-failed";

  const rows: { name: string; value: string; state: StatusLevel }[] = [
    {
      name: "연결",
      value: collectorDown ? "수집기 꺼짐" : data ? "연결됨" : "확인 중",
      state: collectorDown || !data ? "bad" : "ok",
    },
    {
      name: "시장상태",
      value: data?.market_status ?? "—",
      state: "ok",
    },
    {
      name: "바스켓",
      value: s
        ? `${s.basket_source || "—"} · ${formatBasisDate(s.basket_basis_date)}`
        : "—",
      state: "ok",
    },
    {
      name: "FX",
      value: formatAge(s?.fx_age_s),
      state: (s?.fx_age_s ?? 0) > FX_WARN_S ? "warn" : "ok",
    },
    {
      name: "구성종목가",
      value: formatAge(s?.price_age_s),
      state: (s?.price_age_s ?? 0) > PRICE_WARN_S ? "warn" : "ok",
    },
    {
      name: "국내가",
      value: formatAge(s?.kr_etf_age_s),
      state: (s?.kr_etf_age_s ?? 0) > KR_ETF_WARN_S ? "warn" : "ok",
    },
    {
      name: "TWSE",
      value: formatAge(s?.twse_age_s),
      state: (s?.twse_age_s ?? 0) > TWSE_WARN_S ? "warn" : "ok",
    },
    {
      name: "토큰",
      value: s?.token_valid ? "유효" : "만료",
      state: s?.token_valid ? "ok" : "bad",
    },
  ];

  return (
    <div className="group relative">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas-soft px-2.5 py-1 text-[12px] font-semibold text-ink-secondary"
      >
        <span className={cn("h-2 w-2 rounded-full", dot)} />
        {label}
      </button>
      <div className="invisible absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-hairline bg-canvas p-2 opacity-0 shadow-panel transition group-hover:visible group-hover:opacity-100">
        {rows.map((row) => (
          <div
            key={row.name}
            className="flex items-center justify-between gap-3 rounded-lg px-2 py-1 text-[12px]"
          >
            <span className="text-ink-muted">{row.name}</span>
            <span
              className={cn(
                "font-semibold tabular-nums",
                row.state === "bad"
                  ? "text-status-failed"
                  : row.state === "warn"
                    ? "text-amber-600"
                    : "text-ink",
              )}
            >
              {row.value}
            </span>
          </div>
        ))}
        <div className="mt-1 border-t border-hairline px-2 pt-1.5 text-[10px] leading-relaxed text-ink-faint">
          휴장달력 상세·PDF 교차검증은 CHECK 에이전트 연동(P3) 후 표시됩니다.
        </div>
      </div>
    </div>
  );
}

/* ── Topbar 통합: 표시 지표 토글 ─────────────────────────────────────── */

function MetricSelect({
  visible,
  onToggle,
}: {
  visible: MetricKey[];
  onToggle: (key: MetricKey) => void;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-full border border-hairline bg-canvas-soft px-2.5 py-1 text-[12px] font-semibold text-ink-secondary hover:text-ge-point"
      >
        표시 지표
        <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-52 rounded-xl border border-hairline bg-canvas p-2 shadow-panel">
          {CARD_METRICS.map((m) => (
            <label
              key={m.key}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] text-ink hover:bg-canvas-soft"
            >
              <input
                type="checkbox"
                checked={visible.includes(m.key)}
                onChange={() => onToggle(m.key)}
                className="accent-ge-point"
              />
              <span>{m.label}</span>
              {!m.live && (
                <span className="ml-auto text-[10px] text-ink-faint">
                  연동 전
                </span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 급등락 전광판 (우→좌 마퀴) ──────────────────────────────────────── */

interface MoverItem {
  key: string;
  name: string;
  pct: number;
  etfs: string[];
}

function buildMovers(payload: InavComponentsPayload | null): MoverItem[] {
  if (!payload?.byEtf) return [];
  const grouped = new Map<string, MoverItem>();
  for (const [etfCode, entry] of Object.entries(payload.byEtf)) {
    for (const c of entry.components ?? []) {
      if (c.isCash || c.livePrice == null || c.basePrice == null) continue;
      if (c.livePrice <= 0 || c.basePrice <= 0) continue;
      const pct = (c.livePrice / c.basePrice - 1) * 100;
      if (Math.abs(pct) < MOVERS_THRESHOLD_PCT) continue;
      const key = (c.isin || c.name || "").toUpperCase();
      if (!key) continue;
      const item = grouped.get(key) ?? {
        key,
        name: c.name || c.isin || "?",
        pct,
        etfs: [],
      };
      item.pct = pct;
      if (!item.etfs.includes(etfCode)) item.etfs.push(etfCode);
      grouped.set(key, item);
    }
  }
  return [...grouped.values()].sort(
    (a, b) => Math.abs(b.pct) - Math.abs(a.pct),
  );
}

function MoversTicker({ items }: { items: MoverItem[] }) {
  // 아이템 수에 비례해 속도 유지 (한 바퀴 시간).
  const duration = Math.max(24, items.length * 6);
  return (
    <div className="sticky top-16 z-10 h-10 overflow-hidden border-b border-hairline bg-white">
      <div
        className="inav-ticker-track flex h-10 items-center"
        style={{ animationDuration: `${duration}s` }}
      >
        <TickerRun items={items} />
        <TickerRun items={items} />
      </div>
    </div>
  );
}

function TickerRun({ items }: { items: MoverItem[] }) {
  return (
    <div className="flex h-10 min-w-[100vw] shrink-0 items-center gap-7 px-6">
      <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-ink-muted">
        <Flame className="h-3.5 w-3.5 text-status-failed" strokeWidth={2.2} />
        급등락 ±{MOVERS_THRESHOLD_PCT}%
      </span>
      {items.map((it) => (
        <TickerChip key={it.key} item={it} />
      ))}
    </div>
  );
}

function TickerChip({ item }: { item: MoverItem }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5"
      title={`편입 ETF: ${item.etfs.join(", ")}`}
    >
      <span className="text-[12.5px] font-bold text-ge-navy">{item.name}</span>
      <span
        className={cn(
          "px-0.5 text-[12.5px] font-extrabold tabular-nums",
          item.pct >= 0 ? "text-status-failed" : "text-status-running",
        )}
      >
        <RollingText text={signedPct(item.pct)} />
      </span>
      <span className="text-[10px] text-ink-faint">
        {item.etfs.length > 1
          ? `${item.etfs[0]} 외 ${item.etfs.length - 1}`
          : item.etfs[0]}
      </span>
    </span>
  );
}

/* ── 뷰 스위치(Topbar) · 열수 토글 ───────────────────────────────────── */

// 카드 ⟷ 표 토글 스위치: 동그라미 단추가 좌(카드)/우(표)로 이동.
function ViewSwitch({
  view,
  onChange,
}: {
  view: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  const isTable = view === "table";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isTable}
      title="카드/표 전환"
      onClick={() => onChange(isTable ? "cards" : "table")}
      className="inline-flex select-none items-center gap-1.5"
    >
      <LayoutGrid
        className={cn("h-4 w-4", !isTable ? "text-ge-point" : "text-slate-300")}
        strokeWidth={2}
      />
      <span
        className={cn(
          "text-[12px] font-semibold",
          !isTable ? "text-ge-point" : "text-ink-muted",
        )}
      >
        카드
      </span>
      <span
        className={cn(
          "relative h-5 w-9 rounded-full border transition-colors",
          isTable
            ? "border-ge-point/40 bg-ge-blue-bg"
            : "border-hairline bg-canvas-soft",
        )}
      >
        <span
          className={cn(
            "absolute left-0.5 top-0.5 h-4 w-4 rounded-full border border-hairline bg-white shadow transition-transform",
            isTable ? "translate-x-4" : "translate-x-0",
          )}
        />
      </span>
      <span
        className={cn(
          "text-[12px] font-semibold",
          isTable ? "text-ge-point" : "text-ink-muted",
        )}
      >
        표
      </span>
      <Table2
        className={cn("h-4 w-4", isTable ? "text-ge-point" : "text-slate-300")}
        strokeWidth={2}
      />
    </button>
  );
}

/* ── 카드 그리드 (5열 고정) ──────────────────────────────────────────── */

function EtfCardGrid({
  etfs,
  visibleMetrics,
  onOpen,
  hogaByCode,
  hogaStale,
}: {
  etfs: InavEtf[];
  visibleMetrics: MetricKey[];
  onOpen: (ticker: string) => void;
  hogaByCode: Map<string, HogaEtf>;
  hogaStale: boolean;
}) {
  if (!etfs.length) {
    return <p className="text-sm text-ink-muted">표시할 ETF가 없습니다.</p>;
  }
  return (
    <div className="grid grid-cols-5 gap-3">
      {etfs.map((etf) => (
        <div key={etf.ticker} className="flex flex-col gap-2">
          <EtfCard
            etf={etf}
            visibleMetrics={visibleMetrics}
            onOpen={() => onOpen(etf.ticker)}
          />
          <OrderbookCard
            hoga={hogaByCode.get(etf.ticker) ?? null}
            stale={hogaStale}
          />
        </div>
      ))}
    </div>
  );
}

function EtfCard({
  etf,
  visibleMetrics,
  onOpen,
}: {
  etf: InavEtf;
  visibleMetrics: MetricKey[];
  onOpen: () => void;
}) {
  const dev = etf.deviation_pct;
  const devAbs = dev == null ? null : Math.abs(dev);
  const danger = devAbs != null && devAbs >= 2;
  const warn = devAbs != null && devAbs >= 1 && devAbs < 2;

  return (
    <button
      type="button"
      onClick={onOpen}
      title="클릭하면 구성종목 상세를 엽니다"
      className={cn(
        "flex flex-col gap-2.5 rounded-2xl border-2 bg-canvas p-3.5 text-left shadow-card transition hover:-translate-y-px hover:shadow-panel",
        danger
          ? "border-status-failed/50"
          : warn
            ? "border-amber-400/60"
            : "border-hairline",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-extrabold text-ge-navy">
            {etf.name || "—"}
          </div>
          <div className="text-[11px] font-semibold tabular-nums text-ink-muted">
            {etf.ticker}
          </div>
        </div>
        {(danger || warn) && (
          <span
            title={`실제괴리 ${dev == null ? "—" : signedPct(dev)}`}
            className={cn(
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
              danger
                ? "bg-status-failed/[0.10] text-status-failed"
                : "bg-amber-400/[0.15] text-amber-600",
            )}
          >
            <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2.2} />
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[21px] font-extrabold leading-none tabular-nums text-ge-navy">
          <RollingText
            text={etf.kr_etf_price == null ? EMDASH : formatKrw(etf.kr_etf_price)}
          />
        </span>
        <ChangeChip pct={etf.change_pct} />
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-hairline pt-2.5">
        {visibleMetrics.includes("deviation") && (
          <MiniMetric label="실제괴리">
            <DeviationValue pct={etf.deviation_pct} />
          </MiniMetric>
        )}
        {visibleMetrics.includes("intraday") && (
          <MiniMetric label="장중괴리">
            <DeviationValue pct={etf.intraday_dev_pct} />
          </MiniMetric>
        )}
        <MiniMetric label="iNAV">
          <RollingText text={formatKrw(etf.inav_per_share)} />
        </MiniMetric>
        {visibleMetrics.includes("aum") && (
          <MiniMetric label="AUM(억)">
            <RollingText text={fmtEok(etf.aum_krw)} />
          </MiniMetric>
        )}
        {visibleMetrics.includes("expense") && (
          <MiniMetric label="보수율">
            {etf.expense_pct == null
              ? EMDASH
              : `${etf.expense_pct.toFixed(3)}%`}
          </MiniMetric>
        )}
        {visibleMetrics.includes("trade") && (
          <MiniMetric label="거래대금(억)">
            <RollingText text={fmtEok(etf.trade_value_krw)} />
          </MiniMetric>
        )}
        {visibleMetrics.includes("components") && (
          <MiniMetric label="구성종목">
            {etf.priced_component_count ?? EMDASH}
            {" / "}
            {etf.component_count ?? EMDASH}
          </MiniMetric>
        )}
        {visibleMetrics.includes("weight") && (
          <MiniMetric label="반영비중">
            <RollingText
              text={
                etf.priced_weight_pct == null
                  ? EMDASH
                  : `${etf.priced_weight_pct.toFixed(2)}%`
              }
            />
          </MiniMetric>
        )}
        {visibleMetrics.includes("lp") && (
          <MiniMetric label="LP대금(억)">
            <RollingText text={fmtEok(etf.lp_value_krw)} />
          </MiniMetric>
        )}
      </dl>
    </button>
  );
}

/* ── 호가카드 — CHECK 에이전트 5단계 잔량 (구 orderbook-card 이식) ────── */

function OrderbookCard({
  hoga,
  stale,
}: {
  hoga: HogaEtf | null;
  stale: boolean;
}) {
  if (!hoga) {
    return (
      <div className="rounded-2xl border-2 border-dashed border-hairline bg-canvas px-3 py-4 text-center text-[11px] font-semibold text-ink-faint">
        호가 수신 대기
      </div>
    );
  }
  const asks = padLevels(hoga.asks);
  const bids = padLevels(hoga.bids);
  const maxQty = Math.max(...asks, ...bids);
  const totalAsk = asks.reduce((s, v) => s + v, 0);
  const totalBid = bids.reduce((s, v) => s + v, 0);

  return (
    <div
      className={cn(
        "rounded-2xl border-2 border-hairline bg-canvas p-2.5 shadow-card",
        stale && "opacity-60",
      )}
    >
      {stale && (
        <div className="mb-1.5 flex items-center justify-center gap-1 rounded-md bg-amber-400/[0.15] py-0.5 text-[10px] font-bold text-amber-600">
          <AlertTriangle className="h-3 w-3" strokeWidth={2.2} />
          호가 지연/끊김
        </div>
      )}
      <div className="flex flex-col gap-[3px]">
        {ASK_LABELS.map((label, j) => (
          <OrderbookRow
            key={label}
            side="ask"
            label={label}
            qty={asks[j]}
            maxQty={maxQty}
          />
        ))}
        {/* 물량부족 하이라이트는 랜딩 모니터링 A 알림으로 이관 (2026-07-20) */}
        <div className="my-0.5 flex items-center justify-center gap-2 border-y border-hairline py-1 text-[10.5px] font-bold tabular-nums">
          <span className="text-ask">
            총매도 <RollingText text={totalAsk.toLocaleString("ko-KR")} />
          </span>
          <span className="text-ink-faint">/</span>
          <span className="text-bid">
            총매수 <RollingText text={totalBid.toLocaleString("ko-KR")} />
          </span>
        </div>
        {BID_LABELS.map((label, j) => (
          <OrderbookRow
            key={label}
            side="bid"
            label={label}
            qty={bids[j]}
            maxQty={maxQty}
          />
        ))}
      </div>
    </div>
  );
}

function OrderbookRow({
  side,
  label,
  qty,
  maxQty,
}: {
  side: "ask" | "bid";
  label: string;
  qty: number;
  maxQty: number;
}) {
  const pct = maxQty > 0 ? (qty / maxQty) * 100 : 0;
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-8 shrink-0 text-[10px] font-semibold text-ink-muted">
        {label}
      </span>
      <div
        className={cn(
          "h-[9px] flex-1 overflow-hidden rounded-[2px]",
          side === "ask" ? "bg-ask-soft" : "bg-bid-soft",
        )}
      >
        <div
          className={cn(
            "h-full rounded-[2px] transition-[width] duration-300 ease-out",
            side === "ask" ? "bg-ask" : "bg-bid",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={cn(
          "w-14 shrink-0 text-right text-[11px] font-bold tabular-nums",
          side === "ask" ? "text-ask" : "text-bid",
        )}
      >
        <RollingText text={qty.toLocaleString("ko-KR")} />
      </span>
    </div>
  );
}

// 5단 고정 패딩 — 결측/짧은 배열을 0으로 채워 카드 높이를 안정화.
function padLevels(levels: number[] | null | undefined): number[] {
  const out = [0, 0, 0, 0, 0];
  (levels ?? []).slice(0, 5).forEach((v, i) => {
    out[i] = Number.isFinite(v) ? Number(v) : 0;
  });
  return out;
}

function MiniMetric({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-[11px] font-semibold text-ink-muted">{label}</dt>
      <dd className="text-[12px] font-bold tabular-nums text-ink">{children}</dd>
    </div>
  );
}

function ChangeChip({ pct }: { pct: number | null }) {
  if (pct == null) {
    return <span className="text-[12px] text-ink-faint">{EMDASH}</span>;
  }
  const up = pct > 0;
  const down = pct < 0;
  return (
    <span
      className={cn(
        "rounded-md px-1.5 py-0.5 text-[12px] font-bold tabular-nums",
        up && "bg-status-failed/[0.08] text-status-failed",
        down && "bg-status-running/[0.08] text-status-running",
        !up && !down && "text-ink-secondary",
      )}
    >
      <RollingText text={signedPct(pct)} />
    </span>
  );
}

function DeviationValue({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-ink-faint">{EMDASH}</span>;
  const abs = Math.abs(pct);
  return (
    <span
      className={cn(
        "rounded px-1 py-0.5 font-bold",
        abs >= 2
          ? "bg-status-failed/[0.10] text-status-failed"
          : abs >= 1
            ? "bg-amber-400/[0.15] text-amber-700"
            : pct > 0
              ? "text-status-failed"
              : pct < 0
                ? "text-status-running"
                : "text-ink-secondary",
      )}
    >
      <RollingText text={signedPct(pct)} />
    </span>
  );
}

/* ── 표 뷰 ───────────────────────────────────────────────────────────── */

function EtfTable({
  etfs,
  onOpen,
}: {
  etfs: InavEtf[];
  onOpen: (ticker: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-[0_2px_10px_rgba(36,59,94,0.05)]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>티커</TableHeaderCell>
            <TableHeaderCell>종목명</TableHeaderCell>
            <TableHeaderCell className="text-right">iNAV</TableHeaderCell>
            <TableHeaderCell className="text-right">국내가</TableHeaderCell>
            <TableHeaderCell className="text-right">등락률</TableHeaderCell>
            <TableHeaderCell className="text-right">괴리율</TableHeaderCell>
            <TableHeaderCell className="text-right">AUM(억)</TableHeaderCell>
            <TableHeaderCell className="text-right">거래대금(억)</TableHeaderCell>
            <TableHeaderCell className="text-right">반영비중</TableHeaderCell>
            <TableHeaderCell className="text-right">구성종목</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {etfs.map((etf) => (
            <TableRow
              key={etf.ticker}
              className="cursor-pointer"
              onClick={() => onOpen(etf.ticker)}
            >
              <TableCell className="font-bold tabular-nums text-ge-navy">
                {etf.ticker}
              </TableCell>
              <TableCell>{etf.name || "—"}</TableCell>
              <TableCell className="text-right tabular-nums">
                <RollingText text={formatKrw(etf.inav_per_share)} />
              </TableCell>
              <TableCell className="text-right tabular-nums">
                <RollingText
                  text={
                    etf.kr_etf_price == null
                      ? EMDASH
                      : formatKrw(etf.kr_etf_price)
                  }
                />
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {etf.change_pct == null ? (
                  <span className="text-ink-faint">{EMDASH}</span>
                ) : (
                  <span
                    className={cn(
                      "font-semibold",
                      etf.change_pct > 0
                        ? "text-status-failed"
                        : etf.change_pct < 0
                          ? "text-status-running"
                          : "text-ink-secondary",
                    )}
                  >
                    <RollingText text={signedPct(etf.change_pct)} />
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {etf.deviation_pct == null ? (
                  <span className="text-ink-faint">{EMDASH}</span>
                ) : (
                  <DeviationValue pct={etf.deviation_pct} />
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtEok(etf.aum_krw)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtEok(etf.trade_value_krw)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {etf.priced_weight_pct == null
                  ? EMDASH
                  : `${etf.priced_weight_pct.toFixed(2)}%`}
              </TableCell>
              <TableCell className="text-right tabular-nums text-ink-muted">
                {etf.priced_component_count ?? EMDASH}
                {" / "}
                {etf.component_count ?? EMDASH}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/* ── FX 패널 ─────────────────────────────────────────────────────────── */

function FxPanel({ fx }: { fx: Record<string, number> }) {
  const entries = FX_ORDER.filter((c) => fx[c] != null).map(
    (c) => [c, fx[c]] as const,
  );
  // 스키마에 새 통화가 생기면 순서 밖 항목도 뒤에 붙인다.
  for (const [c, v] of Object.entries(fx)) {
    if (c !== "KRW" && !FX_ORDER.includes(c)) entries.push([c, v]);
  }

  return (
    <section className="rounded-2xl border border-hairline bg-canvas p-5 shadow-[0_2px_10px_rgba(36,59,94,0.05)]">
      <div className="mb-3 flex items-center gap-2">
        <span className="h-4 w-1.5 rounded-full bg-ge-point" />
        <span className="text-[13px] font-extrabold text-ge-navy">
          환율 (KRW 기준)
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4 lg:grid-cols-7">
        {entries.map(([code, rate]) => (
          <div key={code} className="flex flex-col">
            <span className="text-[11px] font-bold uppercase tracking-wider text-ink-muted">
              {code}
            </span>
            <span className="text-[15px] font-extrabold tabular-nums text-ge-navy">
              {formatRate(rate)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── 구성종목 모달 ───────────────────────────────────────────────────── */

type SortKey =
  | "isin"
  | "name"
  | "exchange"
  | "basePrice"
  | "livePrice"
  | "krwPrice"
  | "weightPct"
  | "tradeTime";

const NUMERIC_SORT_KEYS = new Set<SortKey>([
  "basePrice",
  "livePrice",
  "krwPrice",
  "weightPct",
]);

const SORT_COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "isin", label: "ISIN", numeric: false },
  { key: "name", label: "종목명", numeric: false },
  { key: "exchange", label: "거래소(통화)", numeric: false },
  { key: "basePrice", label: "전일종가", numeric: true },
  { key: "livePrice", label: "가격", numeric: true },
  { key: "krwPrice", label: "KRW 가격", numeric: true },
  { key: "weightPct", label: "비중", numeric: true },
  { key: "tradeTime", label: "갱신", numeric: false },
];

const koCollator = new Intl.Collator("ko", {
  numeric: true,
  sensitivity: "base",
});

function sortValue(row: InavComponentRow, key: SortKey): number | string | null {
  const raw = row[key];
  if (raw == null) return null;
  if (NUMERIC_SORT_KEYS.has(key)) {
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  }
  const text = String(raw).trim();
  return text === "" || text === "-" ? null : text;
}

function ComponentModal({
  ticker,
  payload,
  etf,
  onClose,
}: {
  ticker: string;
  payload: InavComponentsPayload | null;
  etf: InavEtf | null;
  onClose: () => void;
}) {
  const entry = payload?.byEtf?.[ticker] ?? null;
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({
    key: "weightPct",
    dir: -1,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = useMemo(() => {
    const list = entry?.components ?? [];
    const { key, dir } = sort;
    return [...list].sort((a, b) => {
      const av = sortValue(a, key);
      const bv = sortValue(b, key);
      if (av == null && bv == null) {
        return koCollator.compare(a.name || "", b.name || "");
      }
      if (av == null) return 1; // null/공란은 항상 마지막
      if (bv == null) return -1;
      let primary: number;
      if (typeof av === "number" && typeof bv === "number") {
        primary = av === bv ? 0 : av < bv ? -1 : 1;
      } else {
        primary = koCollator.compare(String(av), String(bv));
      }
      if (primary !== 0) return primary * dir;
      return koCollator.compare(a.name || "", b.name || "");
    });
  }, [entry, sort]);

  const currencies = useMemo(() => {
    if (!entry || !payload) return [] as string[];
    const seen = new Set<string>();
    for (const r of entry.components) {
      const c = r.currency;
      if (!c || c === "KRW" || payload.fxRates[c] == null) continue;
      seen.add(c);
    }
    return [...seen].sort((a, b) => {
      const ai = FX_ORDER.indexOf(a);
      const bi = FX_ORDER.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [entry, payload]);

  const toggleSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === 1 ? -1 : 1 }
        : { key, dir: NUMERIC_SORT_KEYS.has(key) ? -1 : 1 },
    );
  };

  const inavTotal = entry?.inavTotalKrw ?? null;
  const subParts: string[] = [];
  if (inavTotal != null && inavTotal > 0) {
    subParts.push(`iNAV ${fmtNum(inavTotal / INAV_DIVISOR, 2, 2)} KRW`);
    subParts.push(`iNAV총액 ${fmtNum(inavTotal / 1e8, 2, 2)} 억`);
  }
  if (payload?.generatedAt) subParts.push(`산출 ${payload.generatedAt}`);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-canvas shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-extrabold text-ge-navy">
              {(entry?.etfName || etf?.name || ticker) + " · " + ticker}
            </h2>
            <div className="mt-0.5 text-[12px] tabular-nums text-ink-muted">
              {subParts.join(" · ") || "—"}
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

        {currencies.length > 0 && payload && (
          <div className="flex flex-wrap items-center gap-2 border-b border-hairline bg-canvas-soft px-5 py-2.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-ink-muted">
              계산 환율
            </span>
            {currencies.map((c) => (
              <span
                key={c}
                className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas px-2.5 py-1"
              >
                <span className="text-[11px] font-semibold text-ink-muted">
                  {c}/KRW
                </span>
                <span className="text-[12px] font-bold tabular-nums text-ge-navy">
                  {fmtNum(payload.fxRates[c], 2, 4)}
                </span>
              </span>
            ))}
          </div>
        )}

        <div className="overflow-auto">
          {!entry ? (
            <p className="px-5 py-8 text-center text-sm text-ink-muted">
              컴포넌트 데이터를 불러오는 중…
            </p>
          ) : rows.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-ink-muted">
              표시할 컴포넌트가 없습니다.
            </p>
          ) : (
            <table className="w-full border-collapse text-[12.5px]">
              <thead className="sticky top-0 bg-ge-th">
                <tr>
                  {SORT_COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className={cn(
                        "cursor-pointer select-none whitespace-nowrap px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-ink-secondary",
                        col.numeric ? "text-right" : "text-left",
                        sort.key === col.key && "text-ge-point",
                      )}
                    >
                      {col.label}
                      {sort.key === col.key && (
                        <span className="ml-0.5">
                          {sort.dir > 0 ? "▲" : "▼"}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <ComponentRow key={`${r.isin ?? r.name}-${i}`} row={r} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function ComponentRow({ row }: { row: InavComponentRow }) {
  const hasLive = row.livePrice != null && Number.isFinite(row.livePrice);
  const priced = row.isCash ? hasLive : hasLive && (row.livePrice as number) > 0;
  const exch =
    (row.exchange || "") + (row.currency ? ` (${row.currency})` : "");
  const retPct =
    priced && !row.isCash && row.basePrice != null && row.basePrice > 0
      ? ((row.livePrice as number) / row.basePrice - 1) * 100
      : null;

  return (
    <tr
      className={cn(
        "border-t border-hairline/70",
        !priced && "opacity-45",
      )}
    >
      <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-ink-muted">
        {row.isin || "-"}
      </td>
      <td className="max-w-[220px] truncate px-3 py-1.5 font-semibold text-ink">
        {row.name || "-"}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-ink-secondary">
        {exch || "-"}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
        {row.isCash || row.basePrice == null
          ? "-"
          : fmtNum(row.basePrice, 2, 4)}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
        <span className="inline-flex items-center justify-end gap-1">
          <RollingText
            text={
              priced
                ? fmtNum(row.livePrice, row.isCash ? 0 : 2, row.isCash ? 0 : 4)
                : "-"
            }
          />
          {retPct != null && (
            <span
              className={cn(
                "text-[11px] font-semibold",
                retPct > 0
                  ? "text-status-failed"
                  : retPct < 0
                    ? "text-status-running"
                    : "text-ink-muted",
              )}
            >
              ({signedPct(retPct)})
            </span>
          )}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
        {row.krwPrice == null
          ? "-"
          : fmtNum(row.krwPrice, row.isCash ? 0 : 2, row.isCash ? 0 : 2)}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">
        {row.weightPct == null ? "-" : `${fmtNum(row.weightPct, 2, 2)}%`}
      </td>
      <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-ink-muted">
        {row.tradeTime || "-"}
      </td>
    </tr>
  );
}
