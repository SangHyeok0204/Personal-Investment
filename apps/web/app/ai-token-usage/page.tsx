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

// GPT(Codex) 는 account1 만 구독 유지 — 2·3 은 해제됨(2026-07-21). Claude 3 + GPT 1 = 4장.
const GPT_ACTIVE_ACCOUNT = 1;

// 세션(단기) 한도 = 카드의 hero. Claude "현재 세션" / GPT "5시간 사용 한도".
const SESSION_KEYWORDS = ["현재", "5시간"];

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

function pickSession(items: AiUsageMeter[]): AiUsageMeter | null {
  return (
    items.find((it) => SESSION_KEYWORDS.some((k) => it.label.includes(k))) ?? null
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

  // 한 줄 4장: Claude 전 계정 + GPT account1.
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
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-72 w-full rounded-2xl" />
            ))}
          </div>
        ) : usage.isError ? (
          <p className="text-sm text-ink-muted">
            API가 응답하지 않아 사용량을 표시할 수 없습니다.
          </p>
        ) : cards.length === 0 ? (
          <p className="text-sm text-ink-muted">표시할 계정이 없습니다.</p>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
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
  const session = pickSession(account.items);
  const rest = account.items.filter((it) => it !== session);
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

        {/* Hero: 세션 링 + 리셋 시계 */}
        <SessionRing meter={session} muted={account.stale} />

        {/* 나머지 한도 — 얇은 막대 */}
        {rest.length > 0 && (
          <div className="mt-auto flex flex-col gap-2 border-t border-hairline pt-3.5">
            {rest.map((m) => (
              <MeterBar key={m.label} meter={m} muted={account.stale} />
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
          {meter?.label ?? "세션 한도 없음"}
        </div>
        {meter?.subtitle && (
          <div className="mt-0.5 text-[11px] text-ink-faint">
            {meter.subtitle}
          </div>
        )}
      </div>
    </div>
  );
}

function MeterBar({ meter, muted }: { meter: AiUsageMeter; muted?: boolean }) {
  const pct = Math.min(100, Math.max(0, meter.pct));
  const color = muted ? "#B7C0CE" : severityColor(pct);
  return (
    <div className="flex items-center gap-2.5" title={meter.subtitle ?? undefined}>
      <span className="w-[4.5rem] shrink-0 truncate text-[11px] font-medium text-ink-muted">
        {meter.label}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ge-blue-bg">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span
        className="w-8 shrink-0 text-right text-[11px] font-bold tabular-nums"
        style={{ color }}
      >
        {Math.round(pct)}%
      </span>
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
