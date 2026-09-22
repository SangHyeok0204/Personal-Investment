"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  getFreshness,
  getJobs,
  runHistorySync,
  type Freshness,
  type Job,
} from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수집 상태 — **내 데이터가 최신인가.**
//
// ★2026-09-22 다시 씀: 원본 GE 의 영문 작업 실행기(테스트 잡 실행 · CSV 업로드)
//   였다. 이 계좌의 데이터는 전부 증권사 API 로 들어오므로 CSV 업로드는 쓸 일이
//   없고, 정작 **"체결이 며칠째 안 들어오고 있다"**를 알려 주는 자리가 없었다.
//   실제로 그래서 체결 원장이 2일 밀린 걸 며칠 뒤에야 발견했다.
//
// ⚠️잔고·보유는 5초마다 자동으로 갱신되지만 **체결·배당·주문·일별성과는 이력
//   동기화를 돌려야만** 들어온다. 둘을 한 숫자로 뭉뚱그리면 "방금 동기화됨"이라
//   적어 놓고 체결은 사흘 전 것을 보여 주게 된다.
//
// ⚠️뒤처짐을 **"몇 시간 지났나"로 판정하지 않는다.** 주말에는 사흘이 지나도
//   받을 게 없고, 장 마감 직후에는 한 시간만 지나도 받을 게 있다. 마지막
//   동기화 이후 **정규장이 닫힌 적이 있는가**로 본다.

const STATUS_STYLE: Record<string, string> = {
  SUCCESS: "bg-bid-soft text-bid",
  FAILED: "bg-ask-soft text-ask",
  RUNNING: "bg-ge-point/12 text-ge-point",
  PENDING: "bg-canvas-soft text-ink-faint",
};

const JOB_LABEL: Record<string, string> = {
  SYNC_KIWOOM_PORTFOLIO: "증권사 이력 동기화",
  CSV_IMPORT: "CSV 가져오기",
  TEST_JOB: "테스트 작업",
};

export default function DataOperationsPage() {
  const qc = useQueryClient();
  const [notesOpen, setNotesOpen] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const freshness = useQuery({
    queryKey: ["freshness"],
    queryFn: getFreshness,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const jobs = useQuery({
    queryKey: ["jobs", { limit: 12 }],
    queryFn: () => getJobs({ limit: 12 }),
    staleTime: 30_000,
  });

  const sync = useMutation({
    mutationFn: runHistorySync,
    onSuccess: () => {
      setSyncError(null);
      qc.invalidateQueries({ queryKey: ["freshness"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e: unknown) =>
      setSyncError(e instanceof Error ? e.message : "동기화하지 못했습니다."),
  });

  const f = freshness.data;
  const manual = (f?.ledgers ?? []).filter((l) => !l.auto);
  const sourceDown = !freshness.isLoading && freshness.isError;

  return (
    <>
      <Topbar
        title="수집 상태"
        subtitle="내 데이터가 최신인가"
        showAccountContext={false}
      />
      <PageContainer fit>
        {sourceDown && (
          <SourceDownBanner source="API" detail="수집 상태를 받지 못했습니다." />
        )}

        {/* ⚠️뒤처졌으면 맨 위에서 말한다 — 이걸 모르면 옛 숫자를 보고 판단한다. */}
        {f?.stale && (
          <div className="flex shrink-0 items-center gap-2 rounded-xl border border-ask/25 bg-ask-soft px-3 py-2">
            <span className="shrink-0 rounded bg-ask/15 px-1.5 py-0.5 text-[10px] font-extrabold text-ask">
              뒤처짐
            </span>
            <span className="text-[11px] font-semibold leading-snug text-ink-secondary">
              마지막 이력 동기화 이후 미국 정규장이 닫혔습니다
              {f.last_market_close_at && (
                <> (마감 {formatDateTime(f.last_market_close_at)})</>
              )}{" "}
              — 새 체결이 있어도 아직 안 들어와 있습니다.{" "}
              <strong>체결·배당·주문·일별성과</strong>를 쓰는 화면이 옛 것을
              보여 줍니다.
            </span>
            <button
              type="button"
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
              className="ml-auto shrink-0 rounded-lg bg-ask px-3 py-1.5 text-[11px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {sync.isPending ? "받는 중… (40초쯤)" : "지금 받아오기"}
            </button>
          </div>
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="마지막 이력 동기화"
            value={
              f?.last_history_sync_at
                ? formatRelativeTime(f.last_history_sync_at)
                : f
                  ? "없음"
                  : null
            }
            hint={
              f?.last_history_sync_at
                ? formatDateTime(f.last_history_sync_at)
                : "한 번도 돌린 기록이 없습니다"
            }
            accent={f?.stale ? "down" : undefined}
            loading={freshness.isLoading}
          />
          <StatTile
            label="상태"
            value={f ? (f.stale ? "받아올 것 있음" : "최신") : null}
            hint={
              f?.last_market_close_at
                ? `기준: 마지막 정규장 마감 ${formatDateTime(f.last_market_close_at)}`
                : "정규장 마감 기준으로 판정"
            }
            accent={f ? (f.stale ? "down" : "up") : undefined}
            actionHint="눌러서 판정 기준 보기"
            onClick={() => setNotesOpen(true)}
            loading={freshness.isLoading}
          />
          <StatTile
            label="자동 갱신"
            value={f ? `${f.ledgers.filter((l) => l.auto).length}종` : null}
            hint="잔고 · 보유 — 5초마다"
            loading={freshness.isLoading}
          />
          <StatTile
            label="이력 동기화 필요"
            value={f ? `${manual.length}종` : null}
            hint="체결 · 주문 · 배당 · 실현 · 일별성과"
            loading={freshness.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] xl:auto-rows-auto",
          )}
        >
          <StubCard
            title="원장별 상태"
            subtitle="무엇이 언제까지 들어와 있나"
            className="min-h-0"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => sync.mutate()}
                disabled={sync.isPending}
                className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25 disabled:opacity-50"
              >
                {sync.isPending ? "받는 중…" : "이력 받아오기"}
              </button>
            }
          >
            <DataTable
              columns={["원장", "최신", "건수", "갱신"]}
              align={["left", "left", "right", "right"]}
              empty={freshness.isLoading ? "불러오는 중…" : "표시할 원장이 없습니다"}
            >
              {(f?.ledgers ?? []).map((l) => (
                <tr key={l.key} className="border-b border-hairline">
                  <Cell left strong>
                    {l.label}
                  </Cell>
                  <Cell left tone={l.last_date ? undefined : "muted"}>
                    {l.last_date ?? "—"}
                  </Cell>
                  <Cell tone="muted">{l.row_count.toLocaleString()}</Cell>
                  <Cell>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold",
                        l.auto
                          ? "bg-bid-soft text-bid"
                          : "bg-canvas-soft text-ink-muted",
                      )}
                    >
                      {l.auto ? "자동 5초" : "이력"}
                    </span>
                  </Cell>
                </tr>
              ))}
            </DataTable>
            {/* ⚠️원장 날짜가 며칠 전이어도 뒤처진 게 아닐 수 있다. */}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              최신 날짜가 며칠 전이어도 <strong>뒤처진 것이 아닐 수 있습니다</strong> —
              배당은 지급일에만, 매매는 거래한 날에만 생깁니다. 판정은 위의 동기화
              시각으로 합니다.
            </p>
            {syncError && (
              <p className="mt-2 rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold text-ask">
                {syncError}
              </p>
            )}
          </StubCard>

          <StubCard
            title="최근 작업"
            subtitle={`${jobs.data?.items.length ?? 0}건 · 최근순`}
            className="min-h-0"
            scrollBody
          >
            <DataTable
              columns={["시각", "작업", "상태", "걸린 시간"]}
              align={["left", "left", "left", "right"]}
              empty={jobs.isLoading ? "불러오는 중…" : "기록이 없습니다"}
            >
              {(jobs.data?.items ?? []).map((j) => (
                <JobRow key={j.id} job={j} />
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="뒤처짐을 어떻게 판정하나"
        subtitle="시간이 아니라 장 마감 기준"
      >
        <ul className="space-y-2">
          {(f?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                <Emphasized text={text} />
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function JobRow({ job }: { job: Job }) {
  const took =
    job.started_at && job.finished_at
      ? `${Math.round(
          (new Date(job.finished_at).getTime() -
            new Date(job.started_at).getTime()) /
            1000,
        )}초`
      : "—";
  return (
    <tr className="border-b border-hairline">
      <Cell left tone="muted">
        {formatDateTime(job.created_at)?.slice(5) ?? "—"}
      </Cell>
      <Cell left strong>
        <span className="block max-w-[140px] truncate">
          {JOB_LABEL[job.job_type] ?? job.job_type}
        </span>
        {job.error_message && (
          <span
            className="block max-w-[140px] truncate text-[10px] text-ask"
            title={job.error_message}
          >
            {job.error_message}
          </span>
        )}
      </Cell>
      <Cell left>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold",
            STATUS_STYLE[job.status] ?? STATUS_STYLE.PENDING,
          )}
        >
          {job.status}
        </span>
      </Cell>
      <Cell tone="muted">{took}</Cell>
    </tr>
  );
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */
function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="text-ink">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  );
}
