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

// 계정 items[] 에서 게이지에 쓸 항목을 라벨 키워드로 골라낸다.
// Claude: "현재 세션" / "모든 모델",  GPT(Codex): "5시간 사용 한도" / "주간 사용 한도".
function pickMeter(items: AiUsageMeter[], keywords: string[]): AiUsageMeter | null {
  return items.find((it) => keywords.some((k) => it.label.includes(k))) ?? null;
}

export default function AiTokenUsagePage() {
  const usage = useQuery({
    queryKey: ["aiTokenUsage"],
    queryFn: getAiTokenUsage,
    refetchInterval: 60000,
  });

  const data = usage.data;

  return (
    <>
      <Topbar
        title="AI Token Usage"
        subtitle="기타 · Claude / GPT 계정별 사용량 한도"
      />
      <PageContainer>
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
          <div className="grid grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-56 w-full rounded-xl" />
            ))}
          </div>
        ) : usage.isError ? (
          <p className="text-sm text-ink-muted">
            API가 응답하지 않아 사용량 데이터를 표시할 수 없습니다.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {(data?.claude ?? []).map((a) => (
              <UsageCard key={`c-${a.account_num}`} provider="Claude" account={a} />
            ))}
            {(data?.codex ?? []).map((a) => (
              <UsageCard key={`g-${a.account_num}`} provider="GPT" account={a} />
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
  provider: "Claude" | "GPT";
  account: AiUsageAccount;
}) {
  const current = pickMeter(account.items, ["현재", "5시간"]);
  const weekly = pickMeter(account.items, ["모든", "주간"]);

  return (
    <div className="overflow-hidden rounded-xl border border-hairline bg-canvas">
      {/* GE hero-card 시그니처: 6px 포인트블루 상단 바 */}
      <div className="h-1.5 bg-ge-point" />
      <div className="px-5 pb-5 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[19px] font-extrabold tracking-tight text-ge-point">
              {provider} · account{account.account_num}
            </div>
            <div className="mt-0.5 truncate text-[11.5px] font-semibold text-ink-faint">
              {account.email ?? "—"}
              {account.plan ? ` · ${account.plan}` : ""}
            </div>
          </div>
          <FreshnessBadge account={account} />
        </div>

        <div className="mt-4 flex items-start justify-around gap-2">
          <Gauge meter={current} label="current" muted={account.stale} />
          <Gauge meter={weekly} label="weekly" muted={account.stale} />
        </div>
      </div>
    </div>
  );
}

function gaugeColor(pct: number): string {
  if (pct >= 90) return "#C0392B";
  if (pct >= 70) return "#D9932B";
  return "#4A7AB5";
}

function Gauge({
  meter,
  label,
  muted,
}: {
  meter: AiUsageMeter | null;
  label: string;
  muted?: boolean;
}) {
  const pct = meter ? Math.min(100, Math.max(0, meter.pct)) : null;
  const r = 34;
  const circ = 2 * Math.PI * r;
  const dash = pct != null ? (circ * pct) / 100 : 0;
  const stroke = pct == null || muted ? "#B7C0CE" : gaugeColor(pct);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative h-[92px] w-[92px]">
        <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
          <circle cx="40" cy="40" r={r} fill="none" stroke="#E7F0FB" strokeWidth="8" />
          {pct != null && (
            <circle
              cx="40"
              cy="40"
              r={r}
              fill="none"
              stroke={stroke}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={`${dash} ${circ}`}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span
            className="text-[23px] font-extrabold tabular-nums"
            style={{ color: stroke }}
          >
            {pct != null ? Math.round(pct) : "—"}
            {pct != null && <span className="text-[13px] font-bold"> %</span>}
          </span>
        </div>
      </div>
      <span className="text-[11px] font-bold uppercase tracking-wide text-ink-muted">
        {label}
      </span>
      {meter?.subtitle && (
        <span
          className="max-w-[104px] truncate text-[10px] text-ink-faint"
          title={meter.subtitle}
        >
          {meter.subtitle}
        </span>
      )}
    </div>
  );
}

function FreshnessBadge({ account }: { account: AiUsageAccount }) {
  if (!account.captured_at) {
    return (
      <span className="inline-flex shrink-0 items-center rounded-full border border-hairline bg-canvas-soft px-2 py-0.5 text-[11px] font-medium text-ink-faint">
        데이터 없음
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
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
