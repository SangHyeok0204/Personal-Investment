"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  getAiTokenUsage,
  type AiUsageAccount,
  type AiUsageMeter,
} from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

type Provider = "Claude" | "GPT";

// GPT(Codex) 는 account1 만 구독 유지 — 2·3 은 해제됨(2026-07-21). Claude 4 + GPT 1 = 5장.
const GPT_ACTIVE_ACCOUNT = 1;

/* ── 미터 분류 ────────────────────────────────────────────────────────
   업스트림(192.168.199.120:8002)은 Claude/Codex 웹 UI 문구를 그대로 긁어와 라벨이
   공급자마다 다르고 이름도 바뀐다(Opus→Fable, 2026-07). 라벨을 그대로 쓰면 카드마다
   행 이름·개수·순서가 어긋나므로, 표시 전에 종류로 분류해 구조를 통일한다.
     session — Claude '현재 세션' / Codex '5시간 사용 한도'  → 카드 hero 링
     weekly  — Claude '모든 모델' / Codex '주간 사용 한도'   → '주간 사용량' 으로 통일
     extra   — Claude 'US$0.00 사용' (초과분 과금)          → '추가 사용량' + 금액
     model   — 그 외(Fable, GPT-5.3-Codex-Spark) 는 라벨 그대로 */
type MeterKind = "session" | "weekly" | "model" | "extra";

function meterKind(label: string): MeterKind {
  if (label.includes("현재") || label.includes("5시간")) return "session";
  if (label.includes("모든 모델") || label.includes("주간")) return "weekly";
  if (label.startsWith("US$")) return "extra";
  return "model";
}

// 종류가 정해진 행은 공급자와 무관하게 같은 이름으로 부른다.
const KIND_LABEL: Partial<Record<MeterKind, string>> = {
  weekly: "주간 사용량",
  extra: "추가 사용량",
};

function displayLabel(label: string): string {
  return KIND_LABEL[meterKind(label)] ?? label;
}

// extra 행의 값은 %가 아니라 금액이다 — 업스트림이 금액을 라벨에 넣어 보내므로
// ('US$0.00 사용') 금액만 떼어 값 슬롯에 놓는다. 형식이 바뀌면 null → % 로 폴백.
function extraAmount(label: string): string | null {
  const m = /^US\$\s*([\d,.]+)/.exec(label);
  return m ? `US$${m[1]}` : null;
}

/** 카드 하단 막대 한 줄. meter=null 은 그 계정에 해당 한도가 없는 상태. */
interface MeterRowModel {
  key: string;
  label: string;
  meter: AiUsageMeter | null;
  value: string;
  /** meter 없는 행의 설명. 있으면 subtitle 자리에 대신 쓴다. */
  note?: string;
}

// hero 를 뺀 나머지 미터를 weekly → model → extra 순으로 세운다. 업스트림 배열 순서에
// 기대지 않으므로 계정마다 행 순서가 같다.
function buildRows(
  items: AiUsageMeter[],
  provider: Provider,
  creditsEnabled: boolean | null,
): MeterRowModel[] {
  const rows: MeterRowModel[] = [];
  for (const kind of ["weekly", "model", "extra"] as const) {
    for (const m of items.filter((it) => meterKind(it.label) === kind)) {
      const pctText = `${Math.round(m.pct)}%`;
      rows.push({
        key: `${kind}:${m.label}`,
        label: displayLabel(m.label),
        meter: m,
        value: kind === "extra" ? extraAmount(m.label) ?? pctText : pctText,
      });
    }
  }
  // Claude 카드는 '추가 사용량' 행을 항상 둔다 — 없으면 카드 행 위치가 한 칸씩
  // 어긋난다. 금액을 'US$0.00' 으로 지어내지는 않는다(실제 과금이 있을 때 조용히
  // 틀린 값이 된다).
  //
  // ★행이 없는 이유는 두 가지이고, 겉으로는 똑같이 보인다:
  //   ① 그 계정의 '사용 크레딧'이 꺼져 있어 claude.ai 가 애초에 이 미터를 안 그린다
  //   ② 크레딧은 켜져 있는데 수집만 실패했다
  // 예전엔 이걸 구분할 수 없어 ①을 추측으로 단정했다. 이제 스크래퍼가 토글
  // (role=switch aria-checked)을 직접 읽어 extra_usage_enabled 로 실어주므로
  // 실측값으로 갈라 쓴다 (2026-07-30 실측: 계정1~3 = true, 계정4 = false).
  if (provider === "Claude" && !rows.some((r) => r.key.startsWith("extra:"))) {
    const [value, note] =
      creditsEnabled === false
        ? ["미설정", "사용 크레딧 꺼짐 · 한도 도달 시 중단"]
        : creditsEnabled === true
          ? ["미수집", "크레딧 켜짐 · 금액 행 수집 실패"]
          : ["—", "크레딧 설정 확인 불가"];
    rows.push({
      key: "extra:none",
      label: "추가 사용량",
      meter: null,
      value,
      note,
    });
  }
  return rows;
}

const PROVIDER_STYLE: Record<Provider, { bar: string; chip: string }> = {
  Claude: { bar: "bg-ge-point", chip: "bg-ge-blue-bg text-ge-point" },
  GPT: { bar: "bg-slate-400", chip: "bg-slate-100 text-slate-500" },
};

// 잔여 여력이 아니라 소진율(pct) 기준 심각도 색. GE 게이지 팔레트.
function severityColor(pct: number): string {
  if (pct >= 90) return "#C0392B";
  if (pct >= 70) return "#D9932B";
  return "#4A7AB5";
}

// 카드 hero(큰 링)로 세울 미터 — 세션 한도가 원칙이다. Codex account1 은 업스트림이
// 5시간 한도를 더 이상 주지 않아 링이 회색 '세션 한도 없음'으로 비어 있었으므로,
// 없으면 주간 → 첫 항목 순으로 물러난다. 링 아래 라벨이 무엇을 보여주는지 밝힌다.
function pickHero(items: AiUsageMeter[]): AiUsageMeter | null {
  return (
    items.find((it) => meterKind(it.label) === "session") ??
    items.find((it) => meterKind(it.label) === "weekly") ??
    items[0] ??
    null
  );
}

interface CardModel {
  provider: Provider;
  account: AiUsageAccount;
}

export default function AiTokenUsagePage() {
  const usage = useQuery({
    queryKey: ["aiTokenUsage"],
    queryFn: getAiTokenUsage,
    refetchInterval: 60000,
  });

  const data = usage.data;

  // 한 줄 5장: Claude 전 계정(4) + GPT account1.
  const cards: CardModel[] = [
    ...(data?.claude ?? []).map((account) => ({
      provider: "Claude" as const,
      account,
    })),
    ...(data?.codex ?? [])
      .filter((a) => a.account_num === GPT_ACTIVE_ACCOUNT)
      .map((account) => ({ provider: "GPT" as const, account })),
  ];

  return (
    <>
      <Topbar
        title="AI Token Usage"
        subtitle="기타 · Claude / GPT 계정별 사용량 한도"
        status={
          data ? (
            <span className="truncate text-[11px] text-slate-400">
              {formatRelativeTime(data.fetched_at)} 조회
            </span>
          ) : undefined
        }
      />
      <PageContainer wide>
        {usage.isError && (
          <div className="mb-4">
            <ApiErrorBanner error={usage.error} />
          </div>
        )}

        {data && !data.reachable && (
          <WarningBanner>
            모니터에 연결할 수 없습니다 ({data.monitor_base_url})
            {data.error ? ` — ${data.error}` : ""}
          </WarningBanner>
        )}

        {usage.isLoading ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-80 w-full rounded-2xl" />
            ))}
          </div>
        ) : usage.isError ? (
          <p className="text-sm text-ink-muted">
            API가 응답하지 않아 사용량을 표시할 수 없습니다.
          </p>
        ) : cards.length === 0 ? (
          <p className="text-sm text-ink-muted">표시할 계정이 없습니다.</p>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-5">
            {cards.map((c) => (
              <UsageCard
                key={`${c.provider}-${c.account.account_num}`}
                provider={c.provider}
                account={c.account}
              />
            ))}
          </div>
        )}
      </PageContainer>
    </>
  );
}

function WarningBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-amber-400/40 bg-amber-400/[0.08] px-4 py-2.5 text-sm text-amber-700">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
      <div>{children}</div>
    </div>
  );
}

function UsageCard({
  provider,
  account,
}: {
  provider: Provider;
  account: AiUsageAccount;
}) {
  const style = PROVIDER_STYLE[provider];
  const hero = pickHero(account.items);
  const rows = buildRows(
    account.items.filter((it) => it !== hero),
    provider,
    account.extra_usage_enabled,
  );
  const emailShort = account.email?.split("@")[0] ?? "—";

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-[0_2px_10px_rgba(36,59,94,0.05)]">
      <div className={cn("h-1.5 shrink-0", style.bar)} />
      <div className="flex flex-1 flex-col gap-4 px-5 pb-5 pt-4">
        {/* 헤더: 공급자 칩 + 계정 번호 · 신선도 */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <span
              className={cn(
                "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold",
                style.chip,
              )}
            >
              {provider}
            </span>
            <div className="mt-1.5 text-[19px] font-extrabold leading-none tracking-tight text-ge-navy">
              account {account.account_num}
            </div>
            <div className="mt-1 truncate text-[11.5px] font-medium text-ink-faint">
              {account.plan ? `${account.plan} · ` : ""}
              {emailShort}
            </div>
          </div>
          <FreshnessBadge account={account} />
        </div>

        {/* Hero: 대표 한도 링 + 초기화 시점 */}
        <SessionRing meter={hero} muted={account.stale} />

        {/* 나머지 한도 — 막대 + 초기화 시점 */}
        {/* mt-auto 는 쓰지 않는다 — hero 블록 높이가 카드마다 같으므로 구분선이 5장
            전부 같은 y 에 오고, 행 수가 적은 GPT 카드도 중간이 비지 않는다. */}
        {rows.length > 0 && (
          <div className="flex flex-col gap-3 border-t border-hairline pt-3.5">
            {rows.map((row) => (
              <MeterRow key={row.key} row={row} muted={account.stale} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SessionRing({
  meter,
  muted,
}: {
  meter: AiUsageMeter | null;
  muted?: boolean;
}) {
  const pct = meter ? Math.min(100, Math.max(0, meter.pct)) : null;
  const r = 32;
  const circ = 2 * Math.PI * r;
  const dash = pct != null ? (circ * pct) / 100 : 0;
  const color = pct == null || muted ? "#B7C0CE" : severityColor(pct);

  return (
    <div className="flex flex-col items-center gap-2.5 py-1">
      <div className="relative h-[128px] w-[128px]">
        <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
          <circle
            cx="40"
            cy="40"
            r={r}
            fill="none"
            stroke="#E7F0FB"
            strokeWidth="7"
          />
          {pct != null && (
            <circle
              cx="40"
              cy="40"
              r={r}
              fill="none"
              stroke={color}
              strokeWidth="7"
              strokeLinecap="round"
              strokeDasharray={`${dash} ${circ}`}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span
            className="text-[36px] font-extrabold leading-none tabular-nums"
            style={{ color }}
          >
            {pct != null ? Math.round(pct) : "—"}
            {pct != null && <span className="text-[16px] font-bold"> %</span>}
          </span>
        </div>
      </div>
      <div className="text-center">
        <div className="text-[12.5px] font-bold text-ge-navy">
          {meter ? displayLabel(meter.label) : "한도 정보 없음"}
        </div>
        <div className="mt-0.5 text-[11px] text-ink-faint">
          {meter?.subtitle ?? "초기화 시점 미수집"}
        </div>
      </div>
    </div>
  );
}

/* 한 줄 = 이름·값 / 막대 / 초기화 시점. 이름과 값을 막대 위로 올려 라벨이 잘리지 않고
   ('GPT-5.3-Codex-Spark' 가 4.5rem 칸에서 잘려 있었다), 초기화 시점을 hover 툴팁에서
   꺼내 상시 노출한다 — 주간 한도가 언제 풀리는지가 이 페이지의 핵심 정보다
   (2026-07-30 사용자 요청). 세 줄 구조가 고정이라 카드끼리 행 높이가 맞는다. */
function MeterRow({ row, muted }: { row: MeterRowModel; muted?: boolean }) {
  const { meter } = row;
  const pct = meter ? Math.min(100, Math.max(0, meter.pct)) : 0;
  const color = meter == null || muted ? "#B7C0CE" : severityColor(pct);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11.5px] font-semibold text-ink-muted">
          {row.label}
        </span>
        <span
          className="shrink-0 text-[11.5px] font-bold tabular-nums"
          style={{ color }}
        >
          {row.value}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ge-blue-bg">
        {meter != null && (
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${pct}%`, background: color }}
          />
        )}
      </div>
      <div className="truncate text-[10.5px] leading-tight text-ink-faint">
        {row.note ?? meter?.subtitle ?? "초기화 시점 미수집"}
      </div>
    </div>
  );
}

function FreshnessBadge({ account }: { account: AiUsageAccount }) {
  if (!account.captured_at) {
    return (
      <span className="inline-flex shrink-0 items-center rounded-full border border-hairline bg-canvas-soft px-2.5 py-1 text-[11px] font-medium text-ink-faint">
        데이터 없음
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium",
        account.stale
          ? "border-amber-400/40 bg-amber-400/[0.10] text-amber-700"
          : "border-status-success/30 bg-status-success/[0.08] text-status-success",
      )}
    >
      {formatRelativeTime(account.captured_at)}
      {account.stale && " · 오래됨"}
    </span>
  );
}
