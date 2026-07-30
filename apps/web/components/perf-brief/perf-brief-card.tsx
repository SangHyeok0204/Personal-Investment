"use client";

/* [성과보고] 카드 컨테이너 — 저장된 보고서 조회 + 엑셀 실시간 분석.
 *
 * 두 소스가 한 카드에 들어간다.
 *  ① 보고서(JSON)  — performance-brief 스킬 산출물. 서사(시장·스토리·관전 포인트) 포함.
 *     요일 규칙(월=위클리 / 화~금=데일리)은 collector 가 판정하고, 오늘 작성분이 없으면
 *     **낡은 수치를 절대 그리지 않는다**(어제 숫자를 오늘로 오인하는 사고 방지).
 *  ② [분석 시작] — 운용역 소스 엑셀을 그 자리에서 읽어 만드는 정량 분석.
 *     매번 같은 순서·같은 형태. 서사는 없다(뉴스 조사가 필요한 부분이라 엑셀만으론 불가). */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPerfAnalysis,
  getPerfBrief,
  getPerfGenerateStatus,
  startPerfGenerate,
  type PerfAnalysis,
} from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { PerfBriefReport } from "./perf-brief";
import { downloadReportHtml } from "./report-html";

type Mode = "daily" | "weekly";
const KIND_LABEL: Record<Mode, string> = { daily: "데일리", weekly: "위클리" };

function Notice({
  head,
  body,
  latest,
}: {
  head: string;
  body: string;
  latest?: { label: string; writtenOn: string | null } | null;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-hairline bg-canvas-soft px-6 py-12 text-center">
      <div className="text-[15px] font-bold text-ge-navy">{head}</div>
      <div className="mt-1.5 max-w-lg text-[13px] leading-relaxed text-ink-muted">{body}</div>
      {latest && (
        <div className="mt-4 rounded-lg border border-hairline bg-canvas px-3.5 py-2 text-[12px] text-ink-secondary">
          마지막 보고서 — <b className="font-bold text-ink">{latest.label}</b>
          {latest.writtenOn && (
            <span className="text-ink-muted"> · {latest.writtenOn.replace(/-/g, ".")} 작성</span>
          )}
        </div>
      )}
    </div>
  );
}

/* QA 경고 — 계산은 됐지만 사람이 확인해야 하는 것들(결측·비중합·시트값 불일치). */
function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="mb-4 rounded-xl border border-[#e6c9a8] bg-[#fdf6ee] px-4 py-3">
      <div className="mb-1.5 text-[12px] font-bold text-[#8a5a1f]">
        QA 경고 {items.length}건 — 보고서 작성 전 확인
      </div>
      <ul className="space-y-1">
        {items.map((w, i) => (
          <li key={i} className="text-[12px] leading-relaxed text-[#6b4a1c]">
            · {w}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ModeBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-2.5 py-1 text-[12px] font-semibold transition ${
        active ? "bg-ge-navy text-white" : "text-ink-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

/* 보고서 생성 진행 패널 — 러너의 단계 로그를 그대로 보여준다. 수 분 걸리는 작업이라
 * 무엇을 하고 있는지(수치 조회 → 프롬프트 → 뉴스 조사 → 검증·저장)가 보여야 한다. */
function GenerateProgress({
  elapsedSec,
  log,
}: {
  elapsedSec?: number;
  log: string[];
}) {
  const mm = String(Math.floor((elapsedSec ?? 0) / 60)).padStart(2, "0");
  const ss = String((elapsedSec ?? 0) % 60).padStart(2, "0");
  return (
    <div className="rounded-xl border border-hairline bg-canvas-soft px-5 py-6">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ge-point border-t-transparent" />
        <span className="text-[14px] font-bold text-ge-navy">보고서 생성 중</span>
        <span className="text-[12px] tabular-nums text-ink-muted">
          {mm}:{ss} 경과
        </span>
        <span className="ml-auto text-[11.5px] text-ink-muted">
          뉴스 조사가 포함돼 수 분 걸립니다 · 페이지를 떠나도 계속 진행됩니다
        </span>
      </div>
      <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-lg border border-hairline bg-canvas px-3.5 py-3 text-[11.5px] leading-relaxed text-ink-secondary">
        {log.length ? log.join("\n") : "시작하는 중…"}
      </pre>
    </div>
  );
}

export function PerfBriefCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["perfBrief"],
    queryFn: getPerfBrief,
    refetchInterval: 300000, // 5분 — 아침 생성분을 자동으로 집어 올린다.
    retry: false,
  });
  const d = query.data;

  // 분석 모드 기본값은 요일 규칙을 따르되, 사용자가 바꿀 수 있다.
  const [mode, setMode] = useState<Mode | null>(null);
  const effMode: Mode = mode ?? (d?.expected === "weekly" ? "weekly" : "daily");

  const analysis = useMutation<PerfAnalysis, Error, Mode>({
    mutationFn: getPerfAnalysis,
  });
  const result = analysis.data;

  // 생성 작업 상태. 작업이 도는 동안에만 폴링한다(평소엔 러너가 꺼져 있을 수 있음).
  const [watching, setWatching] = useState(false);
  const job = useQuery({
    queryKey: ["perfGenerate"],
    queryFn: getPerfGenerateStatus,
    enabled: watching,
    refetchInterval: watching ? 3000 : false,
    retry: false,
  });
  const running = job.data?.status === "running";

  const generate = useMutation({
    mutationFn: (m: Mode) => startPerfGenerate(m),
    onSuccess: () => setWatching(true),
  });

  useEffect(() => {
    if (!watching || running) return;
    const s = job.data?.status;
    if (s !== "done" && s !== "failed") return;
    setWatching(false);
    if (s === "done") {
      analysis.reset(); // 새로 저장된 보고서가 보이도록 정량분석 화면을 내린다
      queryClient.invalidateQueries({ queryKey: ["perfBrief"] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching, running, job.data?.status]);

  const kind = d?.expected ? KIND_LABEL[d.expected] : null;

  // 화면에 떠 있는 보고서(생성본 또는 엑셀 정량분석)를 그대로 HTML 로 내려받는다.
  const shown = result ?? (d?.status === "ready" ? d.report : null);

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
      <div className="h-2 rounded-t-2xl bg-ge-main" />
      <div className="px-5 pb-5 pt-4">
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex items-center gap-2">
            <span className="h-4 w-1.5 rounded-full bg-ge-main" />
            <span className="text-[14px] font-extrabold text-ge-navy">
              {result ? "성과 분석 — 엑셀 실시간" : `오늘의 성과보고${kind ? ` — ${kind}` : ""}`}
            </span>
          </div>
          {result && (
            <span className="rounded-md bg-ge-blue-bg px-2 py-0.5 text-[11px] font-bold text-ge-point">
              {result.source} · 저장 {result.sourceSavedAt}
            </span>
          )}
          {!result && d?.status === "ready" && d.report && (
            <span className="rounded-md bg-ge-blue-bg px-2 py-0.5 text-[11px] font-bold text-ge-point">
              {d.report.writtenOn.replace(/-/g, ".")} 작성
            </span>
          )}

          <div className="ml-auto flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-hairline bg-canvas-soft p-0.5">
              <ModeBtn active={effMode === "daily"} onClick={() => setMode("daily")}>
                일간
              </ModeBtn>
              <ModeBtn active={effMode === "weekly"} onClick={() => setMode("weekly")}>
                주간
              </ModeBtn>
            </div>
            <button
              type="button"
              onClick={() => analysis.mutate(effMode)}
              disabled={analysis.isPending || running}
              className="rounded-lg border border-ge-point px-3.5 py-1.5 text-[12px] font-bold text-ge-point transition hover:bg-ge-blue-bg disabled:opacity-50"
            >
              {analysis.isPending ? "분석 중…" : "분석 시작"}
            </button>
            <button
              type="button"
              onClick={() => generate.mutate(effMode)}
              disabled={running || generate.isPending}
              title="claude 가 뉴스 조사와 서사까지 붙인 완성 보고서를 만듭니다 (수 분)"
              className="rounded-lg bg-ge-point px-3.5 py-1.5 text-[12px] font-bold text-white transition hover:bg-primary-active disabled:opacity-50"
            >
              {running || generate.isPending ? "생성 중…" : "보고서 생성"}
            </button>
            {shown && !running && (
              <button
                type="button"
                onClick={() => downloadReportHtml(shown, result?.warnings)}
                title="지금 화면의 보고서를 기존 서식 그대로 HTML 파일로 저장합니다"
                className="rounded-lg border border-hairline px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-canvas-soft"
              >
                파일로 저장
              </button>
            )}
            {result && (
              <button
                type="button"
                onClick={() => analysis.reset()}
                className="rounded-lg border border-hairline px-3 py-1.5 text-[12px] font-semibold text-ink-muted transition hover:text-ink"
              >
                보고서로
              </button>
            )}
          </div>
        </div>

        {running || generate.isPending ? (
          <GenerateProgress elapsedSec={job.data?.elapsedSec} log={job.data?.log ?? []} />
        ) : generate.isError ? (
          <Notice
            head="보고서 생성을 시작하지 못했습니다"
            body={`${generate.error.message} — Windows 러너(성과보고_러너_시작.bat)가 켜져 있는지 확인해 주세요.`}
          />
        ) : job.data?.status === "failed" ? (
          <Notice
            head="보고서 생성에 실패했습니다"
            body={`${job.data.error ?? "원인 불명"} — 러너 창의 로그를 확인해 주세요. 수치는 [분석 시작]으로 바로 볼 수 있습니다.`}
          />
        ) : analysis.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-[280px] w-full rounded-xl" />
          </div>
        ) : analysis.isError ? (
          <Notice
            head="분석에 실패했습니다"
            body={`소스 엑셀(${KIND_LABEL[effMode]})을 읽지 못했습니다. 파일이 정기미팅 폴더에 있는지, 다른 곳에서 편집 중이 아닌지 확인해 주세요. (${analysis.error.message})`}
          />
        ) : result ? (
          <div className="mx-auto max-w-[1180px]">
            <Warnings items={result.warnings} />
            <PerfBriefReport report={result} />
          </div>
        ) : query.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-[280px] w-full rounded-xl" />
          </div>
        ) : query.isError || !d ? (
          <Notice
            head="성과보고를 불러올 수 없습니다"
            body="collector 가 정기미팅 폴더를 읽지 못했습니다. 마운트와 collector 상태를 확인해 주세요."
          />
        ) : d.status === "ready" && d.report ? (
          <PerfBriefReport report={d.report} />
        ) : d.status === "off" ? (
          <Notice
            head="주말 — 예정된 보고서가 없습니다"
            body="성과보고는 월요일(위클리)과 화~금요일(데일리)에 발행됩니다. [분석 시작]을 누르면 엑셀에서 정량 분석을 바로 만들 수 있습니다."
            latest={d.latest}
          />
        ) : (
          <Notice
            head={`오늘 ${kind ?? ""} 성과보고 준비 중`}
            body="아직 오늘 작성된 보고서가 없습니다. 생성되면 이 자리에 자동으로 표시됩니다. [분석 시작]을 누르면 엑셀에서 정량 분석을 바로 만들 수 있습니다."
            latest={d.latest}
          />
        )}
      </div>
    </section>
  );
}
