"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { getJob, type JobLog, type JobStatus } from "@/lib/api";
import { formatDateTime, prettyJson } from "@/lib/format";
import { StatusBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";

function isActive(status: JobStatus | undefined): boolean {
  return status === "PENDING" || status === "RUNNING";
}

const LOG_LEVEL_COLOR: Record<JobLog["level"], string> = {
  INFO: "text-ink-faint",
  WARNING: "text-status-failed/70",
  ERROR: "text-status-failed",
};

export function JobDetailDrawer({
  jobId,
  onClose,
}: {
  jobId: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/20"
        onClick={onClose}
        aria-hidden
      />
      <div className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-hairline bg-canvas shadow-panel">
        <JobDetailBody jobId={jobId} onClose={onClose} />
      </div>
    </div>
  );
}

function JobDetailBody({
  jobId,
  onClose,
}: {
  jobId: string;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (query) =>
      isActive(query.state.data?.status) ? 2000 : false,
  });

  return (
    <>
      <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="text-[15px] font-semibold tracking-tight text-ink">
            {data ? data.job_type : "Job"}
          </span>
          {data && <StatusBadge status={data.status} />}
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-ink-faint transition-colors hover:bg-black/[0.04] hover:text-ink"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        {isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}

        {isError && <ApiErrorBanner error={error} />}

        {data && (
          <div className="space-y-6">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-ink-muted">ID</dt>
              <dd className="font-mono text-xs text-ink-secondary">
                {data.id}
              </dd>
              <dt className="text-ink-muted">Created</dt>
              <dd className="text-ink-secondary">
                {formatDateTime(data.created_at)}
              </dd>
              <dt className="text-ink-muted">Started</dt>
              <dd className="text-ink-secondary">
                {formatDateTime(data.started_at)}
              </dd>
              <dt className="text-ink-muted">Finished</dt>
              <dd className="text-ink-secondary">
                {formatDateTime(data.finished_at)}
              </dd>
            </dl>

            {data.status === "FAILED" && data.error_message && (
              <Section label="Error">
                <div className="rounded-md border border-status-failed/30 bg-status-failed/[0.06] px-3 py-2 text-sm text-status-failed">
                  {data.error_message}
                </div>
              </Section>
            )}

            <Section label="Payload">
              <JsonBlock value={data.payload} />
            </Section>

            <Section label="Result">
              <JsonBlock value={data.result} />
            </Section>

            <Section label="Logs">
              {data.logs.length === 0 ? (
                <p className="text-sm text-ink-faint">No logs yet.</p>
              ) : (
                <ol className="space-y-3">
                  {data.logs.map((log) => (
                    <li key={log.id} className="flex gap-3 text-sm">
                      <span
                        className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                          log.level === "ERROR"
                            ? "bg-status-failed"
                            : log.level === "WARNING"
                              ? "bg-status-failed/60"
                              : "bg-ink-faint"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-xs font-semibold uppercase tracking-wide ${LOG_LEVEL_COLOR[log.level]}`}
                          >
                            {log.level}
                          </span>
                          {log.step && (
                            <span className="text-xs text-ink-faint">
                              {log.step}
                            </span>
                          )}
                          <span className="ml-auto shrink-0 text-xs text-ink-faint">
                            {formatDateTime(log.created_at)}
                          </span>
                        </div>
                        <p className="mt-0.5 break-words text-ink-secondary">
                          {log.message}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Section>
          </div>
        )}
      </div>
    </>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="eyebrow mb-2">{label}</div>
      {children}
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  if (value == null) {
    return <p className="text-sm text-ink-faint">—</p>;
  }
  return (
    <pre className="overflow-x-auto rounded-md border border-hairline bg-canvas-soft px-3 py-2 font-mono text-xs leading-relaxed text-ink-secondary">
      {prettyJson(value)}
    </pre>
  );
}
