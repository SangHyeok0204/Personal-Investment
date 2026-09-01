"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Flame } from "lucide-react";
import {
  getUsStockIssues,
  type StockIssueItem,
  type StockIssuePayload,
} from "@/lib/api";
import { EMDASH, fmtPct, moveColor } from "@/components/stock-monitor/format";
import { fmtDay, fmtShortDay, fmtStamp } from "@/components/stock-us/format";
import { cn } from "@/lib/utils";

// [종목 모니터링 · 미국] 이슈 모니터 — 화면 오른쪽 절반.
//
// 원천은 어닝과 같은 상류(S: 어닝모니터)의 `stock_issue_alert` 다. KST 06:00 에 Reddit
// 버즈 급등 종목을 걸러 claude CLI 가 종목마다 분석 3줄·이슈 사유·근거 출처를 만든다.
// collector 가 `analysis_data.json`(숫자)과 `종목이슈분석.md`(서사)를 합쳐 주고, 이 카드는
// 그리기만 한다.
//
// ★★**리포트는 매일 나오지 않는다** — 필터를 통과한 종목이 없으면 그날은 없다(2026-08-27~31
//   닷새 연속). 그래서 화면은 '내용이 있는 가장 최근 리포트'를 띄우되 **며칠 전 것인지**와
//   **오늘 슬롯이 어떤 상태인지**를 머리에 같이 적는다. 둘 중 하나만 적으면 6일 전 이슈를
//   오늘 이슈로 읽게 된다.
// ★어닝 카드와 달리 접지 않는다 — 한 리포트가 5종목 안팎이고, 분석 3줄이 이 카드의 내용
//   전부라 접어 두면 볼 게 남지 않는다.
//
// 폴링 2분. 상류가 하루 한 번인데 이보다 자주 볼 이유는 없고, 그렇다고 더 늦추지 않는 건
// 아침 리포트가 뜨는 시각이 06:07~07:43 로 들쭉날쭉해서다.
const POLL_MS = 120_000;

const TODAY_LABEL: Record<StockIssuePayload["todayStatus"], string> = {
  ready: "오늘 리포트",
  empty: "오늘 통과 종목 없음",
  pending: "오늘 리포트 아직 없음",
};

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-ink-faint">{label}</span>
      {value}
    </span>
  );
}

function Line({ label, text }: { label: string; text?: string }) {
  if (!text) return null;
  return (
    <div className="flex gap-2">
      <span className="mt-px w-[52px] shrink-0 rounded bg-ge-blue-bg px-1 py-px text-center text-[11px] font-bold text-ge-point">
        {label}
      </span>
      <span className="min-w-0 text-[12.5px] leading-snug text-ink-secondary">{text}</span>
    </div>
  );
}

function IssueRow({ s }: { s: StockIssueItem }) {
  return (
    <article className="border-b border-hairline/70 px-3 py-2.5 last:border-b-0">
      <div className="flex items-baseline gap-1.5">
        <span className="shrink-0 text-[13px] font-extrabold tracking-tight text-ink">
          {s.ticker}
        </span>
        <span className="min-w-0 truncate text-[12.5px] text-ink-secondary">{s.name}</span>
        <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-ink-muted">
          {s.marketCap ?? EMDASH}
        </span>
        <span
          className={cn(
            "shrink-0 text-[13px] font-extrabold tabular-nums",
            moveColor(s.priceChange),
          )}
        >
          {fmtPct(s.priceChange)}
        </span>
      </div>

      {s.description && (
        <div className="mt-0.5 truncate text-[12px] text-ink-muted">{s.description}</div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11.5px]">
        {s.tags.map((t) => (
          <span
            key={t}
            className="rounded bg-ge-th px-1.5 py-px font-bold text-ge-navy ring-1 ring-hairline"
          >
            {t}
          </span>
        ))}
        {/* 버즈는 이 리포트에 실린 이유 자체라 제일 눈에 띄게 둔다. 항상 급등(+)이다. */}
        <Metric
          label={s.weekly ? "언급(7d)" : "언급(24h)"}
          value={
            <span className="flex items-center gap-0.5 font-extrabold tabular-nums text-amber-600">
              <Flame className="h-3 w-3" />
              {s.mentionChange == null ? EMDASH : `+${Math.round(s.mentionChange)}%`}
            </span>
          }
        />
        {/* ★센티먼트는 색을 주지 않는다 — 이 화면의 색 관례는 등락(상승 빨강)인데
            같은 카드에서 감성에 초록/빨강을 쓰면 두 관례가 부딪혀 오독을 부른다. */}
        <Metric
          label="센티먼트"
          value={
            <span className="font-bold tabular-nums text-ink">
              {s.sentiment == null ? EMDASH : s.sentiment.toFixed(2)}
            </span>
          }
        />
        <Metric
          label="1개월"
          value={
            <span className={cn("font-bold tabular-nums", moveColor(s.monthlyChange))}>
              {fmtPct(s.monthlyChange)}
            </span>
          }
        />
        {s.triggeredOn && (
          <Metric
            label="촉발"
            value={
              <span className="font-bold tabular-nums text-ink">
                {fmtShortDay(s.triggeredOn)}
              </span>
            }
          />
        )}
      </div>

      <div className="mt-2 flex flex-col gap-1">
        <Line label="핵심" text={s.analysis.issue} />
        <Line label="구조" text={s.analysis.structural} />
        <Line label="시사점" text={s.analysis.implication} />
      </div>

      {s.sourceUrl && (
        <a
          href={s.sourceUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-semibold text-ge-point hover:underline"
        >
          근거 출처
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </article>
  );
}

export function IssueMonitorCard() {
  const { data, isLoading, isError } = useQuery<StockIssuePayload>({
    queryKey: ["us-stock-issues"],
    queryFn: getUsStockIssues,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  const stale = (data?.ageDays ?? 0) > 0;

  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-canvas">
      <header className="flex shrink-0 items-center gap-2 bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">이슈 모니터</h2>
        <span className="shrink-0 text-[13px] font-semibold text-white/90">
          Reddit 버즈 급등 + 주가 급변동
        </span>
        {/* 오늘 슬롯 상태 — '오늘 것이 아니다'를 여기서 먼저 말한다. */}
        {data && (
          <span
            className={cn(
              "shrink-0 text-[12px] font-bold",
              data.todayStatus === "ready" ? "text-white/60" : "text-amber-300",
            )}
            title={data.todayMessage ?? undefined}
          >
            {TODAY_LABEL[data.todayStatus]}
          </span>
        )}
        {data?.available && data.note && (
          <span className="min-w-0 truncate text-[12px] font-semibold text-amber-300">
            {data.note}
          </span>
        )}
        <span className="ml-auto shrink-0 text-[12px] tabular-nums text-white/60">
          {data?.asOf ? (
            <>
              {fmtDay(data.asOf)} 리포트
              {stale && ` · ${data.ageDays}일 전`}
            </>
          ) : (
            fmtStamp(data?.generatedAt)
          )}
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-[13.5px] font-semibold text-ink-muted">
            불러오는 중…
          </div>
        ) : isError ? (
          <div className="flex h-full items-center justify-center text-[13.5px] font-semibold text-rose-600">
            collector 에 못 닿았습니다.
          </div>
        ) : data && !data.available ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
            <div className="text-[13px] font-bold text-amber-600">
              이슈 리포트를 읽지 못했습니다
            </div>
            <div className="text-[12px] text-ink-faint">{data.note}</div>
          </div>
        ) : data && data.stocks.length === 0 ? (
          // 고장이 아니라 '조용한 날들'이다 — 그렇게 읽히도록 문구를 고른다.
          <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
            <div className="text-[13px] font-bold text-ink-muted">
              최근 {data.lookbackDays}일 안에 걸린 종목이 없습니다
            </div>
            <div className="text-[12px] text-ink-faint">
              {data.todayMessage ?? "버즈·주가 필터를 통과한 종목이 없었습니다."}
            </div>
          </div>
        ) : (
          data?.stocks.map((s) => <IssueRow key={s.ticker} s={s} />)
        )}
      </div>

      <footer className="flex shrink-0 items-center gap-2 border-t border-hairline bg-canvas-soft px-3 py-1 text-[11px] text-ink-faint">
        <span className="truncate">{data?.filter ?? "어닝모니터 종목 이슈 분석"}</span>
        <span className="ml-auto shrink-0 tabular-nums">
          수집 {fmtStamp(data?.collectedAt)}
        </span>
      </footer>
    </section>
  );
}
