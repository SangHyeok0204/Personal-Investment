"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  getInclusion,
  type Inclusion,
  type InclusionEvent,
  type InclusionHolding,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 편입비 — 매매 이력을 되감아 만든 종목별 원가 비중과 편입/청산 이벤트.
//
// ★**원가(USD) 기준**이다. 평가금액 기준이 아니다. 과거 시점의 평가 비중을 내려면
//   종목별 과거 주가가 있어야 하는데 저장하지 않는다. 없는 가격을 만들어 쓰는 대신
//   축을 바꿨다 — "내가 각 종목에 넣은 돈의 비중"은 매매 이력만으로 정확하다.
//
// ★STALE 행을 숨기지 않는다. 매매 이력에 매도가 빠져 이미 판 종목이 보유 중으로
//   남는 경우가 실제로 있었다(SKHY). 비중 분모에서는 빼되 목록에는 남긴다.

const KIND_LABEL: Record<InclusionEvent["kind"], string> = {
  ENTRY: "신규 편입",
  ADD: "추가 매수",
  TRIM: "일부 매도",
  EXIT: "전량 청산",
};

const KIND_STYLE: Record<InclusionEvent["kind"], string> = {
  ENTRY: "bg-ge-blue-bg text-ge-point",
  ADD: "bg-canvas-soft text-ink-secondary",
  TRIM: "bg-canvas-soft text-ink-secondary",
  EXIT: "bg-hairline text-ink-muted",
};

function pct(value: string | null | undefined, digits = 1): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}

function usd(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function days(n: number): string {
  if (n >= 365) return `${(n / 365).toFixed(1)}년`;
  return `${n}일`;
}

export default function InclusionPage() {
  const { accountId } = useAccount();
  const live = useLiveQueryOptions();
  const [picked, setPicked] = useState<InclusionHolding | null>(null);
  const [eventsOpen, setEventsOpen] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["inclusion", accountId],
    queryFn: () => getInclusion(accountId),
    ...live,
  });

  const open = useMemo(
    () => (data?.holdings ?? []).filter((h) => h.status === "OPEN"),
    [data],
  );
  const stale = useMemo(
    () => (data?.holdings ?? []).filter((h) => h.status === "STALE"),
    [data],
  );
  const closed = useMemo(
    () => (data?.holdings ?? []).filter((h) => h.status === "CLOSED"),
    [data],
  );

  // 최근 편입/청산만 뽑아 본다 — 추가매수/일부매도는 편입 '구조'를 바꾸지 않는다.
  const structural = useMemo(
    () => (data?.events ?? []).filter((e) => e.kind === "ENTRY" || e.kind === "EXIT"),
    [data],
  );

  const avgHold = useMemo(() => {
    if (open.length === 0) return null;
    return Math.round(
      open.reduce((sum, h) => sum + h.holding_days, 0) / open.length,
    );
  }, [open]);

  return (
    <>
      <Topbar title="편입비" subtitle="매매 이력 복원 · 원가(USD) 기준" />
      <PageContainer fit>
        {isError && !isLoading && <NotConnectedBanner what="매매 이력" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="보유 종목"
            value={data ? `${data.open_count}` : null}
            hint={data?.first_trade_date ? `${data.first_trade_date}부터` : undefined}
            loading={isLoading}
          />
          <StatTile
            label="누적 투자원금"
            value={data?.total_cost ? usd(data.total_cost) : null}
            hint="보유 종목 원가 합 (USD)"
            loading={isLoading}
          />
          <StatTile
            label="평균 보유기간"
            value={avgHold == null ? null : days(avgHold)}
            hint={`청산 ${closed.length}종목`}
            loading={isLoading}
          />
          <StatTile
            label="편입·청산"
            value={data ? `${structural.length}회` : null}
            hint="눌러서 전체 이력 보기"
            actionHint="눌러서 전체 이력 보기"
            onClick={() => setEventsOpen(true)}
            loading={isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="편입 현황"
            subtitle={`원가 비중 · ${data?.currency ?? "USD"}`}
            scrollBody
          >
            {isLoading ? (
              <Empty text="불러오는 중" />
            ) : (
              <DataTable
                columns={["종목", "편입비", "원가", "보유기간"]}
                empty="매매 이력이 없습니다"
              >
                {open.map((h) => (
                  <tr
                    key={h.ticker}
                    onClick={() => setPicked(h)}
                    className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                  >
                    <Cell left strong>
                      <span className="flex items-center gap-1.5">
                        <span className="truncate">{h.asset_name ?? h.ticker}</span>
                        <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                          {h.ticker}
                        </span>
                      </span>
                    </Cell>
                    <Cell strong>{pct(h.weight)}</Cell>
                    <Cell>{usd(h.cost)}</Cell>
                    <Cell>{days(h.holding_days)}</Cell>
                  </tr>
                ))}
                {stale.map((h) => (
                  <tr
                    key={h.ticker}
                    onClick={() => setPicked(h)}
                    className="cursor-pointer border-b border-hairline bg-amber-50/60 transition-colors hover:bg-amber-50"
                  >
                    <Cell left strong>
                      <span className="flex items-center gap-1.5">
                        <span className="truncate">{h.asset_name ?? h.ticker}</span>
                        <span className="shrink-0 rounded bg-amber-200 px-1 text-[10px] font-bold text-amber-900">
                          이력 누락
                        </span>
                      </span>
                    </Cell>
                    <Cell tone="muted">제외</Cell>
                    <Cell tone="muted">{usd(h.cost)}</Cell>
                    <Cell tone="muted">{days(h.holding_days)}</Cell>
                  </tr>
                ))}
              </DataTable>
            )}
          </StubCard>

          <StubCard
            title="최근 편입 · 청산"
            subtitle={`${structural.length}회`}
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setEventsOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                전체 이력
              </button>
            }
          >
            {isLoading ? (
              <Empty text="불러오는 중" />
            ) : structural.length === 0 ? (
              <Empty text="편입·청산 이력이 없습니다" />
            ) : (
              <ul className="space-y-1.5">
                {structural.slice(0, 14).map((e, i) => (
                  <li
                    key={`${e.event_date}-${e.ticker}-${i}`}
                    className="flex items-center gap-2 border-b border-hairline pb-1.5 last:border-b-0"
                  >
                    <span className="w-[62px] shrink-0 text-[11px] tabular-nums text-ink-muted">
                      {e.event_date.slice(2)}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold",
                        KIND_STYLE[e.kind],
                      )}
                    >
                      {KIND_LABEL[e.kind]}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12px] font-bold text-ink">
                      {e.asset_name ?? e.ticker}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-ink-secondary">
                      {usd(e.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={eventsOpen}
        onClose={() => setEventsOpen(false)}
        title="편입 · 청산 전체 이력"
        subtitle={
          data?.first_trade_date
            ? `${data.first_trade_date} ~ ${data.last_trade_date}`
            : undefined
        }
      >
        <EventTable events={data?.events ?? []} />
      </Modal>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.asset_name ?? picked?.ticker ?? ""}
        subtitle={picked?.ticker}
      >
        {picked && <HoldingDetail item={picked} data={data} />}
      </Modal>
    </>
  );
}

function EventTable({ events }: { events: InclusionEvent[] }) {
  if (events.length === 0) return <Empty text="이력이 없습니다" />;
  return (
    <div className="max-h-[60vh] overflow-y-auto">
      <DataTable
        columns={["날짜", "구분", "종목", "수량", "금액", "비중 변화", "보유"]}
        align={["left", "left", "left", "right", "right", "right", "right"]}
      >
        {events.map((e, i) => (
          <tr
            key={`${e.event_date}-${e.ticker}-${i}`}
            className="border-b border-hairline"
          >
            <Cell left>{e.event_date}</Cell>
            <Cell left>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-bold",
                  KIND_STYLE[e.kind],
                )}
              >
                {KIND_LABEL[e.kind]}
              </span>
            </Cell>
            <Cell left strong>
              {e.ticker}
            </Cell>
            <Cell>{Number(e.quantity).toLocaleString()}</Cell>
            <Cell>{usd(e.amount)}</Cell>
            <Cell>
              {pct(e.weight_before)} → {pct(e.weight_after)}
            </Cell>
            <Cell tone="muted">{e.holdings_after}</Cell>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

function HoldingDetail({
  item,
  data,
}: {
  item: InclusionHolding;
  data?: Inclusion;
}) {
  const rows: [string, string][] = [
    ["상태", item.status === "OPEN" ? "보유 중" : item.status === "STALE" ? "매매 이력 누락" : "청산"],
    ["최초 편입", item.first_entry],
    ["청산", item.exited_at ?? "—"],
    ["보유기간", days(item.holding_days)],
    ["투자원금", usd(item.cost)],
    ["편입비", item.weight ? pct(item.weight, 2) : "—"],
    ["매수 / 매도", `${item.buy_count}회 / ${item.sell_count}회`],
  ];
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between border-b border-hairline py-2"
          >
            <dt className="text-[12px] text-ink-secondary">{label}</dt>
            <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
          </div>
        ))}
      </dl>

      {item.status === "STALE" && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3">
          <p className="text-[12px] font-bold text-amber-900">
            매매 이력에 매도가 빠져 있습니다
          </p>
          <p className="mt-1 text-[11px] leading-snug text-amber-800">
            실현손익에는 {item.exited_at} 청산으로 기록돼 있는데, 그 매도 체결만
            매매 이력에 없습니다(체결 이력이 며칠 뒤처져 들어오는 것으로 보입니다).
            복원만으로는 아직 보유 중으로 보이기 때문에{" "}
            <strong>편입비 분모에서 뺐습니다</strong>. 숨기지 않고 남겨 둔 건
            이력 자체가 사라지면 안 되기 때문입니다.
          </p>
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-ink-muted">
        편입비 = 이 종목 투자원금 ÷ 보유 종목 투자원금 합
        {data?.total_cost ? ` (${usd(data.total_cost)})` : ""}.
        <strong> 평가금액이 아니라 원가 기준</strong>입니다 — 과거 시점의 평가
        비중을 내려면 종목별 과거 주가가 있어야 하는데 저장하지 않습니다. 원가는
        이동평균법으로, 매도할 때 그 시점 평균단가만큼 덜어냅니다.
      </p>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
