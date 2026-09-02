"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getEtfNewListing,
  type EtfGroupRow,
  type EtfPeriodSpec,
  type EtfRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, tone } from "./format";
import { BAR_TOP_N, GroupedBars, type BarSpec } from "./grouped-bars";
import { ListingView, ReportView } from "./new-listing-views";

// [국내상장 ETF] 왼쪽 질문 4개 · 가운데 답 · 오른쪽 오늘의 특이점.
//
// ★★2026-09-02 사용자 지시로 왼쪽을 **질문 박스 4개**로 바꿨다. 분류 목록·토글 대신
//   "무엇을 알고 싶은가" 를 문장으로 걸어 두고, 누르면 가운데가 그 답으로 바뀐다.
//   분류를 고르는 일은 아래 [구간별 개인 순매수 유입] 표가 계속 맡는다.
// ★박스 ①②는 신규상장(별도 엔드포인트), ③④는 이미 있는 분류 집계를 그대로 쓴다.
//   그래서 ①②만 따로 가져오고, ③④는 부모가 넘겨준 rows 로 그린다.

type ViewKey = "report" | "listing" | "flow" | "ret";

const QUESTIONS: { key: ViewKey; text: string; sub?: string }[] = [
  { key: "report", text: "신규 상장 ETF의 순매수 얼마나 붙었나?", sub: "화요일 전용" },
  { key: "listing", text: "신규 상장 임박 ETF 상세 정보" },
  { key: "flow", text: "ETF 순매수 몰리는 섹터 어디?" },
  { key: "ret", text: "수익률 좋은 ETF 는 어느 섹터?" },
];

// 순매수 뷰 — 겹치는 세 창(어제 ⊂ 1주 ⊂ 1개월)을 **거래일당 평균**으로 세운다.
const FLOW_BARS: BarSpec[] = [
  { key: "d", label: "어제", fill: "#e11d48" },
  { key: "1w", label: "1주", fill: "#4a7ab5" },
  { key: "1m", label: "1개월", fill: "#9bb3d1" },
];
// 수익률 뷰 — 이쪽은 나누지 않는다. 누적 수익률은 그 자체로 비교 가능하고,
// 일평균으로 쪼개면 복리를 단순 나눗셈으로 뭉개게 된다.
const RET_BARS: BarSpec[] = [
  { key: "d", label: "어제", fill: "#2f9e6e" },
  { key: "1w", label: "1주", fill: "#4a7ab5" },
  { key: "1m", label: "1개월", fill: "#9bb3d1" },
];

export function FlowCard({
  rows,
  periods,
  allEtfs,
  selected,
  onSelect,
  asof,
}: {
  rows: EtfGroupRow[];
  periods: EtfPeriodSpec[];
  allEtfs: EtfRow[];
  selected: string | null;
  onSelect: (key: string) => void;
  asof: string | null;
}) {
  const [view, setView] = useState<ViewKey>("flow");

  // 신규상장은 박스 ①②를 눌렀을 때만 받는다 — KRX 조회가 섞여 있어 첫 호출이 무겁다.
  // ★폴링은 **성적표를 보고 있을 때만** 돈다(사용자 지시 2026-09-02). 그 화면의
  //   등락률·거래대금·거래량이 CHECK 실시간이라 **10초**마다 새로 받는다.
  //   [신규 상장 임박] 은 DART 가 아침에 한 번 긁어오는 것 말고는 안 바뀌는 정적 모니터라
  //   폴링하지 않는다 — 같은 엔드포인트를 쓰므로 뷰에 따라 주기를 끈다.
  //   ⚠️한 사이클은 SMB stat 몇 번 + 메모리 조회다(KRX 목록은 하루 캐시). 10초를 더
  //     줄이면 SMB 왕복이 값보다 커진다.
  const { data: nl, isLoading: nlLoading, error: nlError } = useQuery({
    queryKey: ["etf-new-listing"],
    queryFn: getEtfNewListing,
    refetchInterval: view === "report" ? 10_000 : false,
    enabled: view === "report" || view === "listing",
  });

  const daysOf = (k: string) =>
    Math.max(periods.find((p) => p.key === k)?.days ?? 1, 1);

  const flowValue = (r: EtfGroupRow, k: string) => {
    const raw = r.net_cum[k as "d" | "1w" | "1m"];
    return raw == null ? null : raw / daysOf(k);
  };
  const retValue = (r: EtfGroupRow, k: string) =>
    r.ret_cum[k as "d" | "1w" | "1m"] ?? null;

  const flowRows = [...rows].sort(
    (a, b) => (b.net_cum.d ?? 0) - (a.net_cum.d ?? 0),
  );
  // 수익률 뷰는 종목 한둘짜리 분류가 상위를 먹지 않게 5종목 이상만 세운다.
  const retRows = [...rows]
    .filter((r) => r.n >= 5 && r.ret_cum.d != null)
    .sort((a, b) => (b.ret_cum.d ?? 0) - (a.ret_cum.d ?? 0));

  const headNote =
    view === "flow"
      ? `막대 = 거래일당 평균 유입액 · 어제 ⊂ 1주 ⊂ 1개월 · 상위 ${Math.min(BAR_TOP_N, flowRows.length)}/${flowRows.length}개`
      : view === "ret"
        ? `막대 = 시총가중 누적 수익률 · 5종목 이상 분류 · 상위 ${Math.min(BAR_TOP_N, retRows.length)}/${retRows.length}개`
        : nl?.note
          ? nl.note
          : "신규 상장";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          분류별 개인 순매수
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          {headNote}
          {asof ? ` · ${asof}` : ""}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-12">
        {/* ── 왼쪽: 질문 4개 — 세로 4등분, 문구 하나씩 ─────────────────────── */}
        <div className="col-span-12 grid grid-rows-4 border-r border-hairline lg:col-span-3">
          {QUESTIONS.map((q) => {
            const on = view === q.key;
            return (
              <button
                key={q.key}
                type="button"
                onClick={() => setView(q.key)}
                className={cn(
                  "flex min-h-0 flex-col items-center justify-center gap-1 border-b border-hairline px-3 text-center transition-colors last:border-b-0",
                  on ? "bg-ge-blue-bg" : "bg-canvas hover:bg-canvas-soft",
                )}
              >
                <span
                  className={cn(
                    "text-[19px] font-extrabold leading-tight tracking-tight",
                    on ? "text-ge-point" : "text-ge-navy",
                  )}
                >
                  {q.text}
                </span>
                {q.sub && (
                  <span className="text-[13px] font-bold text-ink-faint">
                    ({q.sub})
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* ── 가운데: 고른 질문의 답 ───────────────────────────────────────── */}
        <div className="col-span-12 flex min-h-0 flex-col border-r border-hairline lg:col-span-6">
          {view === "flow" && (
            <GroupedBars
              rows={flowRows}
              bars={FLOW_BARS}
              valueOf={flowValue}
              fmtAxis={(v) => fmtEok(v, false)}
              fmtValue={(v) => (v == null ? "—" : `${fmtEok(v)}/일`)}
              footNote="거래일당 평균 · 주말 제외(공휴일 미반영) · 두 줄 같은 축"
              selected={selected}
              onSelect={onSelect}
              tooltipExtra={(r, k) =>
                `총 ${fmtEok(r.net_cum[k as "d" | "1w" | "1m"])}`
              }
            />
          )}
          {view === "ret" && (
            <GroupedBars
              rows={retRows}
              bars={RET_BARS}
              valueOf={retValue}
              fmtAxis={(v) => `${(v * 100).toFixed(0)}%`}
              fmtValue={(v) => fmtPct(v, 2)}
              footNote="시총가중 누적 수익률 · 5종목 이상 분류 · 두 줄 같은 축"
              selected={selected}
              onSelect={onSelect}
              tooltipExtra={(r) => `${r.n}종목`}
            />
          )}
          {view === "report" &&
            (nlLoading && !nl ? (
              <div className="flex h-full items-center justify-center text-[12px] text-ink-faint">
                불러오는 중
              </div>
            ) : (
              <ReportView data={nl} error={nlError} />
            ))}
          {view === "listing" &&
            (nlLoading && !nl ? (
              <div className="flex h-full items-center justify-center text-[12px] text-ink-faint">
                불러오는 중 — KRX 상장 목록 조회에 몇 초 걸립니다
              </div>
            ) : (
              <ListingView data={nl} error={nlError} />
            ))}
        </div>

        {/* ── 오른쪽: 오늘의 특이점 ────────────────────────────────────────── */}
        <HighlightsPane etfs={allEtfs} />
      </div>
    </div>
  );
}

/* ── 오늘의 특이점 — 순매수 TOP5 · 수익률 TOP5 ───────────────────────────────
   ★TOP5 는 고른 분류가 아니라 **전 종목** 기준이다 — daily_analysis 리포트가 시장
     전체에서 뽑던 것과 같은 기준이라, 회의에서 쓰는 말과 어긋나지 않는다.
   ★'신규 상장' 칸은 왼쪽 박스 ①②가 훨씬 자세히 다루게 되어 뺐다(2026-09-02). */
function HighlightsPane({ etfs }: { etfs: EtfRow[] }) {
  const topFlow = [...etfs]
    .filter((e) => e.net_cum.d != null)
    .sort((a, b) => (b.net_cum.d ?? 0) - (a.net_cum.d ?? 0))
    .slice(0, 5);
  const topRet = [...etfs]
    .filter((e) => e.ret_cum.d != null)
    .sort((a, b) => (b.ret_cum.d ?? 0) - (a.ret_cum.d ?? 0))
    .slice(0, 5);

  return (
    <div className="col-span-12 flex min-h-0 flex-col lg:col-span-3">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Section title="당일 순매수 TOP 5" note="전 종목" />
        {topFlow.map((e, i) => (
          <RankRow key={e.code} i={i} e={e} lead="flow" />
        ))}
        <Section title="당일 수익률 TOP 5" note="전 종목" />
        {topRet.map((e, i) => (
          <RankRow key={e.code} i={i} e={e} lead="ret" />
        ))}
      </div>
    </div>
  );
}

function Section({ title, note }: { title: string; note: string }) {
  return (
    <div className="sticky top-0 z-10 flex items-baseline justify-between gap-2 border-b border-hairline bg-ge-th px-2.5 py-1">
      <span className="text-[10.5px] font-bold text-ink-secondary">{title}</span>
      <span className="shrink-0 text-[9.5px] font-semibold text-ink-faint">{note}</span>
    </div>
  );
}

function RankRow({ i, e, lead }: { i: number; e: EtfRow; lead: "flow" | "ret" }) {
  return (
    <div
      className="grid grid-cols-[13px_1fr_62px] items-center gap-x-1.5 border-b border-hairline/50 px-2.5 py-[5px]"
      title={`${e.code} · ${e.small || e.mid} · ${e.country}`}
    >
      <span className="text-[10px] font-extrabold tabular-nums text-ink-faint">
        {i + 1}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[11.5px] font-semibold text-ink">
          {e.name}
        </span>
        <span
          className={cn(
            "block truncate text-[9.5px] font-semibold tabular-nums",
            tone(lead === "flow" ? e.ret_cum.d : e.net_cum.d),
          )}
        >
          {lead === "flow"
            ? `등락 ${fmtPct(e.ret_cum.d, 1)}`
            : `순매수 ${fmtEok(e.net_cum.d)}`}
        </span>
      </span>
      <span
        className={cn(
          "text-right text-[11.5px] font-bold tabular-nums",
          tone(lead === "flow" ? e.net_cum.d : e.ret_cum.d),
        )}
      >
        {lead === "flow" ? fmtEok(e.net_cum.d) : fmtPct(e.ret_cum.d, 1)}
      </span>
    </div>
  );
}
