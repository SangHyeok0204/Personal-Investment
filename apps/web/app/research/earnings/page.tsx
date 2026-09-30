"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { CardEmpty, Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import { CoveragePanel } from "@/components/research/coverage-panel";
import {
  getEarningsMonitor,
  getEarningsMonitorStock,
  type EarningsMonResult,
  type EarningsMonUpcoming,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 실적 모니터 — 내 보유 + 관심종목의 실적 발표 (계획 B · 와이어프레임 B).
//
// 원천: 일정 · EPS 컨센 = Nasdaq(매일 07:10 KST), 매출 컨센 = Investing.com 크롤(B3b — 실패하면 "수집 실패"),
//       실적 · 8-K · 발표 후 반응 = B4, 관전포인트 = 이 맥의 claude CLI(B2 · B5).
// ⚠️이관(B1) 결과 중 Nasdaq 으로 당시 컨센을 확인 못 한 것은 "원본 판정" 배지 — 서프라이즈 % 를 내지 않는다
//   (원본 엑셀의 컨센 칸이 분기마다 갱신되지 않았다).
// ⚠️분기 라벨은 발표일 기준 달력 분기(원본 규칙) — 회사 회계분기가 아니다(NVDA 8월 발표 = 26Q2).

const WEEKDAY = ["월", "화", "수", "목", "금"];
// 방향은 직전 발표의 가이던스(= 이번 분기 것) 대비 — 컨센 대비 상향/하향이 아니다(B4).
const GUIDE_DIR: Record<string, string> = {
  raise: "직전 가이던스보다 높음",
  lower: "직전 가이던스보다 낮음",
  maintain: "직전과 비슷",
  new: "비교할 직전 가이던스 없음",
};

function money(v: number | null | undefined): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  return `${s}$${a.toFixed(2)}`;
}

function eps(v: number | null | undefined): string {
  return v == null ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`;
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function amount(v: number | null, verified: boolean, format = money): string {
  return `${format(v)}${v != null && !verified ? " (미검증)" : ""}`;
}

function revConsensus(e: { revenue_forecast: number | null; revenue_forecast_status: string | null; revenue_forecast_verified: boolean }): string {
  if (e.revenue_forecast_status === "failed") return "수집 실패";
  if (e.revenue_forecast == null) return "수집 전";
  return amount(e.revenue_forecast, e.revenue_forecast_verified);
}

function verdictTone(v: string | null): "up" | "down" | "muted" | undefined {
  return v === "상회" ? "up" : v === "하회" ? "down" : v === "부합" ? "muted" : undefined;
}

export default function EarningsMonitorPage() {
  const [pick, setPick] = useState<string | null>(null);
  const [dayPick, setDayPick] = useState<string | null>(null);

  const q = useQuery({ queryKey: ["earningsMonitor"], queryFn: getEarningsMonitor, staleTime: 5 * 60_000 });
  const d = q.data;
  const detail = useQuery({
    queryKey: ["earningsMonitorStock", pick],
    queryFn: () => getEarningsMonitorStock(pick!),
    enabled: pick != null,
    staleTime: 5 * 60_000,
  });

  const maxDay = Math.max(1, ...(d?.days ?? []).map((x) => x.tickers.length));
  const surprises = (d?.recent ?? []).filter((r) => r.eps_surprise_pct != null);
  // 극단값(예: 적자 → 흑자 +1,400%)이 막대를 잡아먹지 않게 ±100% 에서 자른다 — 숫자는 그대로 적는다
  const cap = 100;
  const maxAbs = Math.max(10, ...surprises.map((r) => Math.min(Math.abs(r.eps_surprise_pct!), cap)));
  const dayRows = dayPick ? (d?.days.find((x) => x.date === dayPick)?.tickers ?? []) : [];

  return (
    <>
      <Topbar
        title="어닝 콜 / 이슈"
        subtitle={
          d
            ? `보유·관심 ${d.targets.length}종목 · 일정·EPS 컨센 Nasdaq · 관전포인트 claude · ${d.today} 기준`
            : "보유·관심종목 실적 발표"
        }
      />
      <PageContainer fit>
        <CoveragePanel kind="earnings" fit />
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="이번 주 발표"
            value={d ? `내 종목 ${d.this_week_count}` : null}
            hint={
              d
                ? d.this_week_count
                  ? d.days.filter((x) => x.week === 0).flatMap((x) => x.tickers).join(" · ")
                  : `다음 발표까지 ${d.next ? `${d.next.days_left}일` : "—"}`
                : undefined
            }
            loading={q.isLoading}
          />
          <StatTile
            label="지난주 결과"
            value={d ? (d.last_week.n ? `상회 ${d.last_week.beat} · 하회 ${d.last_week.miss}` : "발표 없음") : null}
            hint={d ? `부합 ${d.last_week.inline} · EPS(매출 컨센 확보 시 매출도) ±3% 기준` : undefined}
            loading={q.isLoading}
          />
          <StatTile
            label="다음 발표"
            value={d?.next ? `${d.next.ticker}  D-${d.next.days_left}` : d ? "없음" : null}
            hint={
              d?.next
                ? `${d.next.report_date} ${d.next.timing} · EPS 컨센 ${amount(d.next.eps_forecast, d.next.eps_forecast_verified, eps)}${d.next.timing === "미정" ? " · 예상일" : ""}`
                : undefined
            }
            onClick={d?.next ? () => setPick(d.next!.ticker) : undefined}
            actionHint="눌러서 종목 상세"
            loading={q.isLoading}
          />
          <StatTile
            label="발표 후 최대 반응"
            value={d?.max_reaction ? `${d.max_reaction.ticker} ${pct(d.max_reaction.reaction_pct)}` : d ? "수집 전" : null}
            accent="auto"
            hint={d?.max_reaction ? `${d.max_reaction.reaction_window ?? ""}` : "장후 16:00→17:30 ET 토스 1분봉(B4)"}
            loading={q.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:auto-rows-auto lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard title="이번 주 · 다음 주 발표" subtitle="요일 막대(장전 · 장후 · 미정) · 아래는 9주 안 전체" scrollBody>
            {q.isLoading || !d ? (
              <CardEmpty text={q.isLoading ? "불러오는 중…" : "데이터 없음"} />
            ) : (
              <div className="space-y-3">
                <div className="flex items-end gap-1.5">
                  {d.days.map((x, i) => {
                    const n = x.tickers.length;
                    const h = (n / maxDay) * 64;
                    return (
                      <button
                        key={x.date}
                        type="button"
                        onClick={() => n && setDayPick(x.date)}
                        title={`${x.date} · ${x.tickers.join(", ") || "없음"}`}
                        className={cn("flex min-w-0 flex-1 flex-col items-center gap-1", i === 5 && "ml-3")}
                      >
                        <span className="text-[10px] font-bold tabular-nums text-ink-muted">{n || ""}</span>
                        <span className="flex w-full flex-col-reverse overflow-hidden rounded-t" style={{ height: 64 }}>
                          <span className="w-full bg-[#3A6B96]" style={{ height: (x.bmo / Math.max(n, 1)) * h }} />
                          <span className="w-full bg-[#7B401F]" style={{ height: (x.amc / Math.max(n, 1)) * h }} />
                          <span className="w-full bg-[#A6A6A6]" style={{ height: (x.tbd / Math.max(n, 1)) * h }} />
                        </span>
                        <span className={cn("text-[10px] font-semibold", x.date === d.today ? "text-ge-point" : "text-ink-faint")}>
                          {WEEKDAY[i % 5]} {x.date.slice(8)}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <div className="flex gap-3 text-[10px] font-semibold text-ink-faint">
                  <span><span className="mr-1 inline-block h-2 w-2 bg-[#3A6B96]" />장전</span>
                  <span><span className="mr-1 inline-block h-2 w-2 bg-[#7B401F]" />장후</span>
                  <span><span className="mr-1 inline-block h-2 w-2 bg-[#A6A6A6]" />미정(예상일)</span>
                </div>
                <DataTable
                  columns={["종목", "발표일", "시각", "EPS 컨센", "매출 컨센"]}
                  align={["left", "left", "left", "right", "right"]}
                  empty="9주 안에 발표가 없습니다"
                >
                  {d.upcoming.map((u) => (
                    <UpcomingRow key={u.id} u={u} onPick={() => setPick(u.ticker)} />
                  ))}
                </DataTable>
                <p className="text-[11px] text-ink-faint">
                  {d.no_events.length ? `실적 없음(ETF 등): ${d.no_events.join(", ")} · ` : ""}
                  4주 밖 = 예상일(흐림)
                </p>
              </div>
            )}
          </StubCard>

          <StubCard title="최근 발표 EPS 서프라이즈" subtitle="당시 컨센 대비 · 누르면 종목 상세" scrollBody>
            {q.isLoading || !d ? (
              <CardEmpty text={q.isLoading ? "불러오는 중…" : "데이터 없음"} />
            ) : (
              <div className="space-y-1">
                {d.recent.map((r) => (
                  <SurpriseRow key={r.id} r={r} maxAbs={maxAbs} cap={cap} onPick={() => setPick(r.ticker)} />
                ))}
                <p className="pt-2 text-[11px] text-ink-faint">
                  막대는 ±{cap}% 에서 자름(적자 → 흑자 같은 극단값). &quot;원본 판정&quot; = 이관 자료라 당시 컨센을 확인 못 한 발표.
                </p>
              </div>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal open={dayPick != null} onClose={() => setDayPick(null)} title={`${dayPick ?? ""} 발표`}>
        <div className="flex flex-wrap gap-2">
          {dayRows.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => {
                setDayPick(null);
                setPick(t);
              }}
              className="rounded-lg border border-hairline px-3 py-1.5 text-[13px] font-bold text-ink hover:bg-ge-th"
            >
              {t}
            </button>
          ))}
        </div>
      </Modal>

      <Modal
        open={pick != null}
        onClose={() => setPick(null)}
        title={detail.data ? `${detail.data.ticker} · ${detail.data.company}` : pick ?? ""}
        subtitle="관전포인트 → 결과 · EPS/매출 실적 vs 컨센 · 가이던스 · 발표 후 반응 · 8-K"
        width={880}
      >
        {detail.isLoading || !detail.data ? (
          <CardEmpty text="불러오는 중…" />
        ) : (
          <div className="space-y-4">
            {detail.data.events.map((e) => (
              <section key={e.id} className="rounded-xl border border-hairline p-3">
                <header className="mb-2 flex flex-wrap items-baseline gap-2">
                  <b className="text-[14px] text-ink">{e.quarter}</b>
                  <span className="text-[12px] text-ink-muted">
                    {e.report_date} {e.timing}
                  </span>
                  {e.verdict && (
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[11px] font-bold",
                        e.verdict === "상회" ? "bg-bid-soft text-bid" : e.verdict === "하회" ? "bg-ask-soft text-ask" : "bg-canvas-soft text-ink-muted",
                      )}
                    >
                      {e.verdict}
                    </span>
                  )}
                  {e.verdict && !e.verdict_verified && (
                    <span className="rounded bg-ink-faint/15 px-1.5 py-0.5 text-[10px] font-bold text-ink-muted">미검증 판정</span>
                  )}
                  {e.overall && e.overall !== "미확인" && (
                    <span
                      title="보도자료 · 가이던스까지 본 LLM 종합 판정(claude)"
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold",
                        e.overall === "서프라이즈" ? "bg-bid-soft text-bid" : e.overall === "쇼크" ? "bg-ask-soft text-ask" : "bg-canvas-soft text-ink-muted",
                      )}
                    >
                      종합 {e.overall}
                    </span>
                  )}
                  {e.filing_url && (
                    <a href={e.filing_url} target="_blank" rel="noreferrer" className="ml-auto text-[11px] font-semibold underline">
                      8-K 원문
                    </a>
                  )}
                </header>
                <dl className="mb-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-4">
                  <Fig label="EPS 실적 / 컨센" value={`${amount(e.eps_actual, e.eps_actual_verified, eps)} / ${amount(e.eps_forecast, e.eps_forecast_verified, eps)}`} />
                  <Fig label="EPS 서프라이즈" value={amount(e.eps_surprise_pct, e.eps_actual_verified && e.eps_forecast_verified, pct)} />
                  <Fig label="매출 실적 / 컨센" value={`${amount(e.revenue_actual, e.revenue_actual_verified)} / ${revConsensus(e)}`} />
                  <Fig
                    label="발표 후 반응"
                    value={e.reaction_pct != null ? `${pct(e.reaction_pct)} ${e.reaction_window ?? ""}` : "—"}
                  />
                </dl>
                {e.watchpoints.length > 0 && (
                  <ol className="space-y-1">
                    {e.watchpoints.map((w) => (
                      <li key={w.rank} className="text-[12px] leading-snug">
                        <span className="mr-1 font-bold text-ge-point">{"①②③④"[w.rank - 1]}</span>
                        <span className="text-ink">{w.point ?? "—"}</span>
                        {w.result && <span className="block pl-5 text-ink-muted">→ {w.result}</span>}
                        {w.source === "llm" && !w.result && (
                          <span className="ml-1 text-[10px] text-ink-faint">({w.model ?? "claude"} 생성 · 결과는 발표 후)</span>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
                {e.guidance.length > 0 && (
                  <div className="mt-2 space-y-0.5 text-[12px] text-ink-secondary">
                    {e.guidance.map((g) => (
                      <p key={g.metric}>
                        <b className="text-ink">다음 분기 {g.metric === "revenue" ? "매출" : "EPS"} 가이던스</b>{" "}
                        {g.metric === "revenue" ? money(g.low) : eps(g.low)} ~ {g.metric === "revenue" ? money(g.high) : eps(g.high)}
                        <span className="ml-1 text-[11px] font-semibold text-ge-point">
                          {GUIDE_DIR[g.direction ?? "new"] ?? g.direction}
                        </span>
                      </p>
                    ))}
                    {e.guidance.find((g) => g.text)?.text && (
                      <p className="text-[11px] text-ink-faint">{e.guidance.find((g) => g.text)!.text}</p>
                    )}
                  </div>
                )}
                {e.reaction_note && <p className="mt-2 text-[11px] text-ink-faint">원본 반응 요약: {e.reaction_note}</p>}
              </section>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10.5px] font-bold text-ink-muted">{label}</dt>
      <dd className="font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

function UpcomingRow({ u, onPick }: { u: EarningsMonUpcoming; onPick: () => void }) {
  return (
    <tr
      className={cn("cursor-pointer border-b border-hairline hover:bg-ge-th/60", !u.within_4w && "opacity-55")}
      onClick={onPick}
    >
      <Cell left strong>
        {u.ticker}
        <span className="ml-1.5 font-normal text-ink-faint">{u.company}</span>
      </Cell>
      <Cell left>
        {u.report_date?.slice(5)} <span className="text-ink-faint">D-{u.days_left}</span>
      </Cell>
      <Cell left tone={u.timing === "미정" ? "muted" : undefined}>
        {u.timing}
      </Cell>
      <Cell>
        {amount(u.eps_forecast, u.eps_forecast_verified, eps)}
        {u.n_estimates != null && <span className="ml-1 text-[10px] text-ink-faint">({u.n_estimates})</span>}
      </Cell>
      <Cell tone={u.revenue_forecast_status === "failed" ? "down" : u.revenue_forecast == null ? "muted" : undefined}>
        {revConsensus(u)}
      </Cell>
    </tr>
  );
}

function SurpriseRow({ r, maxAbs, cap, onPick }: { r: EarningsMonResult; maxAbs: number; cap: number; onPick: () => void }) {
  const v = r.eps_surprise_pct;
  const w = v == null ? 0 : (Math.min(Math.abs(v), cap) / maxAbs) * 50;
  return (
    <button type="button" onClick={onPick} className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-ge-th/60">
      <span className="w-14 shrink-0 text-[12px] font-bold text-ink">{r.ticker}</span>
      <span className="w-12 shrink-0 text-[10px] text-ink-faint">{r.report_date?.slice(5)}</span>
      <span className="relative h-3 flex-1">
        <span className="absolute inset-y-0 left-1/2 border-l border-ink-faint/50" />
        {v != null && (
          <span
            className={cn("absolute inset-y-0", v >= 0 ? "bg-bid" : "bg-ask")}
            style={v >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
          />
        )}
      </span>
      <span className="w-16 shrink-0 text-right text-[12px] font-semibold tabular-nums">
        {v != null ? (
          <span className={v >= 0 ? "text-bid" : "text-ask"}>{amount(v, r.eps_actual_verified && r.eps_forecast_verified, pct)}</span>
        ) : (
          <span className="text-[10px] text-ink-faint">{r.verdict ? "원본 판정" : "—"}</span>
        )}
      </span>
      <span className={cn("w-16 shrink-0 text-[11px] font-bold", verdictTone(r.verdict) === "up" ? "text-bid" : verdictTone(r.verdict) === "down" ? "text-ask" : "text-ink-faint")}>
        {r.verdict ?? ""}{r.verdict && !r.verdict_verified ? " (미검증)" : ""}
      </span>
    </button>
  );
}
