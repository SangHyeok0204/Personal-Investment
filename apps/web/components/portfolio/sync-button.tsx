"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  getJob,
  getPortfolioOverview,
  syncConnection,
} from "@/lib/api";

/**
 * Topbar sync action. POSTs the sync, then polls GET /jobs/{id} every 2s until
 * the job is terminal, then invalidates the portfolio queries so the donut,
 * summary and table all refresh together.
 */
export function SyncButton() {
  const queryClient = useQueryClient();
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });
  const connection = overview.data?.connection ?? null;
  const syncStatus = overview.data?.sync_status;

  const [jobId, setJobId] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

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
  const canSync = connection != null && !running;

  return (
    <div className="flex items-center gap-2">
      {syncError && (
        <span
          className="max-w-[220px] truncate text-[11px] text-rose-600"
          title={syncError}
        >
          {syncError}
        </span>
      )}
      <button
        type="button"
        onClick={() => connection && syncMutation.mutate(connection.id)}
        disabled={!canSync}
        className="rounded-md bg-blue-600 px-3.5 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {running ? "동기화 중…" : "키움 계좌 동기화"}
      </button>
    </div>
  );
}
