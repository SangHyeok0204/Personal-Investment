"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { Cell, DataTable, StubCard } from "@/components/stub";
import {
  addWatchlist,
  getWatchlist,
  importHoldingsToWatchlist,
  removeWatchlist,
  type WatchlistItem,
} from "@/lib/api";

// 시장 리서치 · 관심종목 탭 — 읽기 전용 시세 표.
//
// ★2026-09-27 계획 S2(§3.1): 예전 `/watchlist` 보드(등락 막대·목표가 카드·상세
//   모달·메모/목표가 입력)를 걷어내고 **표 하나**로 다시 만들었다. 남긴 관리
//   기능은 티커 추가 · 보유 담기 · 행 삭제뿐이다.
//   ⚠️백엔드의 메모/목표가 쓰기 엔드포인트와 DB 컬럼은 그대로 둔다(UI 에서만 뺐다).
//
// ⚠️52주 위치는 **야후에서 따로** 받는다(1시간 캐시). 토스 일봉에는 52주 범위가
//   없어서, 가격과 묶어 두면 장중 내내 "—" 가 된다.
// ⚠️시세가 없는 종목도 행은 남긴다("—"). 정렬해도 늘 맨 아래.
//
// ★2026-10-04 5D/20D/60D — **거래일** 변화율(서버 계산, 1시간 캐시). 마지막 **완결**
//   일 종가 vs 5·20·60거래일 전 종가다. 당일 등락만 실시간이다. 이력이 모자라면 "—".
// ★2026-10-04 행 색 = 밸류체인 분류 L1 기준색(왼쪽 띠 + 아주 옅은 배경 + 티커 옆 칩).
//   분류에 없는 티커(ETF 등)는 색이 없다 — 추측해 칠하지 않는다.

function pct(value: string | null, digits = 2): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

function price(value: string | null, currency: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const body = n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency === "KRW" ? `₩${body}` : `$${body}`;
}

function toneOfRate(value: string | null): "up" | "down" | undefined {
  if (value == null) return undefined;
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

const COLUMNS = [
  "종목",
  "현재가",
  "전일 종가",
  "당일 등락",
  "5D",
  "20D",
  "60D",
  "52주 저점",
  "52주 고점",
  "52주 위치",
  "",
];
const ALIGN: ("left" | "right")[] = [
  "left",
  "right",
  "right",
  "right",
  "right",
  "right",
  "right",
  "right",
  "right",
  "left",
  "right",
];

/** 정렬 칸별 값. 이름은 문자열, 나머지는 숫자(없으면 null → 늘 맨 아래). */
function sortValue(item: WatchlistItem, column: number): string | number | null {
  const num = (v: string | null) => {
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  switch (column) {
    case 0:
      return item.asset_name ?? item.ticker;
    case 1:
      return num(item.price);
    case 2:
      return num(item.previous_close);
    case 3:
      return num(item.change_rate);
    case 4:
      return num(item.change_5d);
    case 5:
      return num(item.change_20d);
    case 6:
      return num(item.change_60d);
    case 7:
      return num(item.fifty_two_week_low);
    case 8:
      return num(item.fifty_two_week_high);
    case 9:
      return num(item.fifty_two_week_position);
    default:
      return null;
  }
}

export function WatchlistTab() {
  const live = useLiveQueryOptions();
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  // 기본: 당일 등락 내림차순.
  const [sort, setSort] = useState<{ column: number; dir: "asc" | "desc" }>({
    column: 3,
    dir: "desc",
  });

  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    staleTime: 3_000,
    ...live,
  });

  // 어떤 변경이든 서버가 **목록 전체**를 돌려준다 — 그대로 캐시에 넣는다.
  const settle = (data: unknown) => queryClient.setQueryData(["watchlist"], data);

  const add = useMutation({
    mutationFn: (value: string) => addWatchlist({ ticker: value }),
    onSuccess: (data) => {
      settle(data);
      setTicker("");
      setError(null);
    },
    onError: (err: unknown) =>
      setError(err instanceof Error ? err.message : "추가하지 못했습니다"),
  });

  const drop = useMutation({
    mutationFn: removeWatchlist,
    onSuccess: (data) => {
      settle(data);
      setConfirmId(null);
    },
  });

  const pull = useMutation({
    mutationFn: importHoldingsToWatchlist,
    onSuccess: settle,
  });

  const items = useMemo(() => watchlist.data?.items ?? [], [watchlist.data]);

  const sorted = useMemo(() => {
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...items].sort((a, b) => {
      const va = sortValue(a, sort.column);
      const vb = sortValue(b, sort.column);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb), "ko") * sign;
      }
      return (va - vb) * sign;
    });
  }, [items, sort]);

  const up = items.filter((i) => Number(i.change_rate ?? 0) > 0).length;
  const down = items.filter((i) => Number(i.change_rate ?? 0) < 0).length;
  const mover = useMemo(
    () =>
      items
        .filter((i) => i.change_rate != null)
        .sort(
          (a, b) =>
            Math.abs(Number(b.change_rate)) - Math.abs(Number(a.change_rate)),
        )[0],
    [items],
  );
  const noQuote = items.filter((i) => i.price == null).length;
  // 범례 — 지금 표에 있는 L1 만, 종목 수 많은 순.
  const legend = useMemo(() => {
    const seen = new Map<string, { color: string; n: number }>();
    for (const i of items) {
      if (!i.l1_name || !i.l1_color) continue;
      const hit = seen.get(i.l1_name);
      if (hit) hit.n += 1;
      else seen.set(i.l1_name, { color: i.l1_color, n: 1 });
    }
    return [...seen.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [items]);

  const onSort = (column: number) => {
    if (column === COLUMNS.length - 1) return; // 삭제 칸
    setSort((prev) =>
      prev.column === column
        ? { column, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { column, dir: column === 0 ? "asc" : "desc" },
    );
  };

  return (
    <StubCard
      title="관심종목"
      subtitle="실시간 시세 · 칸 제목을 누르면 정렬"
      className="flex-1"
      scrollBody
      action={
        <div className="flex items-center gap-1.5">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && ticker.trim()) add.mutate(ticker);
            }}
            placeholder="티커 추가"
            aria-label="관심종목에 추가할 종목코드"
            className="w-[88px] rounded bg-white/90 px-1.5 py-0.5 text-[11px] font-bold text-ge-header placeholder:font-medium placeholder:text-ink-faint focus:outline-none"
          />
          <button
            type="button"
            onClick={() => ticker.trim() && add.mutate(ticker)}
            disabled={add.isPending || !ticker.trim()}
            className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold text-white transition-colors hover:bg-white/30 disabled:opacity-40"
          >
            추가
          </button>
          <button
            type="button"
            onClick={() => pull.mutate()}
            disabled={pull.isPending}
            className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold text-white transition-colors hover:bg-white/30 disabled:opacity-40"
            title="보유 종목을 관심종목으로 담는다"
          >
            보유 담기
          </button>
        </div>
      }
    >
      {error && (
        <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-bold text-amber-900">
          {error}
        </p>
      )}

      {/* 예전 요약 타일 4개를 한 줄로 줄였다. 오른쪽은 L1 색 범례. */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <p className="text-[11px] font-medium text-ink-muted">
        {watchlist.isLoading ? (
          "불러오는 중…"
        ) : (
          <>
            <b className="text-ink">{items.length}</b>종목 · 오늘{" "}
            <b className="text-bid">상승 {up}</b> ·{" "}
            <b className="text-ask">하락 {down}</b>
            {mover && (
              <>
                {" "}
                · 최대 변동 {mover.asset_name ?? mover.ticker}{" "}
                <b
                  className={
                    toneOfRate(mover.change_rate) === "up"
                      ? "text-bid"
                      : toneOfRate(mover.change_rate) === "down"
                        ? "text-ask"
                        : "text-ink"
                  }
                >
                  {pct(mover.change_rate)}
                </b>
              </>
            )}
            {noQuote > 0 && <> · 시세 없음 {noQuote}</>}
          </>
        )}
      </p>
      {legend.length > 0 && (
        <p
          className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[10px] font-semibold text-ink-muted"
          title="행 색 = 산업 밸류체인 분류 L1. 분류에 없는 종목(ETF 등)은 색 없음"
        >
          {legend.map(([name, { color, n }]) => (
            <span key={name} className="inline-flex items-center gap-1">
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: color }}
              />
              {name} {n}
            </span>
          ))}
        </p>
      )}
      </div>

      <DataTable
        columns={COLUMNS}
        align={ALIGN}
        sort={{ column: sort.column, dir: sort.dir, onSort }}
        empty={
          watchlist.isLoading
            ? "불러오는 중…"
            : "관심종목 없음 · 티커 추가 또는 보유 담기"
        }
      >
        {sorted.map((i) => (
          <tr
            key={i.id}
            className="border-b border-hairline transition-colors hover:bg-canvas-soft"
            // L1 색을 아주 옅게(hex 알파 0x0D ≈ 5%). 글자 대비를 해치지 않는 선.
            style={i.l1_color ? { backgroundColor: `${i.l1_color}0D` } : undefined}
          >
            <Cell
              left
              strong
              className="py-1.5"
              // 왼쪽 3px 띠 — 테두리 대신 inset 그림자라 칸 폭이 변하지 않는다.
              style={
                i.l1_color
                  ? { boxShadow: `inset 3px 0 0 ${i.l1_color}` }
                  : undefined
              }
            >
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2 w-2 shrink-0 rounded-sm"
                  style={i.l1_color ? { backgroundColor: i.l1_color } : undefined}
                  title={i.l1_name ?? "밸류체인 분류 없음"}
                  aria-label={i.l1_name ?? undefined}
                />
                <span className="max-w-[180px] truncate">
                  {i.asset_name ?? i.ticker}
                </span>
                <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                  {i.ticker}
                </span>
              </span>
            </Cell>
            <Cell strong className="py-1.5">
              {price(i.price, i.currency)}
            </Cell>
            <Cell className="py-1.5">{price(i.previous_close, i.currency)}</Cell>
            <Cell tone={toneOfRate(i.change_rate)} className="py-1.5 font-bold">
              {pct(i.change_rate)}
            </Cell>
            {[i.change_5d, i.change_20d, i.change_60d].map((v, k) => (
              <Cell key={k} tone={toneOfRate(v)} className="py-1.5">
                {pct(v)}
              </Cell>
            ))}
            <Cell className="py-1.5">
              {price(i.fifty_two_week_low, i.currency)}
            </Cell>
            <Cell className="py-1.5">
              {price(i.fifty_two_week_high, i.currency)}
            </Cell>
            <Cell left className="py-1.5">
              <RangeBar position={i.fifty_two_week_position} />
            </Cell>
            <Cell className="py-1.5">
              {confirmId === i.id ? (
                <span className="inline-flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={drop.isPending}
                    onClick={() => drop.mutate(i.id)}
                    className="rounded bg-ask px-1.5 py-0.5 text-[10px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    삭제
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmId(null)}
                    className="text-[10px] font-bold text-ink-muted hover:text-ink"
                  >
                    취소
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmId(i.id)}
                  aria-label={`${i.asset_name ?? i.ticker} 관심종목에서 빼기`}
                  title="관심종목에서 빼기"
                  className="rounded px-1 text-[13px] font-bold leading-none text-ink-faint transition-colors hover:text-ask"
                >
                  ×
                </button>
              )}
            </Cell>
          </tr>
        ))}
      </DataTable>
    </StubCard>
  );
}

/** 52주 저점~고점 사이 위치를 막대로. 값이 없으면 막대를 그리지 않는다. */
function RangeBar({ position }: { position: string | null }) {
  if (position == null) {
    return <span className="text-[11px] text-ink-faint">—</span>;
  }
  const ratio = Math.min(1, Math.max(0, Number(position)));
  return (
    <span className="flex items-center gap-1.5">
      <span className="relative h-1.5 w-[54px] overflow-hidden rounded-full bg-canvas-soft">
        <span
          className="absolute top-0 h-full w-[3px] rounded-full bg-ge-point"
          style={{ left: `calc(${ratio * 100}% - 1.5px)` }}
        />
      </span>
      <span className="text-[10px] font-bold tabular-nums text-ink-muted">
        {(ratio * 100).toFixed(0)}%
      </span>
    </span>
  );
}
