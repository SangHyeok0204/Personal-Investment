"use client";

import { useState } from "react";
import type { EtfGroupRow, EtfIntervalSpec, EtfIvKey, EtfRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fmtEok, fmtPct, tone } from "./format";

// [국내상장 ETF] 구간 분해 + 고른 분류의 ETF — **한 카드 두 칸**.
//
// ★★왼쪽 표가 이 페이지의 HISTORICAL 이다. 원천 워크북은 매일 덮어써서 과거가 없지만,
//   시트가 1주·1개월·3개월·6개월 **누적**을 같이 주므로 누적끼리 빼면 겹치지 않는 네
//   구간이 나온다(계산은 서버 — etf_class._etf_metrics, 합 항등식은 테스트로 고정).
// ★열 순서는 **왼쪽이 과거**다. 시트 순서(1w→6m)를 그대로 쓰면 시간이 거꾸로 흐른다.
// ★2026-09-01 사용자 지시로 막대를 걷어내고 숫자만 남겼다. 왼쪽 카드의 막대와 역할이
//   겹쳤고, 이 표에서 보고 싶은 건 "언제 얼마"라는 값 자체다.
// ★두 칸은 각자 스크롤한다(사용자 지시). 카드 하나로 묶되 스크롤은 분리 — 왼쪽에서
//   분류를 고르는 동안 오른쪽 종목 목록의 위치가 따라 움직이면 안 된다.
// ★2026-09-02 사용자 지시로 **머리글 클릭 정렬**을 붙였다. 기본은 **최근 1주 내림차순** —
//   "지금 어디로 들어오고 있나" 가 이 표를 여는 첫 질문이다.

/** 정렬 키. 'total' = 순매수 유입액(6개월 누적), 나머지는 구간 키. */
type SortKey = "label" | "total" | EtfIvKey;
type SortDir = "asc" | "desc";

function sortValue(r: EtfGroupRow, k: SortKey): number | null {
  if (k === "label") return null;
  if (k === "total") return r.net_cum["6m"];
  return r.net_iv[k];
}

/** 머리글 한 칸. 누르면 정렬, 같은 칸을 다시 누르면 방향이 뒤집힌다. */
function SortHead({
  label,
  sub,
  sortKey,
  active,
  dir,
  onSort,
  align = "right",
}: {
  label: string;
  sub?: string;
  sortKey: SortKey;
  active: boolean;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      title={`${label} 기준 정렬`}
      className={cn(
        "group flex min-w-0 cursor-pointer flex-col rounded px-1 py-0.5 transition-colors hover:bg-ge-blue-bg",
        align === "right" ? "items-end" : "items-start",
      )}
    >
      <span
        className={cn(
          "flex items-center gap-0.5 whitespace-nowrap leading-tight",
          active ? "text-ge-point" : "text-ink-secondary",
        )}
      >
        {label}
        <span
          className={cn(
            "text-[9px] leading-none",
            active ? "opacity-100" : "opacity-0 group-hover:opacity-40",
          )}
        >
          {active ? (dir === "desc" ? "▼" : "▲") : "▼"}
        </span>
      </span>
      {sub && (
        <span className="block text-[9.5px] font-medium text-ink-faint">{sub}</span>
      )}
    </button>
  );
}


export function BreakdownCard({
  rows,
  intervals,
  selected,
  onSelect,
  selectedRow,
  etfs,
}: {
  rows: EtfGroupRow[];
  intervals: EtfIntervalSpec[];
  selected: string | null;
  onSelect: (key: string) => void;
  selectedRow: EtfGroupRow | null;
  etfs: EtfRow[];
}) {
  // 왼쪽이 과거 — 3~6개월 → 1~3개월 → 1주~1개월 → 최근 1주
  const cols = [...intervals].reverse();

  // 기본값 = 최근 1주 내림차순(사용자 지시). 같은 칸을 다시 누르면 방향이 뒤집히고,
  // 다른 칸을 누르면 그 칸의 큰 값부터 본다(숫자 칸에서 흔한 의도). 분류는 가나다순.
  const [sortKey, setSortKey] = useState<SortKey>("1w");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(k);
    setSortDir(k === "label" ? "asc" : "desc");
  };

  const ranked = [...rows]
    .filter((r) => r.net_cum["6m"] != null)
    .sort((a, b) => {
      if (sortKey === "label") {
        const c = a.label.localeCompare(b.label, "ko");
        return sortDir === "asc" ? c : -c;
      }
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      // ★결측은 방향과 무관하게 **항상 뒤로**. 오름차순으로 뒤집었을 때 빈 칸이 맨 위로
      //   올라오면 "가장 작은 값" 자리에 값이 없는 행이 앉아 순위를 잘못 읽게 된다.
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return sortDir === "asc" ? va - vb : vb - va;
    });

  const detail = [...etfs].sort(
    (a, b) => (b.net_cum.d ?? 0) - (a.net_cum.d ?? 0),
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-hairline bg-ge-header px-4 py-2.5">
        <h2 className="text-[14px] font-extrabold tracking-tight text-white">
          구간별 개인 순매수 유입
        </h2>
        <span className="shrink-0 text-[11px] font-semibold text-white/70">
          겹치지 않는 4구간 · 합계 = 6개월 유입액
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-12">
        {/* ── 왼쪽: 구간 분해 표 ──────────────────────────────────────────── */}
        <div className="col-span-12 flex min-h-0 flex-col border-r border-hairline lg:col-span-7">
          {/* 머리글 = 정렬 버튼. 기본은 최근 1주 내림차순. */}
          <div className="grid grid-cols-[minmax(0,1.5fr)_92px_repeat(4,minmax(0,1fr))] items-end gap-x-2 border-b border-hairline bg-ge-th px-2 py-1.5 text-[11px] font-bold">
            <SortHead
              label="분류"
              sortKey="label"
              active={sortKey === "label"}
              dir={sortDir}
              onSort={onSort}
              align="left"
            />
            <SortHead
              label="순매수 유입액"
              sortKey="total"
              active={sortKey === "total"}
              dir={sortDir}
              onSort={onSort}
            />
            {cols.map((c) => (
              <SortHead
                key={c.key}
                label={c.label}
                sub={`${c.start?.slice(5).replace("-", "/")}~${c.end
                  ?.slice(5)
                  .replace("-", "/")}`}
                sortKey={c.key as EtfIvKey}
                active={sortKey === c.key}
                dir={sortDir}
                onSort={onSort}
              />
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {ranked.map((r) => {
              const on = selected === r.key;
              return (
                <button
                  key={r.key}
                  type="button"
                  onClick={() => onSelect(r.key)}
                  className={cn(
                    "grid w-full grid-cols-[minmax(0,1.5fr)_92px_repeat(4,minmax(0,1fr))] items-center gap-x-2 border-b border-hairline/50 px-3 py-[6px] text-left transition-colors",
                    on ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
                  )}
                >
                  <span className="min-w-0">
                    <span
                      className={cn(
                        "block truncate text-[12.5px]",
                        on ? "font-extrabold text-ge-point" : "font-bold text-ink",
                      )}
                    >
                      {r.label}
                    </span>
                    {r.path.length > 0 && (
                      <span className="block truncate text-[10px] font-medium text-ink-faint">
                        {r.path.join(" · ")}
                      </span>
                    )}
                  </span>
                  <span
                    className={cn(
                      "text-right text-[12.5px] font-extrabold tabular-nums",
                      tone(r.net_cum["6m"]),
                    )}
                  >
                    {fmtEok(r.net_cum["6m"])}
                  </span>
                  {cols.map((c) => (
                    <span
                      key={c.key}
                      className={cn(
                        "text-right text-[12px] font-semibold tabular-nums",
                        tone(r.net_iv[c.key as EtfIvKey]),
                      )}
                    >
                      {fmtEok(r.net_iv[c.key as EtfIvKey])}
                    </span>
                  ))}
                </button>
              );
            })}
          </div>
        </div>

        {/* ── 오른쪽: 고른 분류의 ETF (스크롤 분리) ───────────────────────── */}
        <div className="col-span-12 flex min-h-0 flex-col lg:col-span-5">
          <div className="flex items-baseline justify-between gap-2 border-b border-hairline bg-ge-th px-3 py-1.5">
            <span className="min-w-0 truncate text-[12px] font-extrabold text-ge-navy">
              {selectedRow ? selectedRow.label : "분류를 고르세요"}
            </span>
            {selectedRow && (
              <span className="shrink-0 text-[10.5px] font-semibold text-ink-faint">
                {selectedRow.n}종목 · 시총 {fmtEok(selectedRow.mcap, false)}
              </span>
            )}
          </div>
          <div className="grid grid-cols-[1fr_78px_66px] items-center gap-x-2 border-b border-hairline bg-ge-th/60 px-3 py-1 text-[10.5px] font-bold text-ink-secondary">
            <span>ETF</span>
            <span className="text-right">개인 순매수</span>
            <span className="text-right">수익률</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {detail.length === 0 && (
              <div className="px-3 py-6 text-center text-[12px] text-ink-faint">
                왼쪽에서 분류를 고르면 그 안의 ETF 가 나옵니다
              </div>
            )}
            {detail.map((e) => (
              <div
                key={e.code}
                className="grid grid-cols-[1fr_78px_66px] items-center gap-x-2 border-b border-hairline/50 px-3 py-[5px]"
                title={`${e.code} · ${e.small || e.mid} · ${e.country}`}
              >
                <span className="min-w-0 truncate text-[12px] font-semibold text-ink">
                  {e.interest && (
                    <span className="mr-1 rounded bg-ge-blue-bg px-1 align-middle text-[9px] font-extrabold text-ge-point">
                      관심
                    </span>
                  )}
                  {e.name}
                </span>
                <span
                  className={cn(
                    "text-right text-[11.5px] font-bold tabular-nums",
                    tone(e.net_cum.d),
                  )}
                >
                  {fmtEok(e.net_cum.d)}
                </span>
                <span
                  className={cn(
                    "text-right text-[11.5px] font-extrabold tabular-nums",
                    tone(e.ret_cum.d),
                  )}
                >
                  {fmtPct(e.ret_cum.d, 1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
