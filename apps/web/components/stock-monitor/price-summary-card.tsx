"use client";

import { useQuery } from "@tanstack/react-query";
import { getPriceBoard, type PriceBoard, type PriceBoardRow, type PriceCatKey } from "@/lib/api";
import type { PriceSel } from "@/components/stock-monitor/price-tree-card";
import { cn } from "@/lib/utils";

// [수익률 요약 표] — 종목 모니터 우하단 1칸. 차트에서 뺀 달력 앵커 지표(DtD~YtD)가
// 여기로 왔다(사용자 지시 2026-08-31). '주목해야할 지수' 카드가 있던 자리다.
//
// ★★역할 분담이 이 화면의 뼈대다: **발견은 표, 확인은 차트**. 추세가 꺾인 시장을
//   찾는 건 차트를 눈으로 훑어서가 아니라 정렬된 숫자에서 한다 — 그래서 묶음 모드는
//   3M 내림차순으로 세우고 값에 배경 틴트를 깐다. 차트는 거기서 고른 하나가 정말
//   꺾였는지 보는 도구다.
//
// ★달력 앵커(DtD·WtD·MtD·YtD)와 롤링(1M·3M·6M·1Y)을 **둘 다** 싣는다. 달력 앵커는
//   "이번 달 얼마"를 답하고, 롤링은 시장끼리 비교할 때 쓴다 — 월초에는 모든 시장의
//   MtD 가 0 근처로 뭉쳐 비교가 안 되기 때문이다. 두 묶음 사이에 선을 하나 긋는다.
//
// ★★쿼리 키를 지표 리스트 카드와 **일부러 똑같이** 맞췄다(["price-board", cat]).
//   react-query 가 캐시를 공유해 요청이 한 번만 나간다 — 이 카드는 네트워크를 전혀
//   더 쓰지 않는다. 바꿀 일이 있으면 두 카드를 같이 봐야 한다.
//
// ★1칸은 좁고 길다(≈280×480). 그래서 지수 하나를 고르면 기간을 **세로로** 쌓고
//   (가로로 8열을 놓으면 열당 35px 라 안 들어간다), 묶음을 고르면 행=시장 / 열은
//   1M·3M·YtD 셋까지만 놓는다.

const POLL_MS = 600_000; // 지표 리스트 카드와 같은 주기(같은 쿼리라 실제로는 공유)

// 표시 순서 = 이 배열 순서. 달력 앵커 4개 → 구분선 → 롤링 4개.
const CAL_ROWS = [
  { key: "dtd", label: "DtD" },
  { key: "wtd", label: "WtD" },
  { key: "mtd", label: "MtD" },
  { key: "ytd", label: "YtD" },
] as const;
const ROLL_ROWS = [
  { key: "r1m", label: "1M" },
  { key: "r3m", label: "3M" },
  { key: "r6m", label: "6M" },
  { key: "r1y", label: "1Y" },
] as const;

// 묶음 모드에서 보여줄 열 — 1칸 폭에 이름까지 넣으면 셋이 한계다.
const GROUP_COLS = [
  { key: "r1m", label: "1M" },
  { key: "r3m", label: "3M" },
  { key: "ytd", label: "YtD" },
] as const;

type RowKey = keyof Pick<
  PriceBoardRow,
  "dtd" | "wtd" | "mtd" | "ytd" | "r1m" | "r3m" | "r6m" | "r1y"
>;

function tone(v: number | null): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

// 배경 틴트 — 같은 열 안에서 |값| 이 가장 큰 것을 1로 놓고 옅게 깐다. 정렬된 표에서
// 눈이 먼저 가야 할 곳을 만드는 게 목적이라 진하게 칠하지 않는다(최대 0.18).
function tint(v: number | null, max: number): string | undefined {
  if (v == null || !Number.isFinite(v) || v === 0 || max <= 0) return undefined;
  const a = Math.min(1, Math.abs(v) / max) * 0.18;
  return v > 0 ? `rgba(225,29,72,${a.toFixed(3)})` : `rgba(37,99,235,${a.toFixed(3)})`;
}

function fmt(v: number | null, isYield: boolean): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v > 0 ? "+" : "";
  return isYield ? `${s}${v.toFixed(0)}` : `${s}${v.toFixed(1)}`;
}

export function PriceSummaryCard({
  cat,
  sel,
}: {
  cat: PriceCatKey;
  sel: PriceSel | null;
}) {
  const { data, isLoading, isError } = useQuery<PriceBoard>({
    queryKey: ["price-board", cat],
    queryFn: () => getPriceBoard(cat),
    refetchInterval: POLL_MS,
  });
  const isYield = !!data?.is_yield;
  const unit = isYield ? "bp" : "%";
  const rows = data?.rows ?? [];

  const leafRow =
    sel?.kind === "leaf" ? rows.find((r) => r.key === sel.key) ?? null : null;
  // 묶음은 3M 내림차순 — 표의 존재 이유가 '누가 이기고 있나'를 세우는 것이다.
  const groupRows =
    sel?.kind === "group"
      ? rows
          .filter((r) => r.group === sel.l1 && r.sub_group === sel.l2)
          .slice()
          .sort((a, b) => (b.r3m ?? -Infinity) - (a.r3m ?? -Infinity))
      : [];

  const title =
    sel?.kind === "leaf"
      ? leafRow?.label ?? "수익률 요약"
      : sel?.kind === "group"
        ? sel.label
        : "수익률 요약";

  return (
    // 마지막 열의 아래 칸 — 화면 오른쪽·아래 끝이라 테두리를 두르지 않는다.
    // (위 ETF 카드가 border-b 로 이미 경계를 긋는다.)
    <section className="lg:col-span-1 lg:col-start-6 flex min-h-0 flex-col bg-canvas">
      <header className="flex shrink-0 items-baseline gap-1.5 bg-ge-header px-2 py-1.5">
        <h2 className="shrink-0 text-[12.5px] font-extrabold text-white">수익률 요약</h2>
        <span className="min-w-0 truncate text-[10px] text-white/70">{title}</span>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums text-white/60">{unit}</span>
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : !sel ? (
        <Center msg="왼쪽 목록에서 지수 또는 묶음을 고르면 기간별 수익률이 표시됩니다." />
      ) : sel.kind === "leaf" ? (
        leafRow ? (
          <LeafTable row={leafRow} isYield={isYield} />
        ) : (
          <Center msg="이 지수는 아직 시트에 값이 없습니다." tone="text-amber-600" />
        )
      ) : groupRows.length ? (
        <GroupTable rows={groupRows} isYield={isYield} />
      ) : (
        <Center msg="이 묶음은 아직 시트에 값이 없습니다." tone="text-amber-600" />
      )}
    </section>
  );
}

// 지수 하나 — 기간을 세로로 쌓는다. 막대는 이 표 안에서 |값| 최대를 1로 잡은
// 상대 길이다(가운데가 0, 좌우로 뻗는다). 절대 스케일이 아니라 "무엇이 큰가"를 본다.
function LeafTable({ row, isYield }: { row: PriceBoardRow; isYield: boolean }) {
  const all = [...CAL_ROWS, ...ROLL_ROWS].map((m) => row[m.key as RowKey]);
  const max = Math.max(...all.map((v) => (v == null ? 0 : Math.abs(v))), 0);

  const line = (m: { key: string; label: string }) => {
    const v = row[m.key as RowKey];
    const w = max > 0 && v != null ? (Math.abs(v) / max) * 50 : 0;
    return (
      <div key={m.key} className="flex flex-1 items-center gap-1.5 px-2.5">
        <span className="w-[26px] shrink-0 text-[11px] font-bold text-ink-muted">{m.label}</span>
        <span
          className={cn(
            "w-[52px] shrink-0 text-right text-[12.5px] font-extrabold tabular-nums",
            tone(v ?? null),
          )}
        >
          {fmt(v ?? null, isYield)}
        </span>
        {/* 가운데 0 에서 좌우로 뻗는 막대 */}
        <span className="relative h-[7px] min-w-0 flex-1 rounded-sm bg-canvas-soft">
          <span className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
          {v != null && Number.isFinite(v) && v !== 0 ? (
            <span
              className={cn(
                "absolute inset-y-0 rounded-sm",
                v > 0 ? "left-1/2 bg-rose-500/70" : "right-1/2 bg-blue-500/70",
              )}
              style={{ width: `${w}%` }}
            />
          ) : null}
        </span>
      </div>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col py-1">
      {CAL_ROWS.map(line)}
      {/* 달력 앵커 / 롤링 경계 — 성격이 다른 두 묶음이라 눈으로 갈라 준다. */}
      <div className="my-1 flex shrink-0 items-center gap-1.5 px-2.5">
        <span className="h-px flex-1 bg-hairline" />
        <span className="shrink-0 text-[9px] font-bold tracking-wide text-slate-400">
          롤링 (비교용)
        </span>
        <span className="h-px flex-1 bg-hairline" />
      </div>
      {ROLL_ROWS.map(line)}
      <div className="shrink-0 px-2.5 pt-1 text-[9px] leading-tight text-slate-400">
        위 4개는 달력 앵커(전일·7일·전월말·전년말) · 아래 4개는 t 기준 롤링
      </div>
    </div>
  );
}

// 묶음 — 행이 시장이고 3M 내림차순이다. 열 안에서 상대적으로 큰 값에 배경이 깔린다.
function GroupTable({ rows, isYield }: { rows: PriceBoardRow[]; isYield: boolean }) {
  // 틴트 기준은 **열마다** 따로 잡는다 — YtD 와 1M 은 스케일이 몇 배씩 달라서
  // 표 전체 최대로 정규화하면 1M 열이 통째로 하얗게 죽는다.
  const maxOf = (k: string) =>
    Math.max(...rows.map((r) => Math.abs((r[k as RowKey] as number | null) ?? 0)), 0);
  const maxes = Object.fromEntries(GROUP_COLS.map((c) => [c.key, maxOf(c.key)]));

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <table className="w-full border-collapse">
        <thead className="sticky top-0 z-10 bg-canvas">
          <tr className="border-b border-hairline">
            <th className="px-1.5 py-1 text-left text-[10px] font-bold text-ink-muted">시장</th>
            {GROUP_COLS.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "px-1 py-1 text-right text-[10px] font-bold",
                  c.key === "r3m" ? "text-ge-point" : "text-ink-muted",
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-hairline/50">
              <td
                className="max-w-0 truncate px-1.5 py-[3px] text-[10.5px] font-semibold text-ink"
                title={r.sub ? `${r.label} · ${r.sub}` : r.label}
              >
                {r.label}
              </td>
              {GROUP_COLS.map((c) => {
                const v = (r[c.key as RowKey] as number | null) ?? null;
                return (
                  <td
                    key={c.key}
                    className={cn(
                      "w-[46px] px-1 py-[3px] text-right text-[10.5px] font-bold tabular-nums",
                      tone(v),
                    )}
                    style={{ background: tint(v, maxes[c.key]) }}
                  >
                    {fmt(v, isYield)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-1.5 py-1 text-[9px] leading-tight text-slate-400">
        3M 내림차순 · 배경은 열 안에서의 상대 크기
      </div>
    </div>
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
