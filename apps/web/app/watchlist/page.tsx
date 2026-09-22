"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import {
  addWatchlist,
  getWatchlist,
  importHoldingsToWatchlist,
  removeWatchlist,
  updateWatchlist,
  deleteRebalanceTarget,
  putRebalanceTarget,
  type WatchlistItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 관심종목 보드.
//
// ★사용자가 처음부터 말한 것: "toss api 활용해서 관심 있는 종목 모니터하는 것".
//   시세 소스(토스/야후)가 붙은 뒤에야 의미가 생겨 이제 만들었다.
//
// ★보유 종목을 여기 복제하지 않는다. 서버가 조회할 때마다 current_positions 를
//   보고 `held` 만 채워 준다 — 팔면 자동으로 '관심'으로 바뀐다.
//
// ⚠️52주 위치는 **야후에서 따로** 받는다(1시간 캐시). 정규장 중 주 시세 소스는
//   토스인데 토스 일봉에는 52주 범위가 없어서, 가격과 묶어 두면 장중 내내
//   "—" 가 된다. 값의 변동 주기가 다르면 받는 주기도 달라야 한다.

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

export default function WatchlistPage() {
  const live = useLiveQueryOptions();
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [picked, setPicked] = useState<WatchlistItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    staleTime: 3_000,
    ...live,
  });

  // 어떤 변경이든 서버가 **목록 전체**를 돌려준다. 그걸 그대로 캐시에 넣으면
  // 추가 조회 없이 화면이 맞춰진다(낙관적 갱신의 어긋남도 없다).
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
      setPicked(null);
    },
  });

  const edit = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof updateWatchlist>[1] }) =>
      updateWatchlist(id, body),
    onSuccess: (data) => {
      settle(data);
      setPicked(null);
    },
  });

  // 종목 하나의 리밸런싱 목표만 고친다 — 세워 둔 다른 목표를 건드리지 않는다.
  const setWeight = useMutation({
    mutationFn: ({ ticker, weight }: { ticker: string; weight: string | null }) =>
      weight == null
        ? deleteRebalanceTarget(ticker)
        : putRebalanceTarget(ticker, weight),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["watchlist"] });
      void queryClient.invalidateQueries({ queryKey: ["rebalance"] });
      setPicked(null);
    },
  });

  const pull = useMutation({
    mutationFn: importHoldingsToWatchlist,
    onSuccess: settle,
  });

  const items = watchlist.data?.items ?? [];
  const heldCount = items.filter((i) => i.held).length;

  const movers = useMemo(() => {
    const rated = items.filter((i) => i.change_rate != null);
    return [...rated].sort(
      (a, b) => Math.abs(Number(b.change_rate)) - Math.abs(Number(a.change_rate)),
    );
  }, [items]);

  // 목표가·손절가를 걸어 둔 종목만. 안 걸어 둔 게 대부분이라 따로 모은다.
  const targeted = useMemo(
    // ⚠️목표 비중만 적어 둔 종목도 들어와야 한다 — 빠지면 "저장했는데 안
    //   보인다"가 된다.
    () =>
      items.filter(
        (i) =>
          i.target_price != null ||
          i.stop_price != null ||
          i.rebalance_weight != null,
      ),
    [items],
  );

  return (
    <>
      <Topbar title="관심종목" subtitle="내가 보는 종목 보드" showAccountContext={false} />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="관심종목"
            value={watchlist.data ? `${items.length}` : null}
            hint={`보유 ${heldCount} · 미보유 ${items.length - heldCount}`}
            loading={watchlist.isLoading}
          />
          <StatTile
            label="오늘 상승"
            value={
              watchlist.data
                ? `${items.filter((i) => Number(i.change_rate ?? 0) > 0).length}`
                : null
            }
            hint="전일 종가 대비"
            accent="up"
            loading={watchlist.isLoading}
          />
          <StatTile
            label="오늘 하락"
            value={
              watchlist.data
                ? `${items.filter((i) => Number(i.change_rate ?? 0) < 0).length}`
                : null
            }
            hint="전일 종가 대비"
            accent="down"
            loading={watchlist.isLoading}
          />
          <StatTile
            label="최대 변동"
            value={movers[0] ? pct(movers[0].change_rate) : null}
            hint={movers[0] ? (movers[0].asset_name ?? movers[0].ticker) : "—"}
            accent="auto"
            loading={watchlist.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="관심종목"
            subtitle={
              watchlist.data?.missing.length
                ? `시세 없음 ${watchlist.data.missing.length}종목`
                : `${items.length}종목 · 실시간`
            }
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
            <DataTable
              columns={["종목", "현재가", "당일", "52주 위치", "메모"]}
              align={["left", "right", "right", "left", "left"]}
              empty={
                watchlist.isLoading
                  ? "불러오는 중…"
                  : "관심종목이 없습니다 — 티커를 추가하거나 '보유 담기'를 누르세요"
              }
            >
              {items.map((i) => (
                <tr
                  key={i.id}
                  onClick={() => setPicked(i)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[140px] truncate">
                        {i.asset_name ?? i.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {i.ticker}
                      </span>
                      {i.held && (
                        <span className="shrink-0 rounded bg-ge-blue-bg px-1 text-[9px] font-bold text-ge-point">
                          보유
                        </span>
                      )}
                    </span>
                  </Cell>
                  <Cell strong>{price(i.price, i.currency)}</Cell>
                  <Cell tone={toneOfRate(i.change_rate)}>{pct(i.change_rate)}</Cell>
                  <Cell left>
                    <RangeBar position={i.fifty_two_week_position} />
                  </Cell>
                  <Cell left tone="muted">
                    <span className="block max-w-[150px] truncate">
                      {i.memo ?? "—"}
                    </span>
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          {/* ★"언제 살까"(목표가)와 "사면 얼마나"(목표 비중)를 한 표에서 본다. */}
          <StubCard
            title="목표가 · 목표 비중"
            subtitle={`${targeted.length}종목`}
            scrollBody
          >
            {targeted.length === 0 ? (
              <div className="flex h-full items-center justify-center px-4 text-center">
                <span className="text-[12px] font-semibold leading-relaxed text-ink-faint">
                  걸어 둔 목표가가 없습니다.
                  <br />
                  종목을 눌러 목표가·손절가·목표 비중을 설정하세요.
                </span>
              </div>
            ) : (
              <DataTable
                columns={["종목", "목표가", "손절가", "목표 비중"]}
                align={["left", "right", "right", "right"]}
              >
                {targeted.map((i) => (
                  <tr
                    key={i.id}
                    onClick={() => setPicked(i)}
                    className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                  >
                    <Cell left strong>
                      <span className="block max-w-[110px] truncate">
                        {i.asset_name ?? i.ticker}
                      </span>
                    </Cell>
                    <Cell tone={i.to_target == null ? "muted" : "up"}>
                      {i.target_price == null ? (
                        "—"
                      ) : (
                        <>
                          {price(i.target_price, i.currency)}
                          <span className="ml-1 text-[10px] font-bold">
                            {pct(i.to_target, 1)}
                          </span>
                        </>
                      )}
                    </Cell>
                    <Cell tone={i.to_stop == null ? "muted" : "down"}>
                      {i.stop_price == null ? (
                        "—"
                      ) : (
                        <>
                          {price(i.stop_price, i.currency)}
                          <span className="ml-1 text-[10px] font-bold">
                            {pct(i.to_stop, 1)}
                          </span>
                        </>
                      )}
                    </Cell>
                    {/* ⚠️목표를 안 세운 것과 "0% 로 두겠다"는 다른 말이다. */}
                    <Cell
                      strong={i.rebalance_weight != null}
                      tone={i.rebalance_weight == null ? "muted" : undefined}
                    >
                      {i.rebalance_weight == null
                        ? "—"
                        : `${(Number(i.rebalance_weight) * 100).toFixed(1)}%`}
                    </Cell>
                  </tr>
                ))}
              </DataTable>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.asset_name ?? picked?.ticker ?? ""}
        subtitle={picked?.ticker}
      >
        {picked && (
          <WatchDetail
            item={picked}
            saving={edit.isPending}
            savingWeight={setWeight.isPending}
            removing={drop.isPending}
            onSave={(body) => edit.mutate({ id: picked.id, body })}
            onSaveWeight={(w) =>
              setWeight.mutate({ ticker: picked.ticker, weight: w })
            }
            onRemove={() => drop.mutate(picked.id)}
          />
        )}
      </Modal>
    </>
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

function WatchDetail({
  item,
  saving,
  savingWeight,
  removing,
  onSave,
  onSaveWeight,
  onRemove,
}: {
  item: WatchlistItem;
  saving: boolean;
  savingWeight: boolean;
  removing: boolean;
  onSave: (body: { memo: string | null; target_price: string | null; stop_price: string | null }) => void;
  onSaveWeight: (weight: string | null) => void;
  onRemove: () => void;
}) {
  const [memo, setMemo] = useState(item.memo ?? "");
  const [target, setTarget] = useState(item.target_price ?? "");
  const [stop, setStop] = useState(item.stop_price ?? "");
  const [confirming, setConfirming] = useState(false);
  // ★관심종목과 리밸런싱을 잇는 자리. "사고 싶다"와 "사면 몇 %"가 따로 놀면
  //   목표를 세워 놓고도 관심종목에서 안 보인다.
  const [weight, setWeight] = useState(
    item.rebalance_weight == null
      ? ""
      : String(Number((Number(item.rebalance_weight) * 100).toFixed(4))),
  );

  const facts: [string, string][] = [
    ["현재가", price(item.price, item.currency)],
    ["전일 종가", price(item.previous_close, item.currency)],
    ["당일 등락", pct(item.change_rate)],
    ["52주 저점", price(item.fifty_two_week_low, item.currency)],
    ["52주 고점", price(item.fifty_two_week_high, item.currency)],
    ["52주 위치", item.fifty_two_week_position == null ? "—" : `${(Number(item.fifty_two_week_position) * 100).toFixed(0)}%`],
    ["보유 여부", item.held ? "보유 중" : "미보유"],
    [
      "리밸런싱 목표",
      // ⚠️목표가 없으면 "—" 다. 0% 로 적으면 "0% 로 두겠다"로 읽힌다.
      item.rebalance_weight == null
        ? "—"
        : `${(Number(item.rebalance_weight) * 100).toFixed(2)}%`,
    ],
    ["시세 소스", item.source ?? "—"],
  ];

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        {facts.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between border-b border-hairline py-2"
          >
            <dt className="text-[12px] text-ink-secondary">{label}</dt>
            <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-2">
        <Field label="메모">
          <input
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
            placeholder="왜 보고 있는지"
            className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] focus:border-ge-point focus:outline-none"
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={`목표가 (${item.currency ?? "USD"})`}>
            <input
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              inputMode="decimal"
              placeholder="예: 260"
              className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] tabular-nums focus:border-ge-point focus:outline-none"
            />
          </Field>
          <Field label={`손절가 (${item.currency ?? "USD"})`}>
            <input
              value={stop}
              onChange={(e) => setStop(e.target.value)}
              inputMode="decimal"
              placeholder="예: 180"
              className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] tabular-nums focus:border-ge-point focus:outline-none"
            />
          </Field>
        </div>

        {/* ★관심종목 ↔ 리밸런싱을 잇는 자리. 목표가는 "언제 살까"이고 이건
            "사면 얼마나 담을까"다 — 둘 다 적어 둬야 계획이 된다. */}
        <Field label="사게 되면 몇 % (리밸런싱 목표)">
          <div className="flex items-center gap-1.5">
            <input
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              inputMode="decimal"
              placeholder="예: 5"
              className="w-24 rounded-lg border border-hairline px-2.5 py-1.5 text-right text-[12px] tabular-nums focus:border-ge-point focus:outline-none"
            />
            <span className="text-[12px] font-bold text-ink-faint">%</span>
            <button
              type="button"
              disabled={savingWeight}
              onClick={() =>
                // 빈칸은 "목표를 지운다"는 뜻이다 — 0 으로 저장하면
                // "0% 로 두겠다"가 되어 다른 말이 된다.
                onSaveWeight(
                  weight.trim() === ""
                    ? null
                    : String((Number(weight) || 0) / 100),
                )
              }
              className="ml-auto rounded-lg bg-ge-navy px-3 py-1.5 text-[11px] font-bold text-white transition-colors hover:bg-ge-navy/90 disabled:opacity-50"
            >
              {savingWeight ? "저장 중…" : "목표 비중 저장"}
            </button>
          </div>
          <span className="mt-1 block text-[11px] leading-snug text-ink-muted">
            리밸런싱 화면의 목표로 바로 들어갑니다. 비워서 저장하면 목표가
            지워집니다 — <strong>0% 와 다른 말입니다.</strong>
          </span>
        </Field>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() =>
            onSave({
              memo: memo.trim() === "" ? null : memo.trim(),
              // 빈칸은 "지운다"는 뜻이다 — 0 으로 저장하면 목표가 0원이 된다.
              target_price: target.trim() === "" ? null : target.trim(),
              stop_price: stop.trim() === "" ? null : stop.trim(),
            })
          }
          className="rounded-lg bg-ge-point px-3.5 py-1.5 text-[12px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "저장 중…" : "저장"}
        </button>

        {/* 삭제는 한 번 더 묻는다 — 되돌릴 수 없다. */}
        {confirming ? (
          <>
            <span className="text-[11px] font-bold text-ink-secondary">
              정말 삭제할까요?
            </span>
            <button
              type="button"
              disabled={removing}
              onClick={onRemove}
              className="rounded-lg bg-ask px-3 py-1.5 text-[12px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              삭제
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-[12px] font-bold text-ink-muted hover:text-ink"
            >
              취소
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="ml-auto text-[12px] font-bold text-ink-muted hover:text-ask"
          >
            관심종목에서 빼기
          </button>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-bold text-ink-muted">{label}</span>
      {children}
    </label>
  );
}
