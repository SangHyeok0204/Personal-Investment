"use client";

import type { SdHealthChannel, SdStats } from "@/lib/stock-discussion";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수집 채널 점: 오류>0 → 실패색, last_ok 없음 → 대기색, 그 외 정상색(§3.1-①).
function channelTone(c: SdHealthChannel | undefined): {
  dot: string;
  text: string;
} {
  if (!c || c.last_ok == null) return { dot: "bg-ink-faint", text: "대기" };
  if (c.consecutive_errors > 0)
    return { dot: "bg-status-failed", text: "오류" };
  return { dot: "bg-status-success", text: "정상" };
}

function ChannelRow({
  name,
  channel,
}: {
  name: string;
  channel: SdHealthChannel | undefined;
}) {
  const tone = channelTone(channel);
  return (
    <div className="flex items-center justify-between gap-2 py-1">
      <div className="flex items-center gap-2">
        <span className={cn("h-2 w-2 shrink-0 rounded-full", tone.dot)} />
        <span className="text-[12.5px] font-semibold text-ink">{name}</span>
      </div>
      <span className="text-[11px] text-ink-faint">
        {channel?.last_ok ? formatRelativeTime(channel.last_ok) : tone.text}
      </span>
    </div>
  );
}

export function HealthPanel({ stats }: { stats: SdStats | undefined }) {
  const h = stats?.health;
  return (
    <section className="rounded-xl border border-hairline bg-canvas p-4 shadow-card">
      <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-muted">
        수집 상태
      </div>
      <ChannelRow name="네이버" channel={h?.naver} />
      <ChannelRow name="토스증권" channel={h?.toss} />

      <div className="mt-3 space-y-1 border-t border-hairline pt-3 text-[11.5px] text-ink-muted">
        <div className="flex items-center justify-between">
          <span>감성 라벨</span>
          <span className="font-semibold tabular-nums text-ink">
            {(h?.sentiment.labeled_total ?? 0).toLocaleString("ko-KR")}건
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>감성 비용</span>
          <span className="font-semibold tabular-nums text-ink">
            ${(h?.sentiment.cost_usd_total ?? 0).toFixed(4)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>스파이 라벨</span>
          <span className="font-semibold tabular-nums text-ink">
            {(h?.spy.labels_total ?? 0).toLocaleString("ko-KR")}개
          </span>
        </div>
      </div>
    </section>
  );
}
