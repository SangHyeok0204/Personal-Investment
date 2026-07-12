"use client";

import { useQuery } from "@tanstack/react-query";
import { getPortfolioOverview } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/format";

/** Topbar status light (portfolio-detail-spec §1). Shares the overview query key
 * with the page, so this adds no extra request. */
export function SyncStatusLight() {
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });

  const data = overview.data;
  const syncStatus = data?.sync_status;
  const connection = data?.connection ?? null;
  const lastSynced = data?.last_synced_at ?? null;

  let dot = "bg-slate-300";
  let text = "text-slate-500";
  let label = "동기화 이력 없음";
  let detail: string | null = null;
  let pulse = false;

  if (overview.isLoading) {
    label = "확인 중";
  } else if (syncStatus === "RUNNING") {
    dot = "bg-blue-500";
    text = "text-blue-600";
    label = "동기화 중";
    pulse = true;
  } else if (syncStatus === "FAILED" || connection?.status === "ERROR") {
    dot = "bg-rose-500";
    text = "text-rose-600";
    label = "오류";
    detail = connection?.last_error ?? "최근 동기화가 실패했습니다.";
  } else if (syncStatus === "SUCCESS" && connection?.status === "CONNECTED") {
    dot = "bg-emerald-500";
    text = "text-emerald-600";
    label = "연결됨";
    detail = lastSynced ? `마지막 동기화 ${formatRelativeTime(lastSynced)}` : null;
  } else if (syncStatus === "SUCCESS") {
    label = "확인 필요";
    detail = lastSynced ? `마지막 동기화 ${formatRelativeTime(lastSynced)}` : null;
  }

  return (
    <div className="flex min-w-0 items-center gap-2 border-l border-slate-200 pl-5">
      <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs font-medium">
        <span
          className={cn("h-2 w-2 shrink-0 rounded-full", dot, pulse && "animate-pulse")}
        />
        <span className={text}>{label}</span>
      </span>
      {detail && (
        <span
          className="min-w-0 truncate text-[11px] text-slate-400"
          title={detail}
        >
          {detail}
        </span>
      )}
    </div>
  );
}
