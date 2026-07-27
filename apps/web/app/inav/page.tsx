"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  LayoutGrid,
  RotateCcw,
  Search,
  Table2,
  X,
} from "lucide-react";
import { useIndexAlerts, type IndexAlert } from "@/components/index-alerts";
import {
  ApiError,
  getInavComponents,
  getInavHoga,
  getInavSnapshot,
  getLpEval,
  type HogaEtf,
  type InavComponentRow,
  type InavComponentsPayload,
  type InavEtf,
  type InavSnapshot,
  type InavSums,
  type LpEvalBasisStat,
  type LpEvalEtf,
} from "@/lib/api";
import { formatKrw, formatRate, formatRelativeTime } from "@/lib/format";
import {
  DEV_ABS_ALERT_PCT,
  SPREAD_ALERT_MIN_TICKS,
  lpQuoteMissing,
  recognizedSpreadTicks,
  tickLadder,
  tickSize,
  toNum,
} from "@/lib/hoga";
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
  "0180V0", // ACE 미국우주테크액티브
  "0199C0", // ACE 고배당주Plus커버드콜액티브
];

// 호가·괴리 알림 대상 = ACE 모니터링 대상(현재 9종, 위 우선순서 집합과 동일).
const ACE_TICKERS = new Set(CARD_TICKER_ORDER);

// 알림 칩에 종목코드 대신 쓰는 줄임말 (2026-07-24 사용자 지정).
const ACE_SHORT_NAMES: Record<string, string> = {
  "414270": "글자", // ACE 글로벌자율주행액티브
  "457480": "테밸", // ACE 테슬라밸류체인액티브
  "483320": "엔밸", // ACE 엔비디아밸류체인액티브
  "483330": "마밸", // ACE 마이크로소프트밸류체인액티브
  "483340": "구밸", // ACE 구글밸류체인액티브
  "0079X0": "비밸", // ACE BYD밸류체인액티브
  "0118Z0": "AI테크", // ACE 미국AI테크핵심산업액티브
  "0180V0": "우주테크", // ACE 미국우주테크액티브
  "0199C0": "고배당", // ACE 고배당주Plus커버드콜액티브
};

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

/* ── 임시 조치 (2026-07-23) ───────────────────────────────────────────
   ACE고배당주Plus커버드콜액티브(0199C0)는 구성종목이 전부 국내 주식이라
   실제괴리와 장중괴리가 원리상 같아야 한다. 자체 iNAV 쪽이 아직 어긋나 있어
   거래소 공시 장중괴리 값을 실제괴리에 덮어쓴다. 표시·알림·테이블이 모두
   이 값을 쓰게 되므로 화면 전체가 일관된다.
   ※ 원인(구성종목 2종 미갱신 추정) 규명 후 이 블록 통째로 제거할 것. */
const DEV_MIRROR_TICKERS = new Set(["0199C0"]);

function applyDevMirror(
  snapshot: InavSnapshot | undefined,
): InavSnapshot | undefined {
  if (!snapshot) return snapshot;
  return {
    ...snapshot,
    etfs: snapshot.etfs.map((etf) =>
      DEV_MIRROR_TICKERS.has(etf.ticker) && etf.intraday_dev_pct != null
        ? { ...etf, deviation_pct: etf.intraday_dev_pct }
        : etf,
    ),
  };
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
  const [lpEvalOpen, setLpEvalOpen] = useState(false);
  // 카드 뷰에서 사용자가 X로 숨긴 ETF (localStorage 영속). 삭제는 곧 숨김.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // 지수 급등락 하루 알림 (서버측 계산) — AlertBar 3번째 줄에 지수별 최신 1건 표시.
  const { alerts: indexAlerts } = useIndexAlerts();

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
    const storedHidden = window.localStorage.getItem("inav-hidden-cards");
    if (storedHidden) {
      try {
        const parsed = JSON.parse(storedHidden) as string[];
        if (Array.isArray(parsed)) setHidden(new Set(parsed));
      } catch {
        /* 무시 */
      }
    }
  }, []);

  const hideCard = useCallback((ticker: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(ticker);
      window.localStorage.setItem(
        "inav-hidden-cards",
        JSON.stringify([...next]),
      );
      return next;
    });
  }, []);

  const restoreHidden = useCallback(() => {
    setHidden(new Set());
    window.localStorage.setItem("inav-hidden-cards", "[]");
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

  const data = useMemo(() => applyDevMirror(query.data), [query.data]);
  const componentsData = componentsQuery.data ?? null;
  const collectorDown =
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 503;

  // 카드 뷰: ACE 지정 8종 우선, 나머지는 스냅샷 순서 유지 (stable sort).
  const orderedEtfs = useMemo(() => {
    const etfs = data?.etfs ?? [];
    const rank = new Map(CARD_TICKER_ORDER.map((t, i) => [t, i]));
    return [...etfs].sort(
      (a, b) =>
        (rank.get(a.ticker) ?? CARD_TICKER_ORDER.length) -
        (rank.get(b.ticker) ?? CARD_TICKER_ORDER.length),
    );
  }, [data]);

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

  // 알림 바 시간대 상태(open/preopen/closed) — 09:00~16:00 만 알림 표시, 16:00 이후
  // '장 마감', 06:00~09:00 '장 개시 대기'. open 이 아니면 호가/괴리 알림을 억제한다
  // (문구만 다름). 3초 폴링마다 재렌더되므로 경계는 폴링 주기 안에서 갱신된다.
  const phase = marketPhase();
  const quietWindow = phase !== "open"; // preopen·closed 모두 알림 억제
  // 알림 0건을 "이상 없음"이라 말할 수 있는 상태인가. 피드가 죽었거나 지연이면
  // 판정 자체가 불가능하므로 거짓 안심을 주지 않는다. '물량X' 판정도 이 신선도
  // 게이트를 쓴다 — 피드가 끊긴 걸 "LP 물량 없음"으로 오인하지 않도록.
  const alertsReady = !collectorDown && !hogaStale && hogaByCode.size > 0;
  // ACE 호가·괴리 알림 (고정 목록으로 표시).
  const aceAlerts = useMemo(
    () => buildAceAlerts(data?.etfs ?? [], hogaByCode, quietWindow, alertsReady),
    [data, hogaByCode, quietWindow, alertsReady],
  );
  // 카드 테두리는 알림 바와 1:1 연동 — 바에 뜬 종목이 곧 빨간 카드.
  const alertsByCode = useMemo(() => {
    const map = new Map<string, AceAlert[]>();
    for (const a of aceAlerts) {
      const list = map.get(a.code);
      if (list) list.push(a);
      else map.set(a.code, [a]);
    }
    return map;
  }, [aceAlerts]);

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
            {view === "cards" && hidden.size > 0 && (
              <button
                onClick={restoreHidden}
                title="숨긴 카드를 모두 다시 표시"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-hairline bg-canvas-soft px-2.5 text-[12px] font-semibold text-ink-muted transition-colors hover:border-ge-point hover:text-ge-point"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                숨김 {hidden.size} · 복원
              </button>
            )}
            <ViewSwitch view={view} onChange={changeView} />
            <MetricSelect visible={metrics} onToggle={toggleMetric} />
            <button
              onClick={() => setLpEvalOpen(true)}
              title="LP 평가 — 인정 스프레드 틱 분포·통계(일별)"
              className="flex h-8 items-center gap-1.5 rounded-lg border border-hairline bg-canvas-soft px-2.5 text-[12px] font-semibold text-ink-muted transition-colors hover:border-ge-point hover:text-ge-point"
            >
              <BarChart3 className="h-3.5 w-3.5" />
              LP평가
            </button>
          </>
        }
      />

      {/* Topbar(h-16) 바로 아래 스티키 띠 — 띠 자체는 상시, 알림 칩만 생겼다 사라진다. */}
      <div className="sticky top-16 z-10">
        <AlertBar
          items={aceAlerts}
          indexAlerts={indexAlerts}
          ready={alertsReady}
          phase={phase}
        />
      </div>

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
                etfs={orderedEtfs.filter((e) => !hidden.has(e.ticker))}
                visibleMetrics={metrics}
                onOpen={setModalTicker}
                onHide={hideCard}
                hogaByCode={hogaByCode}
                hogaStale={hogaStale}
                alertsByCode={alertsByCode}
              />
            ) : (
              <EtfTable
                etfs={data.etfs}
                onOpen={setModalTicker}
                visibleMetrics={metrics}
              />
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

        {lpEvalOpen && <LpEvalModal onClose={() => setLpEvalOpen(false)} />}
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

// 알림 바 시간대 상태 — 하루 3구간(KST, 2026-07-27 사용자 요청):
//   · open    09:00~16:00        : 호가·물량/괴리 알림 표시(정상).
//   · closed  16:00~익일 06:00   : '장 마감' — 알림 억제, 상태 문구만.
//   · preopen 06:00~09:00        : '장 개시 전 · 점검 대기' — LP 호가가 아직
//     신뢰할 수 없어 알림 억제(2026-07-22). 장전 동시호가 포함, 09:00 개장에 open.
// preopen·closed 모두 알림은 억제하고 상태 문구만 다르다.
const MARKET_OPEN_MIN = 9 * 60; // 09:00 개장 → 알림 시작
const ALERT_END_MIN = 16 * 60; // 16:00 → 알림 종료, 장 마감 표시 시작
const PREOPEN_START_MIN = 6 * 60; // 06:00 → 장 마감 종료, 장 개시 대기 시작

type MarketPhase = "open" | "preopen" | "closed";

// 현재 한국시각(KST)의 자정 기준 분. 뷰어/컨테이너 TZ와 무관하게 Asia/Seoul 기준.
function kstMinutesNow(): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  return (h % 24) * 60 + m;
}

// 3초 폴링마다 재렌더되므로 06:00/09:00/16:00 경계는 폴링 주기 안에서 갱신된다.
function marketPhase(): MarketPhase {
  const t = kstMinutesNow();
  if (t >= MARKET_OPEN_MIN && t < ALERT_END_MIN) return "open"; // 09:00~16:00
  if (t >= PREOPEN_START_MIN && t < MARKET_OPEN_MIN) return "preopen"; // 06:00~09:00
  return "closed"; // 16:00~익일 06:00
}

/* ── ACE 호가·괴리 알림 전광판 (고정 목록) ─────────────────────────────
   대상: ACE 8종. 문구는 최대한 함축한다 — 줄 라벨이 이미 성격을 말해주므로 칩에는
   핵심 수치만 남긴다.
   · "N틱": 인정 스프레드가 N틱. 매도·매수 각각 최우선호가부터 처음 1,000주 이상
     실린 틱을 "인정호가"로 잡고, (인정매도호가 − 인정매수호가)를 틱단위로 나눈
     값이다. 카드 현재가와 무관한 순수 호가 스프레드로, 얇은 호가만 앞에 깔려
     있으면 인정호가가 뒤로 밀려 스프레드가 벌어진다. 3틱 이상일 때만 알린다 —
     1~2틱은 정상 스프레드 (2026-07-24 사용자 재정의).
   · "실제괴리": |실제괴리| ≥ DEV_ABS_ALERT_PCT(1%).
   · "장중괴리": |장중괴리(거래소 공시)| ≥ DEV_ABS_ALERT_PCT — 실제괴리가 미국
     데이장 반영으로 공시 iNAV와 갈라질 수 있어 별도 감시.
   quiet=true(개장 09:00~16:00 밖 — 장 개시 대기/장 마감)면 괴리 2종·호가 판정을
   모두 건너뛴다. */

interface AceAlert {
  key: string;
  code: string;
  status: string;
  severity: "hoga" | "dev";
}

function buildAceAlerts(
  etfs: InavEtf[],
  hogaByCode: Map<string, HogaEtf>,
  quiet: boolean,
  feedFresh: boolean,
): AceAlert[] {
  const out: AceAlert[] = [];
  for (const etf of etfs) {
    if (!ACE_TICKERS.has(etf.ticker)) continue;
    const code = etf.ticker;

    const hoga = hogaByCode.get(code);
    if (!quiet && hoga) {
      if (feedFresh && lpQuoteMissing(hoga)) {
        // LP가 한쪽이라도 물량을 아예 안 깔았음 — 예전엔 인정 스프레드가 null 로
        // 떨어져 조용히 넘어갔다. '물량X'로 드러낸다 (2026-07-27 사용자 요청).
        // 스프레드 판정은 건너뛴다 — LP가 비었는데 총호가 스프레드까지 같이
        // 띄우면 칩이 중복돼 헷갈린다.
        out.push({
          key: `${code}:lpmissing`,
          code,
          status: "물량X",
          severity: "hoga",
        });
      } else {
        // 인정 스프레드 — 매도·매수 각각 최우선호가부터 처음 1,000주 이상 실린 틱을
        // 인정호가로 잡고, 두 인정호가의 가격차를 틱으로 환산한다. 얇은 호가만 앞에
        // 깔려 있으면 인정호가가 뒤로 밀려 스프레드가 벌어진다. 3틱 이상 벌어졌을
        // 때만 알린다 — 1~2틱은 정상 스프레드다 (2026-07-24 사용자 재정의).
        const spreadTicks = recognizedSpreadTicks(hoga);
        if (spreadTicks != null && spreadTicks >= SPREAD_ALERT_MIN_TICKS) {
          out.push({
            key: `${code}:spread`,
            code,
            status: `${spreadTicks}틱`,
            severity: "hoga",
          });
        }
      }
    }

    // 괴리 알림도 장 개시 전(quiet) 구간엔 억제한다 — 개장 전 iNAV/시세가 아직
    // 신뢰할 수 없어 호가 판정과 동일하게 '점검 대기'로 남긴다 (2026-07-24 사용자 요청).
    if (!quiet) {
      // 절대 괴리율 과대 — 자체 iNAV 기준(카드도 빨강 테두리 연동).
      const actual = etf.deviation_pct;
      if (actual != null && Math.abs(actual) >= DEV_ABS_ALERT_PCT) {
        out.push({
          key: `${code}:devabs`,
          code,
          status: `실제괴리 ${signedPct(actual)}`,
          severity: "dev",
        });
      }

      // 장중괴리(거래소 공시 premiumIntra) 과대 — 실제괴리는 미국 데이장을 반영해
      // 공시 iNAV 기준과 갈라질 수 있으므로 공시 괴리도 따로 감시한다 (2026-07-23).
      const intra = etf.intraday_dev_pct;
      if (intra != null && Math.abs(intra) >= DEV_ABS_ALERT_PCT) {
        out.push({
          key: `${code}:intradev`,
          code,
          status: `장중괴리 ${signedPct(intra)}`,
          severity: "dev",
        });
      }
    }
  }
  return out;
}

// 흰 띠는 항상 떠 있고 알림 칩만 생멸한다. 흐르는 마퀴 없이 한 번만 렌더하고,
// 많아지면 줄바꿈으로 쌓인다. min-h 는 빈 상태에서도 높이가 흔들리지 않게 하는 값.
function AlertBar({
  items,
  indexAlerts,
  ready,
  phase,
}: {
  items: AceAlert[];
  indexAlerts: IndexAlert[];
  ready: boolean;
  phase: MarketPhase;
}) {
  // 세 줄 — 지수 급등락 / 호가·물량 / 괴리. 성격이 다른 알림이 한 줄에
  // 섞이면 눈으로 훑을 때 구분이 안 된다 (2026-07-23·07-27 사용자 요청).
  const hogaItems = items.filter((it) => it.severity === "hoga");
  const devItems = items.filter((it) => it.severity === "dev");
  // open 이 아니면 호가·물량/괴리 줄은 알림 없이 상태 문구만 — 16:00~06:00 '장 마감',
  // 06:00~09:00 '장 개시 전 · 점검 대기' (2026-07-27 사용자 요청).
  const phaseText =
    phase === "closed"
      ? "장 마감"
      : phase === "preopen"
        ? "장 개시 전 · 점검 대기"
        : null;
  return (
    <div className="border-b border-hairline bg-white px-6 py-0.5">
      <IndexAlertRow items={indexAlerts} />
      <div className="border-t border-hairline/70" />
      <AlertRow
        label="호가·물량"
        tone="hoga"
        items={hogaItems}
        emptyText={phaseText ?? (ready ? "이상 없음" : "호가 대기 중")}
      />
      <div className="border-t border-hairline/70" />
      <AlertRow
        label="괴리"
        tone="dev"
        items={devItems}
        emptyText={phaseText ?? "이상 없음"}
      />
    </div>
  );
}

// 칩 정렬용 고정 지수 순서(그 외 코드는 뒤로).
const INDEX_ORDER = ["KOSPI", "KOSDAQ", "NQ_FUT"];

// 지수 급등락 — 지수별 '최신 1건'만 표시하는 줄(서버측 하루 로그). 호가/괴리 줄과
// 동일 위상·크기. 방향으로 색을 나눈다(상승=빨강·하락=파랑).
function IndexAlertRow({ items }: { items: IndexAlert[] }) {
  // items 는 최신 우선 → 코드별 첫 항목 = 그 지수의 최신 알림. 지수당 하나만 남긴다.
  const seen = new Set<string>();
  const latest: IndexAlert[] = [];
  for (const a of items) {
    if (!seen.has(a.code)) {
      seen.add(a.code);
      latest.push(a);
    }
  }
  latest.sort((a, b) => {
    const ia = INDEX_ORDER.indexOf(a.code);
    const ib = INDEX_ORDER.indexOf(b.code);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  const empty = latest.length === 0;
  const flash = useNewItemsFlash(latest.map((a) => a.id));
  return (
    <div
      key={flash}
      className={cn(
        "-mx-6 flex min-h-[28px] flex-wrap items-center gap-x-6 gap-y-0 px-6",
        flash > 0 && "inav-alert-flash",
      )}
    >
      <span
        className={cn(
          "inline-flex w-[112px] shrink-0 items-center gap-1 text-[17px] font-extrabold leading-none tracking-tight",
          empty ? "text-ink-faint" : "text-ge-point",
        )}
      >
        <AlertTriangle className="h-[18px] w-[18px] shrink-0" strokeWidth={2.6} />
        지수 급등락
      </span>
      {empty ? (
        <span className="text-[17px] font-semibold leading-none text-ink-muted">
          장중 급등락 없음
        </span>
      ) : (
        latest.map((a) => <IndexChip key={a.code} a={a} />)
      )}
    </div>
  );
}

function IndexChip({ a }: { a: IndexAlert }) {
  const isRange = a.kind === "roll1h";
  const up = isRange ? (a.rose ?? true) : a.changePct >= 0;
  const dir = up ? "text-status-failed" : "text-status-running";
  const glyph = up ? "▲" : "▼";
  const sign = up ? "+" : "−";
  const val = Math.abs(isRange ? (a.spreadPct ?? 0) : a.changePct);
  const unit = isRange ? "%p" : "%";
  const hm = (s?: string | null) => (s ? s.slice(11, 16) : "--:--");
  const firedTime = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(a.at));
  // roll1h: 급등락이 일어난 구간(시간순, 저점↔고점) / open5: 발화 시각.
  const timeText = isRange
    ? `${up ? hm(a.minAt) : hm(a.maxAt)}→${up ? hm(a.maxAt) : hm(a.minAt)}`
    : firedTime;
  const tip = isRange
    ? `${a.label} · 최근 1시간 · ${up ? `저점 ${hm(a.minAt)} → 고점 ${hm(a.maxAt)}` : `고점 ${hm(a.maxAt)} → 저점 ${hm(a.minAt)}`}`
    : `${a.label} · 장 초반 · ${firedTime}`;
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1.5" title={tip}>
      <span className="text-[18px] font-bold leading-none text-ge-navy">
        [{a.label}]
      </span>
      <span className={cn("text-[20px] font-extrabold leading-none", dir)}>
        {glyph}
        {sign}
        {val.toFixed(2)}
        {unit}
      </span>
      <span className="text-[13px] font-semibold leading-none tabular-nums text-ink-muted">
        {timeText}
      </span>
    </span>
  );
}

// 직전에 없던 알림 key 가 하나라도 생기면 카운터를 올린다. 이 값을 줄 엘리먼트의
// key 로 써서 리마운트시키면 깜빡임 애니메이션이 매번 처음부터 다시 돈다.
// 첫 렌더(이전 상태 없음)는 깜빡이지 않는다 — 페이지를 열 때마다 번쩍이면 곤란.
function useNewItemsFlash(keys: string[]): number {
  const seen = useRef<Set<string> | null>(null);
  const [flash, setFlash] = useState(0);
  // 1초 폴링마다 items 배열 정체성이 바뀌므로 내용(key 목록)으로만 반응한다.
  const signature = keys.join("|");
  useEffect(() => {
    const current = new Set(signature ? signature.split("|") : []);
    const previous = seen.current;
    seen.current = current;
    if (previous == null) return;
    for (const key of current) {
      if (!previous.has(key)) {
        setFlash((n) => n + 1);
        return;
      }
    }
  }, [signature]);
  return flash;
}

// 가시성 우선 — 여백을 줄이고 글자를 띠 높이에 꽉 차게 키운다.
function AlertRow({
  label,
  tone,
  items,
  emptyText,
}: {
  label: string;
  tone: "hoga" | "dev";
  items: AceAlert[];
  emptyText: string;
}) {
  const empty = items.length === 0;
  const flash = useNewItemsFlash(items.map((it) => it.key));
  return (
    <div
      key={flash}
      className={cn(
        // -mx-6 px-6 = 깜빡임 배경이 띠 좌우 끝까지 차게 한다.
        "-mx-6 flex min-h-[28px] flex-wrap items-center gap-x-6 gap-y-0 px-6",
        flash > 0 && "inav-alert-flash",
      )}
    >
      <span
        className={cn(
          "inline-flex w-[112px] shrink-0 items-center gap-1 text-[17px] font-extrabold leading-none tracking-tight",
          empty
            ? "text-ink-faint"
            : tone === "dev"
              ? "text-status-failed"
              : "text-amber-600",
        )}
      >
        <AlertTriangle className="h-[18px] w-[18px] shrink-0" strokeWidth={2.6} />
        {label}
      </span>
      {empty ? (
        <span className="text-[17px] font-semibold leading-none text-ink-muted">
          {emptyText}
        </span>
      ) : (
        // 한 종목에 판정이 여러 개 걸려도 칩은 하나로 묶는다 — 코드가 반복되면
        // 훑기만 어려워지므로 문구만 "·"로 잇는다 (예: [414270] 3틱 · 1~3틱).
        groupByCode(items).map((g) => (
          <AlertChip key={g.code} code={g.code} statuses={g.statuses} tone={tone} />
        ))
      )}
    </div>
  );
}

// 등장 순서를 유지한 채 종목코드로 묶는다.
function groupByCode(items: AceAlert[]): { code: string; statuses: string[] }[] {
  const byCode = new Map<string, string[]>();
  for (const item of items) {
    const statuses = byCode.get(item.code);
    if (statuses) statuses.push(item.status);
    else byCode.set(item.code, [item.status]);
  }
  return [...byCode].map(([code, statuses]) => ({ code, statuses }));
}

function AlertChip({
  code,
  statuses,
  tone,
}: {
  code: string;
  statuses: string[];
  tone: "hoga" | "dev";
}) {
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1.5">
      <span className="text-[18px] font-bold leading-none text-ge-navy">
        [{ACE_SHORT_NAMES[code] ?? code}]
      </span>
      <span
        className={cn(
          "text-[20px] font-extrabold leading-none",
          tone === "dev" ? "text-status-failed" : "text-amber-600",
        )}
      >
        {statuses.join(" · ")}
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
  onHide,
  hogaByCode,
  hogaStale,
  alertsByCode,
}: {
  etfs: InavEtf[];
  visibleMetrics: MetricKey[];
  onOpen: (ticker: string) => void;
  onHide?: (ticker: string) => void;
  hogaByCode: Map<string, HogaEtf>;
  hogaStale: boolean;
  alertsByCode: Map<string, AceAlert[]>;
}) {
  if (!etfs.length) {
    return (
      <p className="text-sm text-ink-muted">표시할 ETF가 없습니다.</p>
    );
  }
  return (
    <div className="grid grid-cols-5 gap-3">
      {etfs.map((etf) => (
        <div key={etf.ticker} className="group/card relative flex flex-col gap-2">
          {onHide && (
            // 카드는 자체가 <button> 이라 내부 중첩 대신 래퍼에 절대배치로 얹는다.
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onHide(etf.ticker);
              }}
              title="이 카드 숨기기"
              aria-label={`${etf.name || etf.ticker} 카드 숨기기`}
              className="absolute right-1.5 top-1.5 z-10 rounded-full bg-white/85 p-1 text-ink-faint opacity-70 shadow-sm ring-1 ring-hairline transition-all hover:bg-status-failed hover:text-white hover:opacity-100 hover:ring-status-failed group-hover/card:opacity-100"
            >
              <X className="h-3.5 w-3.5" strokeWidth={2.4} />
            </button>
          )}
          <EtfCard
            etf={etf}
            visibleMetrics={visibleMetrics}
            onOpen={() => onOpen(etf.ticker)}
            alerts={alertsByCode.get(etf.ticker)}
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
  alerts,
}: {
  etf: InavEtf;
  visibleMetrics: MetricKey[];
  onOpen: () => void;
  alerts?: AceAlert[];
}) {
  // 경고 표시는 알림 바 단일 기준 — 바에 뜬 종목만 굵은 빨강 테두리.
  const alerted = (alerts?.length ?? 0) > 0;
  const alertText = (alerts ?? []).map((a) => a.status).join(" · ");

  return (
    <button
      type="button"
      onClick={onOpen}
      title={
        alerted
          ? `${alertText} — 클릭하면 구성종목 상세를 엽니다`
          : "클릭하면 구성종목 상세를 엽니다"
      }
      className={cn(
        "flex flex-col gap-2.5 rounded-2xl bg-canvas p-3.5 text-left shadow-card transition hover:-translate-y-px hover:shadow-panel",
        alerted
          ? "border-[3px] border-status-failed"
          : "border-2 border-hairline",
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
        {alerted && (
          <span
            title={alertText}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-failed/[0.10] text-status-failed"
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
  // 연속 5틱 창(최우선호가 기준). 표시 잔량은 LP 호가(lpAskQtys/lpBidQtys) — CHECK
  // 는 10틱 싣지만 가격 사다리(askPrices/bidPrices)가 5단이라 tickLadder 가 가격에
  // 매칭되는 앞 5틱만 쓴다 (2026-07-24 사용자 요청: 총호가는 수신만·표시는 LP 5틱).
  // 가격 배열이 없는 구 피드에서는 예전처럼 "상위 5호가 잔량(총호가)"으로 폴백한다 —
  // 이때는 틱 위치를 알 수 없어 매도N/매수N 라벨.
  const tick = tickSize(
    toNum(hoga.bestAsk) ?? toNum(hoga.bestBid) ?? toNum(hoga.price) ?? 0,
  );
  type Level = { price: number | null; qty: number };
  const askRows: Level[] =
    tickLadder(hoga.askPrices, hoga.lpAskQtys, tick, "ask") ??
    [...padLevels(hoga.asks)].reverse().map((qty) => ({ price: null, qty }));
  const bidRows: Level[] =
    tickLadder(hoga.bidPrices, hoga.lpBidQtys, tick, "bid") ??
    padLevels(hoga.bids).map((qty) => ({ price: null, qty }));
  const maxQty = Math.max(
    ...askRows.map((l) => l.qty),
    ...bidRows.map((l) => l.qty),
  );
  // 합계는 화면에 보이는 창 기준 — 창 밖 잔량은 표시하지 않으므로 합계에도 넣지 않는다.
  const totalAsk = askRows.reduce((s, l) => s + l.qty, 0);
  const totalBid = bidRows.reduce((s, l) => s + l.qty, 0);

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
        {ASK_LABELS.map((label, j) => {
          // 창은 최우선호가부터 위로 쌓이는데 표시는 먼 호가가 위라 뒤집는다.
          const level = askRows[ASK_LABELS.length - 1 - j];
          return (
            <OrderbookRow
              key={label}
              side="ask"
              label={
                level.price != null ? level.price.toLocaleString("ko-KR") : label
              }
              isBest={j === ASK_LABELS.length - 1}
              qty={level.qty}
              maxQty={maxQty}
            />
          );
        })}
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
        {BID_LABELS.map((label, j) => {
          // 표시 순서와 창 인덱스가 모두 매수1→아래로 5틱이라 그대로 쓴다.
          const level = bidRows[j];
          return (
            <OrderbookRow
              key={label}
              side="bid"
              label={
                level.price != null ? level.price.toLocaleString("ko-KR") : label
              }
              isBest={j === 0}
              qty={level.qty}
              maxQty={maxQty}
            />
          );
        })}
      </div>
    </div>
  );
}

function OrderbookRow({
  side,
  label,
  qty,
  maxQty,
  isBest = false,
}: {
  side: "ask" | "bid";
  label: string;
  qty: number;
  maxQty: number;
  isBest?: boolean;
}) {
  const pct = maxQty > 0 ? (qty / maxQty) * 100 : 0;
  return (
    <div className="flex items-center gap-1.5">
      {/* 라벨 자리에 틱별 호가를 싣기 때문에 폭이 넓다 — 바(flex-1)가 그만큼 줄어든다. */}
      <span
        className={cn(
          "w-[52px] shrink-0 text-[11px] tabular-nums",
          isBest
            ? cn("font-extrabold", side === "ask" ? "text-ask" : "text-bid")
            : "font-semibold text-ink-muted",
        )}
      >
        <RollingText text={label} />
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

type TableCol = {
  id: string;
  label: string;
  numeric: boolean;
  metric?: MetricKey; // 있으면 카드와 동일하게 '표시 지표' 토글로 show/hide
  cellClass?: string;
  value: (e: InavEtf) => number | string | null; // 정렬 기준값
  render: (e: InavEtf) => ReactNode;
};

// 테이블 컬럼 = 항상 표시(티커·종목명·iNAV·국내가·등락률) + 지표 컬럼(metric 지정).
// 지표 컬럼은 카드의 '표시 지표' 토글(visibleMetrics)로 show/hide 되어 카드/테이블이
// 완전 대칭이다. 순서·라벨·포맷은 카드 미니지표(CARD_METRICS)와 맞춘다.
const TABLE_COLS: TableCol[] = [
  {
    id: "ticker",
    label: "티커",
    numeric: false,
    value: (e) => e.ticker,
    render: (e) => (
      <span className="font-bold tabular-nums text-ge-navy">{e.ticker}</span>
    ),
  },
  { id: "name", label: "종목명", numeric: false, value: (e) => e.name ?? "", render: (e) => e.name || "—" },
  {
    id: "inav",
    label: "iNAV",
    numeric: true,
    value: (e) => e.inav_per_share,
    render: (e) => <RollingText text={formatKrw(e.inav_per_share)} />,
  },
  {
    id: "price",
    label: "국내가",
    numeric: true,
    value: (e) => e.kr_etf_price,
    render: (e) => (
      <RollingText text={e.kr_etf_price == null ? EMDASH : formatKrw(e.kr_etf_price)} />
    ),
  },
  {
    id: "change",
    label: "등락률",
    numeric: true,
    value: (e) => e.change_pct,
    render: (e) =>
      e.change_pct == null ? (
        <span className="text-ink-faint">{EMDASH}</span>
      ) : (
        <span
          className={cn(
            "font-semibold",
            e.change_pct > 0
              ? "text-status-failed"
              : e.change_pct < 0
                ? "text-status-running"
                : "text-ink-secondary",
          )}
        >
          <RollingText text={signedPct(e.change_pct)} />
        </span>
      ),
  },
  {
    id: "deviation",
    label: "실제괴리",
    numeric: true,
    metric: "deviation",
    value: (e) => e.deviation_pct,
    render: (e) =>
      e.deviation_pct == null ? (
        <span className="text-ink-faint">{EMDASH}</span>
      ) : (
        <DeviationValue pct={e.deviation_pct} />
      ),
  },
  {
    id: "intraday",
    label: "장중괴리",
    numeric: true,
    metric: "intraday",
    value: (e) => e.intraday_dev_pct,
    render: (e) =>
      e.intraday_dev_pct == null ? (
        <span className="text-ink-faint">{EMDASH}</span>
      ) : (
        <DeviationValue pct={e.intraday_dev_pct} />
      ),
  },
  { id: "aum", label: "AUM(억)", numeric: true, metric: "aum", value: (e) => e.aum_krw, render: (e) => fmtEok(e.aum_krw) },
  {
    id: "expense",
    label: "보수율",
    numeric: true,
    metric: "expense",
    value: (e) => e.expense_pct,
    render: (e) => (e.expense_pct == null ? EMDASH : `${e.expense_pct.toFixed(3)}%`),
  },
  {
    id: "trade",
    label: "거래대금(억)",
    numeric: true,
    metric: "trade",
    value: (e) => e.trade_value_krw,
    render: (e) => fmtEok(e.trade_value_krw),
  },
  {
    id: "components",
    label: "구성종목",
    numeric: true,
    metric: "components",
    cellClass: "text-ink-muted",
    value: (e) => e.priced_component_count ?? null,
    render: (e) => `${e.priced_component_count ?? EMDASH} / ${e.component_count ?? EMDASH}`,
  },
  {
    id: "weight",
    label: "반영비중",
    numeric: true,
    metric: "weight",
    value: (e) => e.priced_weight_pct,
    render: (e) =>
      e.priced_weight_pct == null ? EMDASH : `${e.priced_weight_pct.toFixed(2)}%`,
  },
  {
    id: "lp",
    label: "LP대금(억)",
    numeric: true,
    metric: "lp",
    value: (e) => e.lp_value_krw,
    render: (e) => fmtEok(e.lp_value_krw),
  },
];

function EtfTable({
  etfs,
  onOpen,
  visibleMetrics,
}: {
  etfs: InavEtf[];
  onOpen: (ticker: string) => void;
  visibleMetrics: MetricKey[];
}) {
  const [q, setQ] = useState("");
  const [aceOnly, setAceOnly] = useState(false);
  const [sort, setSort] = useState<{ id: string; dir: 1 | -1 } | null>(null);

  // 표시 지표 토글 반영 — 카드와 동일한 visibleMetrics 로 지표 컬럼 show/hide.
  const cols = useMemo(
    () => TABLE_COLS.filter((c) => !c.metric || visibleMetrics.includes(c.metric)),
    [visibleMetrics],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return etfs.filter((e) => {
      if (aceOnly && !(e.name ?? "").toUpperCase().startsWith("ACE")) {
        return false;
      }
      if (!needle) return true;
      return (
        e.ticker.toLowerCase().includes(needle) ||
        (e.name ?? "").toLowerCase().includes(needle)
      );
    });
  }, [etfs, q, aceOnly]);

  // 헤더 클릭 정렬 — 같은 컬럼 재클릭은 방향 토글, 다른 컬럼은 기본 방향(숫자=내림차순).
  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const col = TABLE_COLS.find((c) => c.id === sort.id);
    if (!col) return filtered;
    const arr = [...filtered];
    arr.sort((a, b) => {
      const av = col.value(a);
      const bv = col.value(b);
      const aNull = av == null || av === "";
      const bNull = bv == null || bv === "";
      if (aNull && bNull) return 0;
      if (aNull) return 1; // 결측/공란은 방향 무관 항상 맨 아래
      if (bNull) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv), "ko");
      return cmp * sort.dir;
    });
    return arr;
  }, [filtered, sort]);

  const toggleSort = (col: TableCol) =>
    setSort((prev) =>
      prev?.id === col.id
        ? { id: col.id, dir: prev.dir === 1 ? -1 : 1 }
        : { id: col.id, dir: col.numeric ? -1 : 1 },
    );

  return (
    <section className="overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-[0_2px_10px_rgba(36,59,94,0.05)]">
      {/* 필터 툴바 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="티커·종목명 검색"
            className="h-8 w-60 rounded-lg border border-hairline bg-canvas-soft pl-8 pr-7 text-[12.5px] text-ge-navy outline-none placeholder:text-ink-faint focus:border-ge-point"
          />
          {q && (
            <button
              onClick={() => setQ("")}
              title="지우기"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ge-point"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <button
          onClick={() => setAceOnly((v) => !v)}
          className={cn(
            "h-8 rounded-lg border px-3 text-[12px] font-semibold transition-colors",
            aceOnly
              ? "border-ge-point bg-ge-blue-bg text-ge-point"
              : "border-hairline bg-canvas-soft text-ink-muted hover:text-ge-point",
          )}
        >
          자사(ACE)만
        </button>
        <span className="ml-auto text-[11.5px] tabular-nums text-ink-muted">
          {filtered.length} / {etfs.length}
        </span>
      </div>
      <Table>
        <TableHead>
          <TableRow>
            {cols.map((col) => {
              const active = sort?.id === col.id;
              return (
                <TableHeaderCell
                  key={col.id}
                  onClick={() => toggleSort(col)}
                  title="클릭하여 정렬"
                  className={cn(
                    "cursor-pointer select-none whitespace-nowrap hover:text-ge-point",
                    active && "text-ge-point",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex w-full items-center gap-1",
                      col.numeric ? "justify-end" : "justify-start",
                    )}
                  >
                    {col.label}
                    <span
                      className={cn("text-[9px]", active ? "text-ge-point" : "text-transparent")}
                    >
                      {active && sort?.dir === 1 ? "▲" : "▼"}
                    </span>
                  </span>
                </TableHeaderCell>
              );
            })}
          </TableRow>
        </TableHead>
        <TableBody>
          {sorted.map((etf) => (
            <TableRow
              key={etf.ticker}
              className="cursor-pointer"
              onClick={() => onOpen(etf.ticker)}
            >
              {cols.map((col) => (
                <TableCell
                  key={col.id}
                  className={cn(
                    col.numeric && "text-right tabular-nums",
                    col.cellClass,
                  )}
                >
                  {col.render(etf)}
                </TableCell>
              ))}
            </TableRow>
          ))}
          {sorted.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={cols.length}
                className="py-8 text-center text-[13px] text-ink-muted"
              >
                검색 결과가 없습니다.
              </TableCell>
            </TableRow>
          )}
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

/* ── LP 평가 모달 — 인정 스프레드 틱 체류시간(분) 분포·통계(일별) ─────────
   collector /lp-eval 를 열 때만 30초 폴링(장중 실시간 누적 반영). ACE 8종 카드 =
   틱별 히스토그램 + 평균·최빈·중앙값. 기준 토글 LP(기본, 리테일 제외)/총호가. */

// 스프레드가 넓을수록(=LP 부실) 진하게. 'none'(5틱내 인정호가 없음)이 최악.
function lpBucketColor(key: string): string {
  if (key === "none") return "bg-rose-600";
  const t = Number(key);
  if (t >= 6) return "bg-rose-500";
  if (t === 5) return "bg-amber-600";
  if (t === 4) return "bg-amber-500";
  return "bg-amber-400"; // 3틱
}

function LpStat({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div>
      <div className="text-[10px] font-semibold text-ink-faint">{label}</div>
      <div className={cn("text-[13px] font-extrabold tabular-nums", danger ? "text-rose-600" : "text-ge-navy")}>
        {value}
      </div>
    </div>
  );
}

function LpEvalCard({ etf, basis }: { etf: LpEvalEtf; basis: "lp" | "total" }) {
  const stat: LpEvalBasisStat | undefined = etf.basis[basis];
  // 표시 버킷 = 알림틱(3,4,5,…) 오름차순 + 마지막 '없음'. 'ok'(정상)은 하단 컨텍스트로만.
  const bars = useMemo(() => {
    const h = stat?.hist ?? {};
    const ticks = Object.keys(h)
      .filter((k) => k !== "none" && k !== "ok")
      .map(Number)
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b)
      .map(String);
    if (h.none) ticks.push("none");
    return ticks.map((k) => ({ key: k, count: h[k] ?? 0 }));
  }, [stat]);
  const max = Math.max(1, ...bars.map((b) => b.count));
  const hasData = (stat?.total_min ?? 0) > 0;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-canvas p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-[13px] font-bold text-ge-navy">{etf.name || etf.code}</div>
        <div className="shrink-0 text-[10px] font-semibold tabular-nums text-ink-faint">{etf.code}</div>
      </div>
      {!hasData ? (
        <div className="py-5 text-center text-[11px] text-ink-faint">데이터 없음 (장중 누적)</div>
      ) : bars.length === 0 ? (
        <div className="py-5 text-center text-[11px] font-semibold text-emerald-600">
          알림 없음 · 스프레드 정상 {stat?.ok_min ?? 0}분
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-1">
            {bars.map(({ key, count }) => (
              <div key={key} className="flex items-center gap-1.5">
                <span className="w-9 shrink-0 text-right text-[11px] font-semibold tabular-nums text-ink-muted">
                  {key === "none" ? "없음" : `${key}틱`}
                </span>
                <div className="h-3 flex-1 overflow-hidden rounded-[2px] bg-canvas-soft">
                  <div
                    className={cn("h-full rounded-[2px]", lpBucketColor(key))}
                    style={{ width: `${(count / max) * 100}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-[11px] font-bold tabular-nums text-ink">
                  {count}
                </span>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-1 border-t border-hairline pt-2 text-center">
            <LpStat label="평균" value={stat?.mean_tick != null ? `${fmtNum(stat.mean_tick, 1, 2)}틱` : "—"} />
            <LpStat label="최빈" value={stat?.mode_tick != null ? `${stat.mode_tick}틱` : "—"} />
            <LpStat label="중앙" value={stat?.median_tick != null ? `${stat.median_tick}틱` : "—"} />
          </div>
          <div className="flex items-center justify-center gap-2 text-[10.5px] tabular-nums text-ink-muted">
            <span>알림 <b className="text-ink">{stat?.alert_min ?? 0}</b>분</span>
            <span className="text-ink-faint">·</span>
            <span>없음 <b className={cn((stat?.none_min ?? 0) > 0 && "text-rose-600")}>{stat?.none_min ?? 0}</b>분</span>
            <span className="text-ink-faint">·</span>
            <span>정상 {stat?.ok_min ?? 0}분</span>
          </div>
        </>
      )}
    </div>
  );
}

function LpEvalModal({ onClose }: { onClose: () => void }) {
  const [date, setDate] = useState<string | null>(null); // null = 오늘(서버 기본)
  const [basis, setBasis] = useState<"lp" | "total">("lp");
  const query = useQuery({
    queryKey: ["lpEval", date],
    queryFn: () => getLpEval(date ?? undefined),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = query.data ?? null;
  const dates = d?.available_dates ?? [];
  const curDate = date ?? d?.trade_date ?? "";
  const empty =
    d != null && d.etfs.every((e) => (e.basis[basis]?.total_min ?? 0) === 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-canvas shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-extrabold text-ge-navy">
              LP 평가 · 인정 스프레드 틱 분포
            </h2>
            <div className="mt-0.5 text-[12px] tabular-nums text-ink-muted">
              {d
                ? `${curDate} · 정규장 ${d.session.start}~${d.session.end} · 1,000주↑ 인정호가 · ${d.alert_min_ticks}틱↑ 알림`
                : "불러오는 중…"}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
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
            {dates.length > 0 && (
              <select
                value={curDate}
                onChange={(e) => setDate(e.target.value)}
                className="rounded-lg border border-hairline bg-canvas px-2 py-1 text-[12px] font-semibold text-ink-muted"
              >
                {dates.map((dt) => (
                  <option key={dt} value={dt}>
                    {dt}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              aria-label="닫기"
              onClick={onClose}
              className="rounded-lg p-1.5 text-ink-muted transition hover:bg-canvas-soft hover:text-ink"
            >
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>
        </div>

        <div className="overflow-auto p-4">
          {query.isError ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오지 못했습니다.</p>
          ) : !d ? (
            <p className="py-10 text-center text-sm text-ink-muted">불러오는 중…</p>
          ) : empty ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              {curDate} 누적 데이터가 없습니다. 정규장(09:00~15:30) 중 자동으로 쌓입니다.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {d.etfs.map((etf) => (
                <LpEvalCard key={etf.code} etf={etf} basis={basis} />
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-hairline px-5 py-2 text-[11px] text-ink-faint">
          기준{" "}
          {basis === "lp"
            ? "LP 물량 — 리테일 제외, LP 성실도"
            : "총호가 — 화면 알림 전광판과 동일"}{" "}
          · 값 = 체류시간(분) · 통계는 알림틱(≥{d?.alert_min_ticks ?? 3}) 대상, ‘없음’ 제외
        </div>
      </div>
    </div>
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
