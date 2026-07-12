import type { AssetClass, AssetClassBreakdown } from "@/lib/api";
import { formatKrwCompact } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// Fixed order and legend — all five classes always render, zeros included
// (portfolio-detail-spec §3).
export const ASSET_CLASS_ORDER: AssetClass[] = [
  "STOCK",
  "BOND",
  "DERIVATIVE",
  "OTHER",
  "CASH",
];

export const ASSET_CLASS_META: Record<
  AssetClass,
  { label: string; color: string }
> = {
  STOCK: { label: "주식", color: "#2f78ed" },
  BOND: { label: "채권", color: "#1eb4cc" },
  DERIVATIVE: { label: "파생", color: "#a78bfa" },
  OTHER: { label: "기타", color: "#94a3b8" },
  CASH: { label: "현금", color: "#f3bd55" },
};

/**
 * Slice angles are computed from `value_krw`, never `weight_pct`: weight_pct is
 * rounded to 1dp for display and the five values sum to 99.9–100.1, which would
 * leave a visible sliver gap (or an overlap) in the ring. weight_pct is legend
 * text only.
 */
function conicGradient(slices: AssetClassBreakdown[]): string {
  const visible = slices.filter((slice) => slice.value_krw > 0);
  const total = visible.reduce((sum, slice) => sum + slice.value_krw, 0);
  if (total <= 0) return "conic-gradient(#e2e8f0 0 100%)";

  let cursor = 0;
  const stops = visible.map((slice, index) => {
    const start = cursor;
    // Close the last slice at exactly 100% so float error never leaves a seam.
    const end =
      index === visible.length - 1
        ? 100
        : cursor + (slice.value_krw / total) * 100;
    cursor = end;
    return `${ASSET_CLASS_META[slice.asset_class].color} ${start}% ${end}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

export function AllocationDonut({
  breakdown,
  totalAssetsKrw,
  loading,
}: {
  breakdown: AssetClassBreakdown[];
  totalAssetsKrw: number | undefined;
  loading: boolean;
}) {
  const byClass = new Map(breakdown.map((slice) => [slice.asset_class, slice]));

  return (
    <Card className="overflow-hidden">
      <div className="px-5 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">
          자산 배분
        </h2>
      </div>

      <div className="flex items-center gap-5 px-5 pb-5">
        {loading ? (
          <Skeleton className="h-32 w-32 shrink-0 rounded-full" />
        ) : (
          <div
            className="relative h-32 w-32 shrink-0 rounded-full"
            style={{ background: conicGradient(breakdown) }}
          >
            <div className="absolute inset-[22px] flex flex-col items-center justify-center rounded-full bg-white text-center">
              <span className="text-[10px] text-slate-400">총자산</span>
              <span className="text-[13px] font-semibold tabular-nums text-slate-800">
                {formatKrwCompact(totalAssetsKrw)}
              </span>
            </div>
          </div>
        )}

        <div className="min-w-0 flex-1 space-y-1.5">
          {ASSET_CLASS_ORDER.map((assetClass) => {
            const slice = byClass.get(assetClass);
            return (
              <div
                key={assetClass}
                className="flex items-center justify-between gap-2 text-[11px]"
              >
                <span className="flex items-center gap-1.5 text-slate-500">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: ASSET_CLASS_META[assetClass].color }}
                  />
                  {ASSET_CLASS_META[assetClass].label}
                </span>
                <span className="flex items-center gap-2.5">
                  <span className="tabular-nums text-slate-400">
                    {loading ? "—" : formatKrwCompact(slice?.value_krw ?? 0)}
                  </span>
                  <span className="w-11 text-right font-medium tabular-nums text-slate-700">
                    {loading ? "—" : `${(slice?.weight_pct ?? 0).toFixed(1)}%`}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
