"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  Emphasized,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  getFreshness,
  getJobSources,
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

const SOURCE_STATE_LABEL: Record<string, string> = {
  alive: "작동",
  down: "멈춤",
  ok: "정상",
  "403": "403 차단",
  "429": "429 요청 제한",
  timeout: "응답 없음",
  other: "오류",
  config: "설정 필요",
  // 계획 B2 — claude CLI(LLM 큐)
  logged_out: "로그아웃",
  usage_limit: "사용량 초과",
  cap: "하루 상한",
  missing: "CLI 없음",
  // 계획 B3b — Investing.com(화면 있는 크롬)
  blocked: "Cloudflare 차단",
  unknown: "기록 없음",
};

const JOB_LABEL: Record<string, string> = {
  SYNC_KIWOOM_PORTFOLIO: "증권사 이력 동기화",
  CSV_IMPORT: "CSV 가져오기",
  TEST_JOB: "테스트 작업",
  SEASONALITY_APPEND: "계절성 월말 종가",
  SEC_13F: "13F 보유 공시",
  SEC_13F_BACKFILL: "13F 과거분 채우기",
  SEC_FORM4: "내부자 거래(Form 4)",
  SEC_13DG: "5% 지분 공시(13D/G)",
  CUSIP_RESOLVE: "CUSIP → 티커 매칭",
  EARNINGS_CALENDAR: "실적 일정",
  EARNINGS_REVENUE: "매출 컨센(Investing)",
  EARNINGS_RESULT: "실적 발표·반응",
  LLM_EXHIBIT: "실적 보도자료 정리(LLM)",
  LLM_JUDGE: "관전포인트 결과(LLM)",
  LLM_WATCHPOINTS: "관전포인트 생성(LLM)",
  PLAUD_VIDEO: "영상 이슈 요약",
};

export default function DataOperationsPage() {
  const qc = useQueryClient();
  const [notesOpen, setNotesOpen] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);

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

  // ★(P0) 네이티브 수집기(LaunchAgent)와 외부 원천의 상태. 수집기는 30초마다 생존 신호를 남긴다.
  const sources = useQuery({
    queryKey: ["jobSources"],
    queryFn: getJobSources,
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
  const workers = (sources.data?.items ?? []).filter((s) => s.kind === "worker");
  const aliveWorkers = workers.filter((s) => s.state === "alive").length;
  const blockedSources = (sources.data?.items ?? []).filter(
    (s) => s.kind === "source" && s.state !== "ok" && s.state !== "unknown",
  );

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
  // 목록이 길면 줄 하나는 못 보고 지나친다 — 카드 제목에서 먼저 알린다.
  const warnedJobs = (jobs.data?.items ?? []).filter(
    (j) => jobNotes(j).length > 0,
  ).length;
  const manual = (f?.ledgers ?? []).filter((l) => !l.auto);
  const sourceDown = !freshness.isLoading && freshness.isError;

  return (
    <>
      <Topbar
        title="수집 상태"
        subtitle="데이터 최신성"
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
              — 새 체결 미반영.
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

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-5">
          <StatTile
            label="마지막 이력 동기화"
            value={
              f?.last_history_sync_status === "RUNNING"
                ? "진행 중"
                : f?.last_history_sync_at
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
          <StatTile
            label="수집기"
            value={
              sources.data
                ? workers.length === 0
                  ? "꺼짐"
                  : `${aliveWorkers}/${workers.length} 작동`
                : null
            }
            hint={
              blockedSources.length > 0
                ? `원천 경고 ${blockedSources.length} — ${blockedSources.map((s) => s.source).join(", ")}`
                : "SEC · 크롤 / LLM 큐"
            }
            accent={
              sources.data
                ? aliveWorkers < workers.length || workers.length === 0 || blockedSources.length > 0
                  ? "down"
                  : "up"
                : undefined
            }
            actionHint="눌러서 원천별 상태 보기"
            onClick={() => setSourcesOpen(true)}
            loading={sources.isLoading}
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
            {syncError && (
              <p className="mt-2 rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold text-ask">
                {syncError}
              </p>
            )}
          </StubCard>

          <StubCard
            title="최근 작업"
            subtitle={
              warnedJobs > 0
                ? `${jobs.data?.items.length ?? 0}건 · 알림 ${warnedJobs}건`
                : `${jobs.data?.items.length ?? 0}건 · 최근순`
            }
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
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        title="수집기 · 원천 상태"
        subtitle="수집기는 30초마다 생존 신호 · 원천은 마지막 성공/실패"
        width={820}
      >
        <DataTable
          columns={["이름", "구분", "상태", "마지막 성공", "마지막 실패"]}
          align={["left", "left", "left", "right", "left"]}
          empty="아직 기록이 없습니다 — 수집기가 한 번도 돌지 않았습니다"
        >
          {(sources.data?.items ?? []).map((s) => (
            <tr key={s.source} className="border-b border-hairline">
              <Cell left strong>{s.source}</Cell>
              <Cell left tone="muted">{s.kind === "worker" ? "수집기" : "원천"}</Cell>
              <Cell left tone={s.state === "alive" || s.state === "ok" ? "up" : s.state === "unknown" ? "muted" : "down"}>
                {SOURCE_STATE_LABEL[s.state] ?? s.state}
              </Cell>
              <Cell tone="muted">{s.last_ok_at ? formatRelativeTime(s.last_ok_at) : "—"}</Cell>
              <Cell left tone="muted" className="max-w-[260px] truncate">
                {s.last_error_at
                  ? `${formatRelativeTime(s.last_error_at)} · ${s.last_error_kind ?? ""} ${s.last_error_message ?? ""}`
                  : "—"}
              </Cell>
            </tr>
          ))}
        </DataTable>
      </Modal>

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

/** 성공했지만 **알려야 하는 것**. 실패 사유(error_message)와 자리를 나눈다. */
function jobNotes(job: Job): string[] {
  const raw = (job.result as { history_notes?: unknown } | null)?.history_notes;
  return Array.isArray(raw) ? raw.filter((n): n is string => typeof n === "string") : [];
}

function JobRow({ job }: { job: Job }) {
  // ⚠️경고를 만들어 놓고 보여 주지 않으면 안 만든 것과 같다. 예전에는 동기화
  //   직후 한 번 뜨고 사라져서, '최근 작업'은 "배당 3종목을 건너뛰었다" 같은
  //   경고를 알 길이 없었다(jobs.result 가 전 행 NULL 이었다).
  const notes = jobNotes(job);
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
        {/* 실패는 아니지만 알아야 하는 것 — 색을 달리해 사유와 구분한다. */}
        {notes.map((note) => (
          <span
            key={note}
            className="block max-w-[140px] truncate text-[10px] text-amber-700"
            title={note}
          >
            {note}
          </span>
        ))}
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
