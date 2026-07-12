"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ConnectionBrief, SyncStatus } from "@/lib/api";
import { ApiError, getJob, syncConnection } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/format";

export function PortfolioHeader({
  connection,
  lastSyncedAt,
  syncStatus,
  loading,
}: {
  connection: ConnectionBrief | null;
  lastSyncedAt: string | null;
  syncStatus: SyncStatus;
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  // Poll the sync job every 2s until it reaches a terminal state.
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: jobId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "SUCCESS" || status === "FAILED" ? false : 2000;
    },
  });

  const jobStatus = jobQuery.data?.status;
  const jobError = jobQuery.data?.error_message;
  useEffect(() => {
    if (jobStatus !== "SUCCESS" && jobStatus !== "FAILED") return;
    if (jobStatus === "FAILED") {
      setSyncError(jobError ?? "동기화에 실패했습니다.");
    }
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    setJobId(null);
  }, [jobStatus, jobError, queryClient]);

  const syncMutation = useMutation({
    mutationFn: (id: string) => syncConnection(id),
    onSuccess: (res) => {
      setSyncError(null);
      setJobId(res.job_id);
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (err) => {
      setSyncError(
        err instanceof ApiError ? err.message : "동기화 요청에 실패했습니다.",
      );
    },
  });

  const running =
    jobId != null || syncMutation.isPending || syncStatus === "RUNNING";
  const canSync = connection != null && !running && !loading;

  return (
    <div className="rounded-lg border border-hairline bg-canvas px-5 py-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          {loading && connection == null ? (
            <Skeleton className="h-5 w-40" />
          ) : (
            <ConnectionChip connection={connection} />
          )}
          <span className="text-xs text-ink-faint">
            {lastSyncedAt
              ? `마지막 동기화 ${formatRelativeTime(lastSyncedAt)}`
              : "동기화 이력 없음"}
          </span>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Button
            variant="primary"
            onClick={() => connection && syncMutation.mutate(connection.id)}
            disabled={!canSync}
          >
            {running ? "동기화 중…" : "키움 계좌 동기화"}
          </Button>
          {syncError && (
            <span className="max-w-xs text-right text-xs text-status-failed">
              {syncError}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function ConnectionChip({ connection }: { connection: ConnectionBrief | null }) {
  let dot = "bg-ink-faint";
  let text = "text-ink-muted";
  let label = "연결 대기 — API 키 미설정";
  let detail: string | null = null;

  if (connection == null) {
    label = "연결 정보 없음";
  } else if (!connection.credentials_configured) {
    // 키 미설정 — muted defaults above.
  } else if (connection.status === "CONNECTED") {
    dot = "bg-status-success";
    text = "text-status-success";
    label = "연결됨";
  } else if (connection.status === "ERROR") {
    dot = "bg-status-failed";
    text = "text-status-failed";
    label = "연결 오류";
    detail = connection.last_error;
  } else {
    text = "text-ink-secondary";
    label = "연결 준비됨";
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="inline-flex items-center gap-1.5 text-sm font-medium">
        <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
        <span className={text}>{label}</span>
      </span>
      {detail && (
        <span className="min-w-0 truncate text-xs text-ink-faint" title={detail}>
          {detail}
        </span>
      )}
    </div>
  );
}
