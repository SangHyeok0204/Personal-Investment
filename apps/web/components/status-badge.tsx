import { cn } from "@/lib/utils";
import type { JobStatus } from "@/lib/api";

const STATUS: Record<
  JobStatus,
  { label: string; dot: string; text: string }
> = {
  PENDING: { label: "Pending", dot: "bg-ink-faint", text: "text-ink-muted" },
  RUNNING: {
    label: "Running",
    dot: "bg-status-running",
    text: "text-status-running",
  },
  SUCCESS: {
    label: "Success",
    dot: "bg-status-success",
    text: "text-status-success",
  },
  FAILED: {
    label: "Failed",
    dot: "bg-status-failed",
    text: "text-status-failed",
  },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const c = STATUS[status] ?? STATUS.PENDING;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          c.dot,
          status === "RUNNING" && "animate-pulse",
        )}
      />
      <span className={c.text}>{c.label}</span>
    </span>
  );
}
