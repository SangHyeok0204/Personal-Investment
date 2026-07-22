"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  ApiError,
  getWrapSnapshot,
  type WrapHolding,
  type WrapPayload,
  type WrapPortfolio,
} from "@/lib/api";
import { RollingText } from "@/components/rolling-text";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

const EMDASH = "−";

// 수익률/기여도 부호색 — 대시보드 컨벤션(＋빨강 / −파랑).
const POS = "#e74c3c"; // status-failed
const NEG = "#4a7ab5"; // status-running

function fmtNum(value: number | null | undefined, min = 0, max = 2): string {
  if (value == null || !Number.isFinite(value)) return EMDASH;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
}

function signedPct(pct: number | null | undefined, digits = 2): string {
  if (pct == null || !Number.isFinite(pct)) return EMDASH;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

// 부호 있는 숫자 — % 없이 (기여 컬럼용).
function signedNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function signTextClass(v: number | null | undefined): string {
  if (v == null) return "text-ink-secondary";
  return v > 0
    ? "text-status-failed"
    : v < 0
      ? "text-status-running"
      : "text-ink-secondary";
}

// 현금 판정: ticker=CASH 또는 이름에 '현금' — 정렬 시 항상 맨 아래 (구 뷰어와 동일).
function isCashHolding(h: WrapHolding): boolean {
  return (
    String(h.ticker || "").toUpperCase() === "CASH" ||
    String(h.name || "").includes("현금")
  );
}

export default function WrapPage() {
  const query = useQuery({
    queryKey: ["wrapSnapshot"],
    queryFn: getWrapSnapshot,
    refetchInterval: 3000,
    retry: false,
  });

  const [selKey, setSelKey] = useState<string | null>(null);
  const [krw, setKrw] = useState(false); // 원화 환산 토글 (off=USD, on=환율 포함)

  const data = query.data;
  const collectorDown =
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 503;

  const portfolios = data?.portfolios ?? [];
  const selected =
    portfolios.find((p) => p.key === selKey) ?? portfolios[0] ?? null;

  const stale = data != null && Date.now() - data.timestamp > 60_000;

  return (
    <>
      <Topbar
        title="WRAP 모니터"
        subtitle="시장 모니터링 · 랩 포트폴리오 실시간 수익률"
        status={
          data ? (
            <span className="flex items-center gap-2 truncate text-[11px] text-slate-400">
              가격 기준 {data.priceGeneratedAt}
              {stale && (
                <span className="rounded-full border border-amber-400/40 bg-amber-400/[0.12] px-2 py-0.5 font-semibold text-amber-700">
                  지연
                </span>
              )}
            </span>
          ) : undefined
        }
      />
      <PageContainer wide>
        {query.isError && !collectorDown && (
          <div className="mb-4">
            <ApiErrorBanner error={query.error} />
          </div>
        )}

        {collectorDown && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-amber-400/40 bg-amber-400/[0.08] px-5 py-4 text-amber-700">
            <AlertTriangle className="h-5 w-5 shrink-0" strokeWidth={2} />
            <div>
              <div className="text-sm font-bold">collector 미기동 / WRAP 미준비</div>
              <div className="mt-0.5 text-[13px] text-amber-700/80">
                수집 서비스가 실행 중이 아니거나 WRAP 페이로드가 아직
                준비되지 않았습니다.
              </div>
            </div>
          </div>
        )}

        {query.isLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-28 w-full rounded-2xl" />
            <Skeleton className="h-64 w-full rounded-2xl" />
            <Skeleton className="h-96 w-full rounded-2xl" />
          </div>
        ) : data && selected ? (
          <div className="space-y-4">
            {/* ① 포트폴리오 수익률 카드 (① 전일확정 · ② 실시간) */}
            <div>
              <div className="mb-2 flex items-center justify-end">
                <FxToggle krw={krw} onChange={setKrw} />
              </div>
              <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]">
                {portfolios.map((p) => (
                  <PortfolioCard
                    key={p.key}
                    p={p}
                    selected={p.key === selected.key}
                    krw={krw}
                    onSelect={() => setSelKey(p.key)}
                  />
                ))}
              </div>
            </div>

            {/* ② 분류별 비중·기여도 트리 */}
            <section className="rounded-2xl border border-hairline bg-canvas p-5 shadow-card">
              <div className="mb-1 flex items-center gap-2">
                <span className="h-4 w-1.5 rounded-full bg-ge-point" />
                <span className="text-[13px] font-extrabold text-ge-navy">
                  분류별 비중·기여도 — {selected.name}
                </span>
              </div>
              <CategoryTree p={selected} />
            </section>

            {/* ③ 구성종목 기여도 테이블 */}
            <section className="overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
              <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3">
                <div className="flex items-center gap-2">
                  <span className="h-4 w-1.5 rounded-full bg-ge-point" />
                  <span className="text-[13px] font-extrabold text-ge-navy">
                    구성종목 — {selected.name}
                  </span>
                </div>
                <StatusLight ok={!stale} />
              </div>
              <HoldingsTable p={selected} />
            </section>
          </div>
        ) : (
          !collectorDown && (
            <p className="text-sm text-ink-muted">
              WRAP 데이터를 표시할 수 없습니다.
            </p>
          )
        )}
      </PageContainer>
    </>
  );
}

/* ── ① 포트폴리오 수익률 카드 ────────────────────────────────────────── */

// "YYYYMMDD" → "M/D" (기준 종가일 라벨).
function fmtBasis(d: string | null | undefined): string {
  if (!d || d.length !== 8) return "";
  return `${Number(d.slice(4, 6))}/${Number(d.slice(6, 8))}`;
}

// 원화 환산 토글 — off=USD 가격수익률, on=환율 포함 원화수익률. ①②에 동시 적용.
function FxToggle({
  krw,
  onChange,
}: {
  krw: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={krw}
      onClick={() => onChange(!krw)}
      title="수익률을 원화(환율 포함)로 환산"
      className="inline-flex items-center gap-2 text-[11px] font-semibold"
    >
      <span className={krw ? "text-ge-point" : "text-ink-muted"}>원화 환산</span>
      <span
        className={cn(
          "relative h-4 w-7 rounded-full transition-colors",
          krw ? "bg-ge-point" : "bg-slate-300",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all",
            krw ? "left-3.5" : "left-0.5",
          )}
        />
      </span>
    </button>
  );
}

function PortfolioCard({
  p,
  selected,
  krw,
  onSelect,
}: {
  p: WrapPortfolio;
  selected: boolean;
  krw: boolean;
  onSelect: () => void;
}) {
  // ② 전일종가→최근체결가, ① 전전일→전일 종가수익률 — 토글에 따라 USD/원화.
  const ret2 = krw ? p.return2_krw ?? null : p.return2_usd ?? p.return_pct;
  const ret1 = krw ? p.return1_krw ?? null : p.return1_usd ?? null;
  const basis = fmtBasis(p.return1_basis_date);
  const stale1 = p.return1_is_current === false;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex flex-col gap-1.5 rounded-2xl border-2 bg-canvas p-4 text-left shadow-card transition hover:-translate-y-px hover:shadow-panel",
        selected ? "border-ge-point" : "border-hairline",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-extrabold text-ge-navy">
          {p.name}
        </span>
        {p.holdings_source === "PDF_FALLBACK" && (
          <span
            title="운용역 소스 검증 실패 — 마지막 PDF 기준"
            className="shrink-0 rounded-full border border-amber-400/40 bg-amber-400/[0.12] px-2 py-0.5 text-[10px] font-semibold text-amber-700"
          >
            PDF 폴백
          </span>
        )}
      </div>

      {/* ① 전일확정 (전전일→전일 종가) */}
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold text-ink-muted">
          ① 전일확정
        </span>
        <span
          className={cn(
            "text-[17px] font-extrabold tabular-nums",
            signTextClass(ret1),
          )}
        >
          {signedPct(ret1)}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-[10px] text-ink-faint">
        <span>{basis ? `${basis} 종가기준` : "기준일 대기"}</span>
        {stale1 && (
          <span className="rounded-full border border-amber-400/40 bg-amber-400/[0.12] px-1.5 py-0.5 font-semibold text-amber-700">
            미갱신
          </span>
        )}
      </div>

      {/* ② 실시간 (전일종가→최근체결가) */}
      <div className="mt-0.5 flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold text-ink-muted">
          ② 실시간
        </span>
        <span
          className={cn(
            "text-[26px] font-extrabold leading-none tabular-nums",
            signTextClass(ret2),
          )}
        >
          <RollingText text={signedPct(ret2)} />
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-muted">
        <span className="tabular-nums">
          종목 {p.n_matched}/{p.n_total}
        </span>
        <span className="tabular-nums">
          반영 {p.matched_weight_pct.toFixed(1)}%
        </span>
      </div>
    </button>
  );
}

/* ── ② 분류별 비중·기여도 트리 (구 뷰어 wrapCategoryTreeHtml 이식) ────── */

interface CatMid {
  name: string;
  weight: number;
  contrib: number;
  x: number;
}
interface Cat1 {
  name: string;
  weight: number;
  contrib: number;
  mids: CatMid[];
  x: number;
}

// 보유종목 → 대분류→중분류 집계 (비중 합 + 기여도 합, 비중 내림차순).
function aggregateCategories(p: WrapPortfolio): Cat1[] {
  const byCat1 = new Map<string, Cat1>();
  for (const h of p.holdings ?? []) {
    const c1 = (h.cat1 || "").trim() || "미분류";
    const c2 = (h.cat2 || "").trim() || "기타";
    const w = typeof h.weight_pct === "number" ? h.weight_pct : 0;
    const c = typeof h.contribution_pct === "number" ? h.contribution_pct : 0;
    let g = byCat1.get(c1);
    if (!g) {
      g = { name: c1, weight: 0, contrib: 0, mids: [], x: 0 };
      byCat1.set(c1, g);
    }
    g.weight += w;
    g.contrib += c;
    let m = g.mids.find((mm) => mm.name === c2);
    if (!m) {
      m = { name: c2, weight: 0, contrib: 0, x: 0 };
      g.mids.push(m);
    }
    m.weight += w;
    m.contrib += c;
  }
  const list = [...byCat1.values()].sort((a, b) => b.weight - a.weight);
  for (const g of list) g.mids.sort((a, b) => b.weight - a.weight);
  return list;
}

const NODE_W = 122;
const NODE_H = 34;
const LEAF_GAP = NODE_W + 14;
const SIDE_PAD = NODE_W / 2 + 8;
const ROOT_Y = 8;
const C1_Y = 84;
const C2_Y = 160;

function CategoryTree({ p }: { p: WrapPortfolio }) {
  const cats = useMemo(() => aggregateCategories(p), [p]);
  if (!cats.length) {
    return <p className="py-6 text-sm text-ink-muted">분류 데이터가 없습니다.</p>;
  }

  const leaves = cats.flatMap((g) => g.mids);
  const W = SIDE_PAD * 2 + Math.max(0, leaves.length - 1) * LEAF_GAP;
  const H = C2_Y + NODE_H + 12;

  let c1max = 0;
  let c2max = 0;
  for (const g of cats) {
    if (g.weight > c1max) c1max = g.weight;
    for (const m of g.mids) if (m.weight > c2max) c2max = m.weight;
  }

  // 잎(중분류) x 슬롯 → 대분류 x = 자식들의 중앙, 루트 x = 대분류들의 중앙.
  let idx = 0;
  for (const g of cats) {
    let first: number | null = null;
    let last = 0;
    for (const m of g.mids) {
      m.x = SIDE_PAD + idx * LEAF_GAP;
      if (first === null) first = m.x;
      last = m.x;
      idx++;
    }
    g.x = first === null ? SIDE_PAD + idx * LEAF_GAP : (first + last) / 2;
  }
  const rootX = cats.length
    ? (cats[0].x + cats[cats.length - 1].x) / 2
    : W / 2;

  const sign = (v: number) => (v >= 0 ? POS : NEG);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMinYMin meet"
        style={{
          width: "100%",
          maxWidth: `${W}px`,
          height: "auto",
          display: "block",
          margin: "0 auto",
        }}
      >
        {/* 링크: 루트→대분류 / 대분류→중분류 (굵기=비중 비례, 색=기여도 부호) */}
        {cats.map((g) => (
          <TreeLink
            key={`l1-${g.name}`}
            x1={rootX}
            y1={ROOT_Y + NODE_H}
            x2={g.x}
            y2={C1_Y}
            sw={1 + (g.weight / (c1max || 1)) * 5}
            color={sign(g.contrib)}
          />
        ))}
        {cats.flatMap((g) =>
          g.mids.map((m) => (
            <TreeLink
              key={`l2-${g.name}-${m.name}`}
              x1={g.x}
              y1={C1_Y + NODE_H}
              x2={m.x}
              y2={C2_Y}
              sw={1 + (m.weight / (c2max || 1)) * 4}
              color={sign(m.contrib)}
            />
          )),
        )}
        {/* 노드: 루트(수익률) / 대분류 / 중분류 */}
        <TreeNode
          cx={rootX}
          top={ROOT_Y}
          label={p.name}
          color={sign(p.return_pct)}
          sub={<tspan fill={sign(p.return_pct)}>{signedPct(p.return_pct)}</tspan>}
        />
        {cats.map((g) => (
          <TreeNode
            key={`n1-${g.name}`}
            cx={g.x}
            top={C1_Y}
            label={g.name}
            color={sign(g.contrib)}
            wfrac={g.weight / (c1max || 1)}
            sub={
              <>
                <tspan fill="#8a94a6">{fmtNum(g.weight, 1, 1)}% · </tspan>
                <tspan fill={sign(g.contrib)}>{signedPct(g.contrib)}</tspan>
              </>
            }
          />
        ))}
        {cats.flatMap((g) =>
          g.mids.map((m) => (
            <TreeNode
              key={`n2-${g.name}-${m.name}`}
              cx={m.x}
              top={C2_Y}
              label={m.name}
              color={sign(m.contrib)}
              wfrac={m.weight / (c2max || 1)}
              sub={
                <>
                  <tspan fill="#8a94a6">{fmtNum(m.weight, 1, 1)}% · </tspan>
                  <tspan fill={sign(m.contrib)}>{signedPct(m.contrib)}</tspan>
                </>
              }
            />
          )),
        )}
      </svg>
    </div>
  );
}

function TreeLink({
  x1,
  y1,
  x2,
  y2,
  sw,
  color,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  sw: number;
  color: string;
}) {
  const my = (y1 + y2) / 2;
  const d = `M${x1.toFixed(1)},${y1.toFixed(1)} C${x1.toFixed(1)},${my.toFixed(
    1,
  )} ${x2.toFixed(1)},${my.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeOpacity={0.45}
      strokeWidth={sw}
      strokeLinecap="round"
    />
  );
}

function TreeNode({
  cx,
  top,
  label,
  sub,
  color,
  wfrac,
}: {
  cx: number;
  top: number;
  label: string;
  sub: React.ReactNode;
  color: string;
  wfrac?: number;
}) {
  const x = cx - NODE_W / 2;
  const bw = wfrac != null ? Math.max(3, (NODE_W - 16) * wfrac) : null;
  return (
    <g>
      <rect
        x={x.toFixed(1)}
        y={top}
        width={NODE_W}
        height={NODE_H}
        rx={8}
        fill="#ffffff"
        stroke={color}
        strokeOpacity={0.45}
        strokeWidth={1.4}
      />
      {bw != null && (
        <rect
          x={(cx - bw / 2).toFixed(1)}
          y={top + NODE_H - 5}
          width={bw.toFixed(1)}
          height={2.5}
          rx={1.25}
          fill={color}
          fillOpacity={0.8}
        />
      )}
      <text
        textAnchor="middle"
        x={cx.toFixed(1)}
        y={top + 14}
        fontSize={10.5}
        fontWeight={700}
        fill="#243b5e"
      >
        {label.length > 14 ? `${label.slice(0, 13)}…` : label}
      </text>
      <text
        textAnchor="middle"
        x={cx.toFixed(1)}
        y={top + 26}
        fontSize={9.5}
        fontWeight={600}
      >
        {sub}
      </text>
    </g>
  );
}

/* ── ③ 구성종목 기여도 테이블 ────────────────────────────────────────── */

const WRAP_COLS = [
  { key: "ticker", label: "TICKER", num: false },
  { key: "name", label: "이름", num: false },
  { key: "cat1", label: "대분류", num: false },
  { key: "cat2", label: "중분류", num: false },
  { key: "cat3", label: "소분류", num: false },
  { key: "currency", label: "기준통화", num: false },
  { key: "prev_close", label: "전일종가", num: true },
  { key: "livePrice", label: "현재가", num: true },
  { key: "return_pct", label: "수익률", num: true },
  { key: "fx_return_pct", label: "환 수익률", num: true },
  { key: "weight_pct", label: "비중", num: true },
  { key: "contribution_pct", label: "기여(수익률×비중)", num: true },
] as const;
type WrapSortKey = (typeof WRAP_COLS)[number]["key"];

// 데이터 상태등 — 최신(정상)이면 초록불, 60초 이상 지연이면 회색.
function StatusLight({ ok }: { ok: boolean }) {
  return (
    <span
      className="flex items-center gap-1.5 text-[11px] font-semibold"
      title={ok ? "데이터 정상" : "데이터 지연 — 60초 이상 미갱신"}
    >
      <span
        className={cn(
          "inline-block h-2.5 w-2.5 rounded-full",
          ok
            ? "bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.18)]"
            : "bg-slate-300",
        )}
      />
      <span className={ok ? "text-emerald-600" : "text-ink-faint"}>
        {ok ? "정상" : "지연"}
      </span>
    </span>
  );
}

function HoldingsTable({ p }: { p: WrapPortfolio }) {
  const [sortKey, setSortKey] = useState<WrapSortKey>("weight_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const rows = useMemo(() => {
    const col = WRAP_COLS.find((c) => c.key === sortKey);
    const isNum = col?.num ?? false;
    const dir = sortDir === "asc" ? 1 : -1;
    const arr = [...(p.holdings ?? [])];
    // 원화현금은 정렬 상태와 무관하게 항상 최상단 고정 (구 뷰어는 하단이었음 — 요구 변경).
    arr.sort((a, b) => {
      const ca = isCashHolding(a);
      const cb = isCashHolding(b);
      if (ca && !cb) return -1;
      if (!ca && cb) return 1;
      if (ca && cb) return 0;
      const av = a[sortKey];
      const bv = b[sortKey];
      if (isNum) {
        const an = typeof av === "number" ? av : null;
        const bn = typeof bv === "number" ? bv : null;
        if (an == null && bn == null) return 0;
        if (an == null) return 1; // 미커버는 항상 아래
        if (bn == null) return -1;
        return (an - bn) * dir;
      }
      const as = av == null ? "" : String(av);
      const bs = bv == null ? "" : String(bv);
      if (as === bs) return 0;
      if (as === "") return 1;
      if (bs === "") return -1;
      return as.localeCompare(bs, "ko") * dir;
    });
    return arr;
  }, [p, sortKey, sortDir]);

  const toggleSort = (key: WrapSortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(WRAP_COLS.find((c) => c.key === key)?.num ? "desc" : "asc");
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-[12.5px]">
        <thead className="bg-ge-th">
          <tr>
            {WRAP_COLS.map((c) => (
              <th
                key={c.key}
                onClick={() => toggleSort(c.key)}
                title="클릭하여 정렬"
                className={cn(
                  "cursor-pointer select-none whitespace-nowrap px-2 py-2 text-[11px] font-bold uppercase tracking-wide text-ink-secondary",
                  c.num ? "text-right" : "text-left",
                  sortKey === c.key && "text-ge-point",
                )}
              >
                {c.label}
                {sortKey === c.key && (
                  <span className="ml-0.5">{sortDir === "asc" ? "▲" : "▼"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((h, i) => (
            <HoldingRow key={`${h.ticker}-${i}`} h={h} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 기준통화 pill — 통화별 옅은 색 구분 (KRW 는 무채색).
const CURRENCY_TEXT: Record<string, string> = {
  KRW: "text-ink-faint",
  USD: "text-ge-point",
  JPY: "text-amber-600",
  TWD: "text-emerald-600",
  HKD: "text-rose-500",
  CNY: "text-rose-500",
};

function HoldingRow({ h }: { h: WrapHolding }) {
  return (
    <tr
      className={cn(
        "border-t border-hairline/70",
        !h.matched && "opacity-45",
      )}
    >
      <td
        className="whitespace-nowrap px-2 py-1.5 font-bold tabular-nums text-ge-navy"
        title={h.name || ""}
      >
        {h.ticker || EMDASH}
      </td>
      <td className="px-2 py-1.5 text-ink-secondary" title={h.name || ""}>
        <span className="block max-w-[160px] truncate">{h.name || ""}</span>
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-ink-secondary">
        {h.cat1 || ""}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-ink-secondary">
        {h.cat2 || ""}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-ink-secondary">
        {h.cat3 || ""}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5">
        {h.currency ? (
          <span
            className={cn(
              "rounded bg-canvas-soft px-1.5 py-0.5 text-[10.5px] font-bold",
              CURRENCY_TEXT[h.currency] ?? "text-ink-secondary",
            )}
          >
            {h.currency}
          </span>
        ) : (
          EMDASH
        )}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">
        {h.prev_close == null ? EMDASH : fmtNum(h.prev_close, 2, 2)}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">
        <RollingText
          text={h.livePrice == null ? EMDASH : fmtNum(h.livePrice, 2, 2)}
        />
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-2 py-1.5 text-right font-semibold tabular-nums",
          signTextClass(h.return_pct),
        )}
      >
        {h.return_pct == null ? (
          <span className="rounded bg-canvas-soft px-1.5 py-0.5 text-[10px] font-semibold text-ink-faint">
            미커버
          </span>
        ) : (
          signedPct(h.return_pct)
        )}
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-2 py-1.5 text-right font-semibold tabular-nums",
          h.fx_return_pct == null ? "text-ink-faint" : signTextClass(h.fx_return_pct),
        )}
        title="해당 통화의 원화 환율 전일 대비 등락률 (KRW 종목은 해당 없음)"
      >
        {h.fx_return_pct == null ? EMDASH : signedPct(h.fx_return_pct)}
      </td>
      <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">
        {fmtNum(h.weight_pct, 2, 2)}
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-2 py-1.5 text-right font-semibold tabular-nums",
          signTextClass(h.contribution_pct),
        )}
      >
        {signedNum(h.contribution_pct)}
      </td>
    </tr>
  );
}
