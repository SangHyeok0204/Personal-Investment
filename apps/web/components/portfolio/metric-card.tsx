import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

type Tone = "default" | "positive" | "negative" | "muted";

const TONE_TEXT: Record<Tone, string> = {
  default: "text-ink",
  positive: "text-status-success",
  negative: "text-status-failed",
  muted: "text-ink-muted",
};

const SUB_TONE_TEXT: Record<Tone, string> = {
  default: "text-ink-faint",
  positive: "text-status-success",
  negative: "text-status-failed",
  muted: "text-ink-faint",
};

export function MetricCard({
  label,
  value,
  sub,
  tone = "default",
  loading = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  loading?: boolean;
}) {
  return (
    <div className="rounded-md border border-hairline bg-canvas px-4 py-3.5">
      <span className="eyebrow">{label}</span>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-24" />
      ) : (
        <div
          className={cn(
            "mt-1.5 text-xl font-semibold tabular-nums tracking-tight",
            TONE_TEXT[tone],
          )}
        >
          {value}
        </div>
      )}
      {sub != null && !loading && (
        <div className={cn("mt-0.5 text-xs tabular-nums", SUB_TONE_TEXT[tone])}>
          {sub}
        </div>
      )}
    </div>
  );
}
