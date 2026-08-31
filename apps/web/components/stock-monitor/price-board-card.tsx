"use client";

import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPriceBoard, type PriceBoard, type PriceCatKey } from "@/lib/api";
import { EMDASH } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [가격 모니터 · 표] — 가운데 2번째 칸, 위아래 2행(1×2). 자산군 하나의 전 시장을
// Price·DtD·WtD·MtD·YtD 로 세운다. 원천은 주간가격모니터 price_monitor.xlsx.
//
// ★상단 [버튼 탭]이 자산군을 갈아끼운다(주식·채권·원자재·환·비트코인). 같은 상태를
//   오른쪽 차트 카드가 함께 보므로 탭·선택은 페이지가 들고 있고 여기는 받아 쓴다.
// ★★채권은 **bp**, 나머지는 **%** — payload 의 is_yield 로 갈린다. 금리의 %변화율은
//   의미가 없고 마이너스 구간에서 부호가 뒤집힌다(생성기가 겪은 함정).
// ★행 클릭 = 오른쪽 차트의 대상 변경. 표가 "전부 한눈에", 차트가 "하나 자세히"를 맡는다.

const POLL_MS = 600_000; // 원천이 일단위(주간 수기 갱신)라 자주 물을 이유가 없다

// 상승 빨강 / 하락 파랑 — 화면 공통 등락 관례(format.moveColor 와 같은 짝).
function tone(v: number | null): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

function fmtChg(v: number | null, isYield: boolean): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  const s = v > 0 ? "+" : "";
  return isYield ? `${s}${v.toFixed(1)}` : `${s}${v.toFixed(2)}`;
}

function fmtPrice(v: number, isYield: boolean): string {
  if (isYield) return `${v.toFixed(2)}%`;
  const d = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 10 ? 2 : 4;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function PriceBoardCard({
  cat,
  onCat,
  selected,
  onSelect,
}: {
  cat: PriceCatKey;
  onCat: (c: PriceCatKey) => void;
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const { data, isLoading, isError } = useQuery<PriceBoard>({
    queryKey: ["price-board", cat], // 차트 카드와 같은 키 → fetch 는 한 번
    queryFn: () => getPriceBoard(cat),
    refetchInterval: POLL_MS,
  });
  const rows = data?.rows ?? [];
  const isYield = !!data?.is_yield;
  const cats = data?.categories ?? [
    { key: "equity" as PriceCatKey, label: "주식" },
    { key: "bond" as PriceCatKey, label: "채권" },
    { key: "commodity" as PriceCatKey, label: "원자재" },
    { key: "fx" as PriceCatKey, label: "환" },
    { key: "crypto" as PriceCatKey, label: "비트코인" },
  ];
  const activeKey = selected ?? rows[0]?.key ?? null;

  return (
    // col-start-2 를 못 박는다 — 왼쪽 실시간 급등락(1칸) 다음 자리가 고정이어야
    // 오른쪽 차트(3~4칸)와 열이 맞는다. row-span-2 라 위아래를 통으로 쓴다.
    <section className="lg:col-start-2 lg:row-span-2 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas">
      <header className="flex shrink-0 flex-col gap-1 border-b border-hairline px-2 py-1.5">
        <div className="flex items-baseline gap-1.5">
          <h2 className="shrink-0 text-[12.5px] font-extrabold text-ink">가격 모니터</h2>
          {data?.asof ? (
            <span className="ml-auto shrink-0 text-[10px] tabular-nums text-slate-400">
              {data.asof.slice(5)}
            </span>
          ) : null}
        </div>
        {/* 자산군 탭 — 칸이 좁아 5개가 두 줄로 접힌다(줄바꿈 허용). */}
        <div className="flex flex-wrap gap-0.5">
          {cats.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => onCat(c.key)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10.5px] font-bold transition-colors",
                cat === c.key
                  ? "bg-ge-navy text-white"
                  : "bg-canvas-soft text-ink-muted hover:bg-ge-blue-bg",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : rows.length === 0 ? (
        <Center
          msg={data?.note ?? "price_monitor.xlsx 판독 대기 중입니다."}
          tone={data?.note ? "text-amber-600" : undefined}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <table className="w-full border-collapse text-[10.5px] tabular-nums">
            <thead className="sticky top-0 z-10 bg-canvas">
              <tr className="text-ink-muted">
                <th className="px-1 py-0.5 text-left font-semibold">시장</th>
                <th className="px-0.5 py-0.5 text-right font-semibold">DtD</th>
                <th className="px-0.5 py-0.5 text-right font-semibold">WtD</th>
                <th className="px-0.5 py-0.5 text-right font-semibold">MtD</th>
                <th className="px-1 py-0.5 text-right font-semibold">YtD</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const newGroup = r.group && (i === 0 || rows[i - 1].group !== r.group);
                return (
                  <Fragment key={r.key}>
                    {newGroup ? (
                      <tr>
                        <td
                          colSpan={5}
                          className="bg-canvas-soft px-1 py-[1px] text-[9.5px] font-bold text-ink-muted"
                        >
                          {r.group}
                        </td>
                      </tr>
                    ) : null}
                    <tr
                      onClick={() => onSelect(r.key)}
                      title={`${r.label}${r.sub ? ` · ${r.sub}` : ""} — ${fmtPrice(r.price, isYield)} (${r.asof})`}
                      className={cn(
                        "cursor-pointer border-b border-hairline/50 transition-colors",
                        activeKey === r.key ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
                      )}
                    >
                      <td className="max-w-0 truncate px-1 py-[2px] font-semibold text-ink">
                        {r.label}
                      </td>
                      <td className={cn("px-0.5 py-[2px] text-right font-bold", tone(r.dtd))}>
                        {fmtChg(r.dtd, isYield)}
                      </td>
                      <td className={cn("px-0.5 py-[2px] text-right", tone(r.wtd))}>
                        {fmtChg(r.wtd, isYield)}
                      </td>
                      <td className={cn("px-0.5 py-[2px] text-right", tone(r.mtd))}>
                        {fmtChg(r.mtd, isYield)}
                      </td>
                      <td className={cn("px-1 py-[2px] text-right font-bold", tone(r.ytd))}>
                        {fmtChg(r.ytd, isYield)}
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 단위를 바닥에 한 번 적는다 — 채권만 bp 라 헷갈릴 자리다. */}
      <div className="shrink-0 border-t border-hairline px-2 py-0.5 text-[9.5px] text-slate-400">
        단위 {isYield ? "bp (금리 변화폭)" : "% (수익률)"} · 행 클릭 = 차트 전환
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-3 text-center">
      <span className={cn("text-[11px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
