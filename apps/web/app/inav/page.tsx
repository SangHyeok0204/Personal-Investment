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
  ChevronDown,
  Eye,
  EyeOff,
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
  type HogaEtf,
  type InavComponentRow,
  type InavComponentsPayload,
  type InavEtf,
  type InavSnapshot,
  type InavSums,
} from "@/lib/api";
import { formatKrw, formatRate, formatRelativeTime } from "@/lib/format";
import {
  devSeverity,
  lpQuoteMissing,
  recognizedSpread,
  spreadBp,
  spreadSeverity,
  tickLadder,
  tickSize,
  toNum,
  type Severity,
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

// 호가 스프레드 bp 표기 — 1틱이 4~5bp라 정수로 끊으면 1틱 차이가 뭉개진다.
// 발화 구간(3~20틱)이 대략 12~85bp라 소수 1자리면 충분하다 (2026-07-29).
function formatBp(bp: number): string {
  return bp.toFixed(1);
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
  // 카드 뷰에서 사용자가 X로 숨긴 ETF (localStorage 영속). 삭제는 곧 숨김.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // 지수 급등락 줄 표시 여부 (localStorage 영속). 끄면 그 줄이 차지한 칸을 완전히
  // 내놓는다 — 숨김 상태에서도 Topbar '지수' 토글로 되살릴 수 있다 (2026-07-30).
  const [showIndex, setShowIndex] = useState(true);
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
    if (window.localStorage.getItem("inav-show-index-row") === "0")
      setShowIndex(false);
  }, []);

  const toggleIndexRow = useCallback(() => {
    setShowIndex((prev) => {
      const next = !prev;
      window.localStorage.setItem("inav-show-index-row", next ? "1" : "0");
      return next;
    });
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

  // 카드 뷰: ACE 지정 9종 우선, 나머지는 스냅샷 순서 유지 (stable sort).
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

  // 요약 바 시간대 상태(open/preopen/closed) — LP 호가 의무시간 09:05~15:20 만 값
  // 표시, 밖에서는 값을 숨기고 문구만 둔다(2026-07-30 확정).
  // 3초 폴링마다 재렌더되므로 경계는 폴링 주기 안에서 갱신된다.
  const phase = marketPhase();
  const quietWindow = phase !== "open";
  // 값을 믿을 수 있는 상태인가. 두 줄의 출처가 달라 게이트도 따로 둔다 —
  // 호가·물량은 CHECK 피드(지연 10s 초과면 낡은 호가), 괴리는 collector 스냅샷.
  // 예전엔 호가 게이트 하나로 '물량X'만 억제하고 bp 는 낡은 값으로 계속 띄웠다(허점 ⑥).
  const hogaReady = !quietWindow && !collectorDown && !hogaStale && hogaByCode.size > 0;
  const devReady = !quietWindow && !collectorDown && (data?.etfs?.length ?? 0) > 0;
  // ACE 9종 상시 요약 (고정 순서).
  const aceSummaries = useMemo(
    () => buildAceSummaries(data?.etfs ?? [], hogaByCode),
    [data, hogaByCode],
  );
  // 카드 테두리는 요약 바와 1:1 연동 — 바에서 빨강인 종목이 곧 빨간 카드.
  // 상시 표시로 바뀐 뒤로는 '값이 있으면 알림'이 아니라 '빨강 밴드면 알림'이다.
  const criticalByCode = useMemo(() => {
    const map = new Map<string, string>();
    if (!hogaReady && !devReady) return map;
    for (const s of aceSummaries) {
      if (!isCritical(s)) continue;
      const parts: string[] = [];
      if (hogaReady) {
        if (s.hoga.kind === "missing") parts.push("물량X");
        else if (s.hoga.kind === "bp" && spreadSeverity(s.hoga.bp) === "crit")
          parts.push(`${formatBp(s.hoga.bp)}bp`);
      }
      if (devReady) {
        if (s.actual != null && devSeverity(s.actual) === "crit")
          parts.push(`실제괴리 ${signedPct(s.actual)}`);
        if (s.intra != null && devSeverity(s.intra) === "crit")
          parts.push(`장중괴리 ${signedPct(s.intra)}`);
      }
      if (parts.length > 0) map.set(s.code, parts.join(" · "));
    }
    return map;
  }, [aceSummaries, hogaReady, devReady]);

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
            <button
              onClick={toggleIndexRow}
              title={
                showIndex
                  ? "지수 급등락 줄 숨기기 (칸을 내놓습니다)"
                  : "지수 급등락 줄 표시"
              }
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[12px] font-semibold transition-colors",
                showIndex
                  ? "border-ge-point bg-ge-point/[0.08] text-ge-point"
                  : "border-hairline bg-canvas-soft text-ink-muted hover:border-ge-point hover:text-ge-point",
              )}
            >
              {showIndex ? (
                <Eye className="h-3.5 w-3.5" />
              ) : (
                <EyeOff className="h-3.5 w-3.5" />
              )}
              지수
            </button>
            <ViewSwitch view={view} onChange={changeView} />
            <MetricSelect visible={metrics} onToggle={toggleMetric} />
          </>
        }
      />

      {/* Topbar(h-16) 바로 아래 스티키 띠 — 띠 자체는 상시, 알림 칩만 생겼다 사라진다. */}
      <div className="sticky top-16 z-10">
        <AlertBar
          summaries={aceSummaries}
          indexAlerts={indexAlerts}
          hogaReady={hogaReady}
          devReady={devReady}
          phase={phase}
          showIndex={showIndex}
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
                criticalByCode={criticalByCode}
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

/* 요약 바 시간대 상태 — 창의 기준은 '장 시간'이 아니라 **KRX LP 호가 제출 의무
   시간(09:05~15:20 KST)** 이다. 그 밖에서 호가가 얇은 건 LP 태만이 아니라 규정상
   면제이므로, 값을 띄우면 곧바로 오독이 된다.
     · open    09:05~15:20      : 값 표시(정상 감시 구간).
     · closed  15:20~익일 06:00 : 의무 종료 — 값 숨기고 문구만.
     · preopen 06:00~09:05      : 의무 시작 전 — 값 숨기고 문구만. 장전 동시호가와
       개장 직후 5분을 모두 포함한다.
   근거(2026-07-30 확인): 삼성자산운용 Kodex ETF 가이드 "9:00~9:05 : 호가 제출 불필요
   시간", 단일가매매 접수시간(오전 08:00~09:00 / 오후 15:20~15:30)도 면제.
   collector lp_eval 의 표본 구간(SESSION_START_MIN/SESSION_END_MIN)과 정확히 같다 —
   화면과 통계가 다른 창을 쓰면 서로 대조가 안 된다. */
const MARKET_OPEN_MIN = 9 * 60 + 5; // 09:05 LP 의무 시작 (개장 직후 5분은 면제)
const ALERT_END_MIN = 15 * 60 + 20; // 15:20 종가 단일가 진입 = 의무 종료
const PREOPEN_START_MIN = 6 * 60; // 06:00 → '장 마감' 종료, '점검 대기' 시작
// ※ 연속장은 15:30 까지고 개장은 09:00 이라 문구는 시장 시간과 5~10분 어긋난다.
//   목적이 'LP 의무 구간 감시'라 문구도 의무 기준으로 적는다(아래 phaseText).

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

// 3초 폴링마다 재렌더되므로 06:00/09:05/15:20 경계는 폴링 주기 안에서 갱신된다.
function marketPhase(): MarketPhase {
  const t = kstMinutesNow();
  if (t >= MARKET_OPEN_MIN && t < ALERT_END_MIN) return "open"; // 09:05~15:20
  if (t >= PREOPEN_START_MIN && t < MARKET_OPEN_MIN) return "preopen"; // 06:00~09:05
  return "closed"; // 15:20~익일 06:00
}

/* ── ACE 호가·괴리 상시 요약 ────────────────────────────────────────────
   ★2026-07-30 전환: 조건부 알림 → **상시 요약**. 예전엔 임계값을 넘은 종목만 칩으로
   띄웠는데(호가 15bp↑ / 괴리 1%↑), 이제 ACE 9종 전부의 값을 항상 보여주고 심각성은
   색으로만 나타낸다(hoga.ts spreadSeverity/devSeverity). 임계값을 넘지 않아도 값이
   보이므로 "지금 정상인지"와 "얼마나 정상인지"를 함께 읽을 수 있다.

   · 호가·물량 = 인정 스프레드 bp. 매도·매수 각각 최우선호가부터 바깥으로 훑어 처음
     LP 1,000주 이상 실린 호가를 "인정호가"로 잡고, (인정매도호가 − 인정매수호가)를
     체결가로 나눈 값이다. 카드 현재가와 무관한 순수 호가 스프레드.
     한쪽이라도 인정호가가 없으면 bp 를 낼 수 없어 '물량X'.
   · 괴리 = 실제(자체 iNAV 기준)·장중(거래소 공시) 2종. 실제괴리는 미국 데이장을
     반영해 공시와 갈라질 수 있어 따로 본다 (2026-07-23).

   표시 억제(quiet·피드 끊김)는 렌더 쪽에서 처리한다 — 여기서는 계산만 한다. */

// 호가 셀 상태. na = 판정 불가(피드에 종목 없음 / LP 미탑재 구 피드 / 체결가 없음)로,
// "LP 가 물량을 안 깔았다"(missing)와 구분한다.
type HogaCell =
  | { kind: "bp"; bp: number; ticks: number }
  | { kind: "missing" }
  | { kind: "na" };

interface AceSummary {
  code: string;
  name: string; // 툴팁용 정식명 (칩에는 약칭만 쓴다)
  hoga: HogaCell;
  actual: number | null; // 실제괴리 %
  intra: number | null; // 장중괴리 %
}

function buildAceSummaries(
  etfs: InavEtf[],
  hogaByCode: Map<string, HogaEtf>,
): AceSummary[] {
  const byTicker = new Map(etfs.map((e) => [e.ticker, e]));
  // 카드·표와 같은 고정 순서로 낸다 — 값이 상시 표시되므로 자리가 흔들리면 못 읽는다.
  return CARD_TICKER_ORDER.filter((code) => ACE_TICKERS.has(code)).map((code) => {
    const etf = byTicker.get(code);
    const hoga = hogaByCode.get(code);
    let cell: HogaCell = { kind: "na" };
    if (hoga) {
      if (lpQuoteMissing(hoga)) {
        cell = { kind: "missing" };
      } else {
        const spread = recognizedSpread(hoga);
        const bp = spread != null ? spreadBp(spread.won, spread.mid) : null;
        // ticks = 스프레드(원) ÷ 호가단위. 대상 ETF는 전부 2,000원 이상이라 5원 단위
        // 이므로 사용자가 말한 "스프레드를 5로 나눈 값"과 같다 (2026-07-30).
        if (bp != null && spread != null)
          cell = { kind: "bp", bp, ticks: spread.ticks };
      }
    }
    return {
      code,
      name: etf?.name || hoga?.name || code,
      hoga: cell,
      actual: etf?.deviation_pct ?? null,
      intra: etf?.intraday_dev_pct ?? null,
    };
  });
}

// 심각도 → 색. ETF 약칭은 색을 바꾸지 않는다(navy 고정) — 값만 물들여야 눈이 값으로
// 간다 (2026-07-30 사용자 지시: "ETF 명은 색깔 그대로 유지").
const SEVERITY_TEXT: Record<Severity, string> = {
  calm: "text-ink-faint",
  warn: "text-amber-600",
  crit: "text-status-failed",
};

// 줄별 '빨강' 판정 — 줄 라벨 색과 깜빡임은 그 줄의 값만 봐야 한다(실제괴리 줄이
// 장중괴리 때문에 빨개지면 어느 줄을 봐야 할지 알 수 없다).
function isHogaCrit(s: AceSummary): boolean {
  if (s.hoga.kind === "missing") return true;
  return s.hoga.kind === "bp" && spreadSeverity(s.hoga.bp) === "crit";
}

function isDevCrit(pct: number | null): boolean {
  return pct != null && devSeverity(pct) === "crit";
}

// 한 종목이 어느 줄에서든 '빨강'인가 — 카드 테두리 연동(합집합)에 쓴다.
function isCritical(s: AceSummary): boolean {
  return isHogaCrit(s) || isDevCrit(s.actual) || isDevCrit(s.intra);
}

// 흰 띠는 항상 떠 있고 알림 칩만 생멸한다. 흐르는 마퀴 없이 한 번만 렌더하고,
// 많아지면 줄바꿈으로 쌓인다. min-h 는 빈 상태에서도 높이가 흔들리지 않게 하는 값.
function AlertBar({
  summaries,
  indexAlerts,
  hogaReady,
  devReady,
  phase,
  showIndex,
}: {
  summaries: AceSummary[];
  indexAlerts: IndexAlert[];
  hogaReady: boolean;
  devReady: boolean;
  phase: MarketPhase;
  showIndex: boolean;
}) {
  // 네 줄 — 지수 급등락 / 호가·물량 / 실제괴리 / 장중괴리. 성격이 다른 값이 한 줄에
  // 섞이면 눈으로 훑을 때 구분이 안 된다 (2026-07-23·07-27 사용자 요청).
  // 괴리는 2026-07-30 사용자 요청으로 실제/장중을 각자 흰 밴드 한 줄씩 차지하게
  // 분리했다 — 한 줄에 '실 -0.15% 장 +0.16%'로 붙여 두면 두 지표가 눈에서 섞인다.
  // open(=LP 의무시간 09:05~15:20) 이 아니면 세 줄 모두 값 없이 상태 문구만 둔다
  // (2026-07-27·07-30 사용자 확정: 상시 요약으로 바꿔도 의무 없는 구간의 숫자는
  // 오독을 부른다). 문구도 의무 기준 — '장 개시 전'·'장 마감'으로 쓰면 09:00~09:05,
  // 15:20~15:30 에 사실과 어긋난다.
  const phaseText =
    phase === "closed"
      ? "LP 의무 종료 · 장 마감"
      : phase === "preopen"
        ? "LP 의무 시작 전 · 점검 대기"
        : null;
  return (
    <div className="border-b border-hairline bg-white px-6 py-0.5">
      {/* 지수 줄은 숨기면 차지한 칸을 완전히 내놓는다 — 구분선까지 함께 빠진다
          (2026-07-30 사용자 요청). 복원은 Topbar '지수' 토글. */}
      {showIndex && (
        <>
          <IndexAlertRow items={indexAlerts} />
          <div className="border-t border-hairline/70" />
        </>
      )}
      {/* 열 머리 — 값이 실제로 그려질 때만 띄운다(전부 억제 상태면 이름만 남아 혼란). */}
      {phaseText == null && (hogaReady || devReady) && (
        <SummaryHeader summaries={summaries} />
      )}
      <SummaryRow
        label="호가·물량"
        summaries={summaries}
        // 호가는 CHECK 피드 신선도에 달려 있다.
        blockedText={phaseText ?? (hogaReady ? null : "호가 대기 중")}
        isCrit={isHogaCrit}
        render={(s) => ({
          main: <HogaValue cell={s.hoga} />,
          suffix:
            s.hoga.kind === "bp" ? <TickSuffix ticks={s.hoga.ticks} /> : null,
        })}
      />
      <div className="border-t border-hairline/70" />
      {/* 괴리 2종은 각각 한 줄 — 괴리는 collector 스냅샷 값이라 CHECK 지연과
          무관하므로 호가와 게이트를 따로 둔다. */}
      <SummaryRow
        label="실제괴리"
        summaries={summaries}
        blockedText={phaseText ?? (devReady ? null : "스냅샷 대기 중")}
        isCrit={(s) => isDevCrit(s.actual)}
        render={(s) => ({ main: <DevValue pct={s.actual} /> })}
        alignRight
      />
      <div className="border-t border-hairline/70" />
      <SummaryRow
        label="장중괴리"
        summaries={summaries}
        blockedText={phaseText ?? (devReady ? null : "스냅샷 대기 중")}
        isCrit={(s) => isDevCrit(s.intra)}
        render={(s) => ({ main: <DevValue pct={s.intra} /> })}
        alignRight
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
function useNewItemsFlash(keys: string[], active = true): number {
  const seen = useRef<Set<string> | null>(null);
  const [flash, setFlash] = useState(0);
  // 1초 폴링마다 items 배열 정체성이 바뀌므로 내용(key 목록)으로만 반응한다.
  const signature = keys.join("|");
  useEffect(() => {
    // 값을 못 그리는 구간(세션 밖·피드 대기)에서는 기준선을 버린다. 데이터가 비동기로
    // 도착하므로 '첫 렌더는 깜빡이지 않는다'는 아래 가드만으로는 부족했다 — 빈 상태가
    // 기준선이 되어 데이터 도착을 '새 항목'으로 오인해 페이지를 열 때마다 번쩍였다
    // (2026-07-30 실측). 다시 활성화된 첫 렌더가 새 기준선이 된다.
    if (!active) {
      seen.current = null;
      return;
    }
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

// 상시 요약 줄 — ACE 9종을 고정 순서로 전부 그린다. 값이 항상 있으므로 셀 폭을
// 고정해 줄바꿈이 일어나도 세로로 열이 맞게 한다(눈이 같은 자리를 훑을 수 있게).
// 줄 라벨은 그 줄에 빨강이 하나라도 있을 때만 빨강 — 없으면 차분한 회색을 유지한다.
function SummaryRow({
  label,
  summaries,
  blockedText,
  isCrit,
  render,
  alignRight = false,
}: {
  label: string;
  summaries: AceSummary[];
  // null 이면 값 표시, 문자열이면 값을 숨기고 그 문구만 (세션 밖·피드 대기).
  blockedText: string | null;
  // 이 줄 기준의 '빨강' 판정 — 라벨 색·깜빡임에 쓴다.
  isCrit: (s: AceSummary) => boolean;
  // main = 정렬 대상 수치(오른쪽 정렬), suffix = 부가 표기(왼쪽 정렬, 예 "(2틱)").
  render: (s: AceSummary) => { main: ReactNode; suffix?: ReactNode };
  // 부가 표기를 아예 안 쓰는 줄(괴리 2종)은 수치를 셀 오른쪽 끝에 붙인다
  // (2026-08-05 사용자 요청). 호가 줄은 "(N틱)" 자리를 비워둬야 bp 가 헤더 약칭과
  // 같은 축에 서므로 그대로 둔다. **줄 단위** 선택이라 한 줄 안에서 칸이 들쭉날쭉해질
  // 일은 없다 — 셀마다 판단하면 '물량X'(틱 없음)만 오른쪽으로 튄다.
  alignRight?: boolean;
}) {
  const blocked = blockedText != null;
  // 상시 표시라 '새 알림'이 없다 — 대신 **빨강으로 새로 진입한 종목**이 생기면
  // 깜빡인다 (2026-07-30). 회색↔오렌지까지 깜빡이면 상시 번쩍여 쓸모가 없다.
  const critKeys = blocked
    ? []
    : summaries.filter(isCrit).map((s) => `${label}:${s.code}`);
  const flash = useNewItemsFlash(critKeys, !blocked);
  return (
    <div
      key={flash}
      className={cn(
        // -mx-6 px-6 = 깜빡임 배경이 띠 좌우 끝까지 차게 한다. 열 정렬을 위해 셀
        // 사이 gap 은 두지 않는다(폭이 이미 고정) — 헤더 줄과 같은 격자 상수를 쓴다.
        "-mx-6 flex flex-nowrap items-stretch overflow-x-auto px-6",
        GRID_ROW_H,
        flash > 0 && "inav-alert-flash",
      )}
    >
      <span
        className={cn(
          GRID_LABEL,
          "inline-flex items-center gap-1 text-[17px] font-extrabold leading-none tracking-tight",
          !blocked && critKeys.length > 0 ? "text-status-failed" : "text-ink-faint",
        )}
      >
        <AlertTriangle className="h-[18px] w-[18px] shrink-0" strokeWidth={2.6} />
        {label}
      </span>
      {blocked ? (
        <span className="flex items-center text-[17px] font-semibold leading-none text-ink-muted">
          {blockedText}
        </span>
      ) : (
        summaries.map((s) => {
          const { main, suffix } = render(s);
          return (
            // 종목명은 위 헤더 줄이 한 번만 이고, 값 줄은 같은 고정폭 열에 수치만 담는다
            // — 줄마다 약칭을 반복하면 읽을 만한 글자 크기로 9종이 한 줄에 안 들어간다
            // (실측: [우주테크]가 이름칸을 넘치고 [고배당]이 다음 줄로 밀렸다).
            <span
              key={s.code}
              className={cn(GRID_CELL, "flex items-center")}
              title={s.name}
            >
              {alignRight ? (
                <span className={GRID_MAIN_FULL}>{main}</span>
              ) : (
                <>
                  <span className={GRID_MAIN}>{main}</span>
                  <span className={GRID_SUFFIX}>{suffix}</span>
                </>
              )}
            </span>
          );
        })
      )}
    </div>
  );
}

// 호가 값 — bp / 물량X / 판정불가. 색은 bp 밴드(20·40)로 고른다. 물량X 는 인정호가가
// 아예 없다는 뜻이라 최상위 심각도(빨강)로 둔다.
function HogaValue({ cell }: { cell: HogaCell }) {
  if (cell.kind === "na") {
    return (
      <span className="text-[17px] font-extrabold leading-none text-ink-faint">
        {EMDASH}
      </span>
    );
  }
  if (cell.kind === "missing") {
    return (
      <span className="text-[17px] font-extrabold leading-none text-status-failed">
        물량X
      </span>
    );
  }
  return (
    <span
      className={cn(
        "text-[17px] font-extrabold leading-none tabular-nums",
        SEVERITY_TEXT[spreadSeverity(cell.bp)],
      )}
    >
      {formatBp(cell.bp)}bp
    </span>
  );
}

/* ── 요약 격자 (엑셀 셀) ────────────────────────────────────────────────
   2026-07-30 사용자 요청: 가로·세로를 확실히 고정해 셀처럼 보이게 한다. 글자 길이가
   달라도 어긋나지 않도록 ①열 폭 ②행 높이 ③세로 구분선을 전부 고정값으로 박고,
   헤더와 값 줄이 **같은 상수**를 쓰게 해 격자가 갈라질 수 없게 만든다. */
const GRID_LABEL = "w-[112px] shrink-0"; // 줄 라벨 칸
const GRID_CELL = "w-[120px] shrink-0 border-l border-hairline/60 px-1"; // 종목 1칸
const GRID_MAIN = "w-[68px] shrink-0 text-right"; // 정렬 대상 수치
const GRID_SUFFIX = "w-[44px] shrink-0 pl-1 text-left"; // 부가 표기 "(N틱)"
// 부가 표기가 아예 없는 줄(괴리 2종)용 — 수치가 셀 오른쪽 끝에 붙는다.
const GRID_MAIN_FULL = "w-full text-right";
const GRID_ROW_H = "h-[30px]"; // 값 줄 높이 (고정)

// 값 줄들이 공유하는 열 머리 — ETF 약칭을 한 번만 쓴다. 수치와 같은 GRID_MAIN 칸에
// 오른쪽 정렬해 이름과 숫자가 같은 축에 서게 한다.
function SummaryHeader({ summaries }: { summaries: AceSummary[] }) {
  return (
    <div className="flex h-[22px] flex-nowrap items-center overflow-x-auto">
      <span className={GRID_LABEL} />
      {summaries.map((s) => (
        <span
          key={s.code}
          title={s.name}
          className={cn(GRID_CELL, "flex items-center")}
        >
          <span
            className={cn(
              GRID_MAIN,
              "truncate text-[12px] font-bold leading-none text-ge-navy",
            )}
          >
            {ACE_SHORT_NAMES[s.code] ?? s.code}
          </span>
          <span className={GRID_SUFFIX} />
        </span>
      ))}
    </div>
  );
}

// 호가 셀의 부가 표기 "(N틱)" — bp 는 종목 가격대를 정규화한 값이라 실제 호가가 몇 틱
// 벌어졌는지는 따로 봐야 알 수 있다 (2026-07-30 사용자 요청). 색은 입히지 않는다 —
// 밴드 색은 bp 가 가지고, 틱은 참고 수치다.
function TickSuffix({ ticks }: { ticks: number }) {
  return (
    <span className="text-[13px] font-semibold leading-none tabular-nums text-ink-faint">
      ({ticks}틱)
    </span>
  );
}

// 괴리 값 — 절댓값 밴드(1%·2%)로 색을 고른다. 실제/장중이 각각 자기 줄을 가지므로
// (2026-07-30 분리) 어느 지표인지는 줄 라벨이 말해준다 — 셀에는 수치만 남긴다.
function DevValue({ pct }: { pct: number | null }) {
  return (
    <span
      className={cn(
        "text-[17px] font-extrabold leading-none tabular-nums",
        pct == null ? "text-ink-faint" : SEVERITY_TEXT[devSeverity(pct)],
      )}
    >
      {pct == null ? EMDASH : signedPct(pct)}
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
  criticalByCode,
}: {
  etfs: InavEtf[];
  visibleMetrics: MetricKey[];
  onOpen: (ticker: string) => void;
  onHide?: (ticker: string) => void;
  hogaByCode: Map<string, HogaEtf>;
  hogaStale: boolean;
  // 요약 바에서 '빨강'인 종목 → 사유 문구. 없는 코드는 정상.
  criticalByCode: Map<string, string>;
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
            criticalText={criticalByCode.get(etf.ticker)}
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
  criticalText,
}: {
  etf: InavEtf;
  visibleMetrics: MetricKey[];
  onOpen: () => void;
  criticalText?: string;
}) {
  // 경고 표시는 요약 바 단일 기준 — 바에서 빨강(40bp↑·물량X·괴리 2%↑)인 종목만
  // 굵은 빨강 테두리 (2026-07-30: 상시 표시로 바뀌어 '값 있음'은 기준이 못 된다).
  const alerted = criticalText != null;
  const alertText = criticalText ?? "";

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
