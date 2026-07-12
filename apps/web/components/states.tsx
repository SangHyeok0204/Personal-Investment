import { AlertCircle } from "lucide-react";
import { ApiError } from "@/lib/api";

export function ApiErrorBanner({ error }: { error: unknown }) {
  const unreachable =
    error instanceof ApiError && error.code === "NETWORK_ERROR";
  const message =
    error instanceof ApiError ? error.message : "Something went wrong.";

  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-status-failed/30 bg-status-failed/[0.06] px-4 py-3 text-sm text-status-failed">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
      <div>
        <div className="font-medium">
          {unreachable ? "API unreachable" : message}
        </div>
        {unreachable && (
          <div className="mt-0.5 text-status-failed/80">
            Could not reach the API server. Make sure it is running and
            reachable.
          </div>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-hairline bg-canvas-soft px-6 py-10 text-center text-sm text-ink-muted">
      {message}
    </div>
  );
}
