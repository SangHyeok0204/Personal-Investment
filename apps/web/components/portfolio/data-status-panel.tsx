import type { ReactNode } from "react";
import type { SyncStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/format";

export function DataStatusPanel({
  lastSyncedAt,
  syncStatus,
  lastError,
}: {
  lastSyncedAt: string | null;
  syncStatus: SyncStatus;
  lastError: string | null | undefined;
}) {
  return (
    <Card>
      <CardHeader>
        <span className="eyebrow">데이터 상태</span>
        <CardTitle>동기화 정보</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <Row label="마지막 동기화">
          <span className="text-sm tabular-nums text-ink-secondary">
            {formatRelativeTime(lastSyncedAt)}
          </span>
        </Row>
        <Row label="동기화 상태">
          {syncStatus === "NEVER_SYNCED" ? (
            <span className="text-sm text-ink-muted">이력 없음</span>
          ) : (
            <StatusBadge status={syncStatus} />
          )}
        </Row>
        <Row label="최근 오류">
          <span
            className={cn(
              "max-w-[60%] truncate text-sm",
              lastError ? "text-status-failed" : "text-ink-muted",
            )}
            title={lastError ?? undefined}
          >
            {lastError || "없음"}
          </span>
        </Row>
        <Row label="데이터 출처">
          <span className="text-sm text-ink-secondary">키움 REST API</span>
        </Row>
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-ink-muted">{label}</span>
      {children}
    </div>
  );
}
