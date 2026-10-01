"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { CardEmpty, SourceDownBanner, StatTile, StubCard } from "@/components/stub";
import { getVideoDigests, refreshVideoDigests, type VideoDigest } from "@/lib/api-video";
import { cn } from "@/lib/utils";

// 영상 요약 — 유튜브 영상을 Plaud 로 녹음해 올리면 한 문단 이슈로.
//
// ★흐름: Plaud 제목 `[youtube_261001_월가아재]`(태그·YYMMDD·채널) → 매일 07:40 KST 이후 한 번
//   worker(PLAUD_VIDEO, llm 큐)가 새 녹음만 받아 `claude -p` 로 3~5문장 요약 → 여기.
//   "지금 확인"은 같은 작업을 바로 넣는다(이미 대기·실행 중이면 그대로).
// ⚠️요약이 없는 카드도 그린다 — 대기(Plaud 전사 없음)·실패(LLM)는 이유와 함께. 빈칸을 지어내지 않는다.
// ⚠️날짜 묶음은 **영상 날짜**(제목의 YYMMDD)다. 녹음한 날과 다를 수 있다.

const DAYS = 30;
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

function dateLabel(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  const wd = new Date(y, m - 1, d).getDay();
  return `${y}.${String(m).padStart(2, "0")}.${String(d).padStart(2, "0")} (${WEEKDAY[wd]})`;
}

/** ISO → 한국 시각 "MM-DD HH:mm". 모르면 null(지금으로 채우지 않는다). */
function kstStamp(iso: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return null;
  const p = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(t);
  const g = (k: string) => p.find((x) => x.type === k)?.value ?? "";
  return `${g("month")}-${g("day")} ${g("hour")}:${g("minute")}`;
}

function groupByDate(items: VideoDigest[]): [string, VideoDigest[]][] {
  const acc = new Map<string, VideoDigest[]>();
  for (const it of items) {
    const list = acc.get(it.video_date) ?? [];
    list.push(it);
    acc.set(it.video_date, list);
  }
  // 서버가 최근순으로 준다 — 그 순서를 지킨다.
  return [...acc.entries()];
}

export default function VideoNewsPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["videoDigests", DAYS],
    queryFn: () => getVideoDigests(DAYS),
    // 하루 한 번 쌓이는 데이터다. 작업이 도는 중이면 조금 더 자주 본다.
    refetchInterval: (query) =>
      ["PENDING", "RUNNING"].includes(query.state.data?.last_job?.status ?? "") ? 15_000 : false,
  });
  const refresh = useMutation({
    mutationFn: refreshVideoDigests,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videoDigests"] }),
  });

  const data = q.data;
  const items = data?.items ?? [];
  const done = items.filter((i) => i.status === "done");
  const waiting = items.filter((i) => i.status !== "done");
  const channels = new Set(items.map((i) => i.channel));
  const groups = groupByDate(items);
  const running = ["PENDING", "RUNNING"].includes(data?.last_job?.status ?? "");

  const src = data?.source;
  const srcDown =
    src?.last_error_at != null &&
    (src.last_ok_at == null || Date.parse(src.last_error_at) > Date.parse(src.last_ok_at));
  // 실패한 작업 뒤에 수집이 성공했으면(손으로 돌렸거나 다음 작업) 옛 실패는 띄우지 않는다.
  const jobFailed =
    data?.last_job?.status === "FAILED" &&
    !(
      src?.last_ok_at != null &&
      data.last_job.finished_at != null &&
      Date.parse(src.last_ok_at) > Date.parse(data.last_job.finished_at)
    );

  return (
    <>
      <Topbar title="영상 요약" subtitle="Plaud 녹음 → 한 문단 이슈" />
      <PageContainer fit>
        {q.isError && <SourceDownBanner source="API" detail="영상 요약을 불러오지 못함" />}
        {srcDown && (
          <SourceDownBanner
            source="Plaud"
            detail={src?.last_error_message ?? src?.last_error_kind ?? undefined}
          />
        )}
        {!srcDown && jobFailed && (
          <SourceDownBanner
            source="영상 요약 작업"
            detail={`실패 — ${data?.last_job?.error_message ?? "이유 미상"}`}
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label={`요약 (최근 ${DAYS}일)`}
            value={data ? `${done.length}건` : null}
            hint={data ? `전체 ${items.length}건` : "한 문단 요약"}
            loading={q.isLoading}
          />
          <StatTile
            label="채널"
            value={data ? `${channels.size}곳` : null}
            hint={data && channels.size > 0 ? [...channels].slice(0, 3).join(" · ") : "제목의 채널명"}
            loading={q.isLoading}
          />
          <StatTile
            label="대기·실패"
            value={data ? `${waiting.length}건` : null}
            hint="전사 대기 · LLM 실패"
            loading={q.isLoading}
          />
          <StatTile
            label="마지막 확인"
            value={data ? (kstStamp(src?.last_ok_at ?? null) ?? "—") : null}
            hint={data?.schedule ?? "매일 아침 한 번"}
            loading={q.isLoading}
          />
        </div>

        <StubCard
          title="날짜별 요약"
          subtitle={data ? `영상 날짜 기준 · 최근이 위 · ${items.length}건` : undefined}
          className="flex-1"
          scrollBody
          action={
            <button
              type="button"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || running}
              className="flex items-center gap-1 rounded-md bg-white/15 px-2 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25 disabled:opacity-60"
            >
              <RefreshCw className={cn("h-3 w-3", (refresh.isPending || running) && "animate-spin")} />
              {running ? "확인 중…" : "지금 확인"}
            </button>
          }
        >
          {q.isLoading ? (
            <CardEmpty text="불러오는 중…" />
          ) : items.length === 0 ? (
            <EmptyGuide />
          ) : (
            <div className="space-y-4">
              {groups.map(([day, list]) => (
                <section key={day}>
                  <h3 className="mb-2 text-[12px] font-extrabold text-ge-navy">
                    {dateLabel(day)}
                    <span className="ml-1.5 text-[11px] font-semibold text-ink-muted">
                      {list.length}건
                    </span>
                  </h3>
                  <div className="grid gap-2.5 lg:grid-cols-2">
                    {list.map((v) => (
                      <VideoCard key={v.id} v={v} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </StubCard>
      </PageContainer>
    </>
  );
}

function VideoCard({ v }: { v: VideoDigest }) {
  const recorded = kstStamp(v.recorded_at);
  return (
    <article className="rounded-xl border border-hairline bg-canvas px-3.5 py-3 shadow-card">
      <header className="mb-1.5 flex items-center gap-2">
        <span className="shrink-0 rounded bg-ge-navy/10 px-1.5 py-0.5 text-[10px] font-extrabold text-ge-navy">
          {v.source_tag}
        </span>
        <span className="truncate text-[13px] font-extrabold text-ink" title={v.title}>
          {v.channel}
        </span>
        <StatusChip status={v.status} />
        <span className="ml-auto shrink-0 text-[10px] font-semibold text-ink-muted">
          {v.video_date}
          {recorded && ` · 녹음 ${recorded}`}
        </span>
      </header>
      {v.status === "done" && v.summary_ko ? (
        <p className="text-[12.5px] leading-relaxed text-ink-secondary">{v.summary_ko}</p>
      ) : (
        <p className="text-[12px] font-medium leading-snug text-ink-muted">
          요약 없음{v.error ? ` — ${v.error}` : " — 다음 확인 때 요약"}
        </p>
      )}
    </article>
  );
}

function StatusChip({ status }: { status: string }) {
  if (status === "done") return null;
  const failed = status === "failed";
  return (
    <span
      className={cn(
        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-extrabold",
        failed ? "bg-bid-soft text-status-failed" : "bg-ask-soft text-ask",
      )}
    >
      {failed ? "실패" : "대기"}
    </span>
  );
}

function EmptyGuide() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
      <p className="text-[13px] font-bold text-ink">아직 요약한 영상이 없습니다</p>
      <p className="max-w-md text-[12px] leading-relaxed text-ink-muted">
        유튜브 영상을 Plaud 로 녹음하고 제목을 아래 형식으로 달면, 매일 아침 한 번 새 녹음을
        찾아 한 문단으로 요약합니다.
      </p>
      <code className="rounded-lg bg-canvas-soft px-3 py-1.5 text-[12px] font-bold text-ge-point">
        [youtube_261001_월가아재]
      </code>
      <p className="text-[11px] leading-snug text-ink-muted">
        youtube · 영상 날짜(YYMMDD) · 채널명 — 대괄호는 없어도 됩니다(Youtube_261001_월가아재)
      </p>
    </div>
  );
}
