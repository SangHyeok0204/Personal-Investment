"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, Search, Wifi, WifiOff } from "lucide-react";
import type { SdStats } from "@/lib/stock-discussion";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const STALE_THRESHOLD_S = 180; // SD_PUSH_INTERVAL_HINT(60) × SD_STALE_FACTOR(3), D11
const CHANNEL_LAG_S = 30 * 60; // 수집 지연 주의 임계(30분)

function ageSeconds(iso: string | null | undefined, nowMs: number): number {
  if (!iso) return Infinity;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return Infinity;
  return (nowMs - t) / 1000;
}

interface FeedHeaderProps {
  stats: SdStats | undefined;
  newCount: number;
  onResetNew: () => void;
  onRefresh: () => void;
  isFetching: boolean;
  searchInput: string;
  onSearchInput: (v: string) => void;
}

export function FeedHeader({
  stats,
  newCount,
  onResetNew,
  onRefresh,
  isFetching,
  searchInput,
  onSearchInput,
}: FeedHeaderProps) {
  // 1s 클록 — 시계 표시 + staleness 재계산(폴링 사이 last_ingest_at 은 고정).
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const lastIngest = stats?.last_ingest_at ?? null;
  const ingestAge = ageSeconds(lastIngest, nowMs);
  const fresh = ingestAge <= STALE_THRESHOLD_S;

  // push 는 신선하나 채널 last_ok 가 오래됐으면 "수집 지연"(에러 아님, §6-3).
  const naverLag = ageSeconds(stats?.health.naver.last_ok, nowMs);
  const tossLag = ageSeconds(stats?.health.toss.last_ok, nowMs);
  const collectDelayed =
    fresh && Math.min(naverLag, tossLag) > CHANNEL_LAG_S && stats != null;

  const clock = new Date(nowMs).toLocaleTimeString("ko-KR", { hour12: false });

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
      <div className="h-2 bg-ge-point" />
      <div className="flex flex-col gap-3 p-4">
        {/* 상단: 시계·최근갱신·연결점 + 새로고침 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              suppressHydrationWarning
              className="text-[26px] font-extrabold leading-none tracking-tight tabular-nums text-ge-navy"
            >
              {clock}
            </span>
            <span className="text-[11.5px] text-ink-muted">
              최근 갱신 {formatRelativeTime(lastIngest)}
            </span>
            <ConnectionDot fresh={fresh} hasData={stats != null} />
          </div>
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-canvas-soft px-3 py-1.5 text-[12px] font-semibold text-ink-muted transition-colors hover:bg-ge-blue-bg hover:text-ge-point"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", isFetching && "animate-spin")}
              strokeWidth={2.2}
            />
            새로고침
          </button>
        </div>

        {/* 카운트 밴드 */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onResetNew}
            disabled={newCount === 0}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-bold transition-colors",
              newCount > 0
                ? "bg-ge-point text-white hover:bg-ge-navy"
                : "cursor-default bg-canvas-soft text-ink-faint",
            )}
          >
            신규 {newCount}
          </button>
          <CountPill label="오늘" value={stats?.today} />
          <CountPill label="총" value={stats?.total} />
        </div>

        {/* 검색 (디바운스는 부모에서 300ms) */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchInput(e.target.value)}
            placeholder="제목·본문·작성자 검색 (DB 전체)"
            className="w-full rounded-lg border border-hairline bg-canvas-soft py-2 pl-9 pr-3 text-[13px] text-ink outline-none transition-colors focus:border-ge-point focus:bg-canvas"
          />
        </div>

        {/* staleness 배너 (데이터는 아래 계속 렌더) */}
        {stats != null && !fresh && (
          <div className="flex items-start gap-2 rounded-lg border border-status-failed/30 bg-status-failed/[0.06] px-3 py-2 text-[12px] text-status-failed">
            <WifiOff className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>
              수집 서버에 연결되지 않았습니다 · 마지막 동기화{" "}
              {formatRelativeTime(lastIngest)} (직전 동기화 데이터 표시 중)
            </span>
          </div>
        )}
        {collectDelayed && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/[0.08] px-3 py-2 text-[12px] text-amber-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>수집 지연 · 동기화는 최신이나 크롤 채널 응답이 지연되고 있습니다</span>
          </div>
        )}
      </div>
    </div>
  );
}

function ConnectionDot({
  fresh,
  hasData,
}: {
  fresh: boolean;
  hasData: boolean;
}) {
  if (!hasData) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11.5px] text-ink-faint">
        <span className="h-2 w-2 rounded-full bg-ink-faint" />연결 확인 중
      </span>
    );
  }
  return fresh ? (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-status-success">
      <Wifi className="h-3.5 w-3.5" strokeWidth={2.4} />
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success/60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
      </span>
      실시간 갱신
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-status-failed">
      <span className="h-2 w-2 rounded-full bg-status-failed" />수집 서버 미접속
    </span>
  );
}

function CountPill({
  label,
  value,
}: {
  label: string;
  value: number | undefined;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas-soft px-2.5 py-1 text-[12px]">
      <span className="text-ink-muted">{label}</span>
      <span className="font-bold tabular-nums text-ge-navy">
        {value != null ? value.toLocaleString("ko-KR") : "—"}
      </span>
    </span>
  );
}
