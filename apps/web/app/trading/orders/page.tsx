"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, NotConnectedBanner, StatTile, StubCard } from "@/components/stub";
import { getOrders, type OrderItem, type OrderStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

// 주문 내역 — 체결 이력이 감추는 것들.
//
// ★체결(/trading/executions)은 **성사된 것**만 보여준다. 여기에는 미체결·취소와
//   지정가 대비 체결가(슬리피지)가 남는다. 실측: 주문 145건 중 55건(38%)이
//   한 번도 체결되지 않았다 — 체결 화면만 보면 존재조차 모르는 기록이다.
//
// ★같은 종목을 몇 초 간격으로 여러 번 주문한 흔적이 드러난다. 실측 예:
//   2026-09-18 SKHY 매도를 19초 동안 183.80 → 183.77 → 183.73 으로 내리다가
//   183.69 에 체결됐다. "호가를 따라 내렸다"는 행동이 여기에만 남는다.

const STATUS_LABEL: Record<OrderStatus, string> = {
  FILLED: "체결",
  PARTIAL: "부분체결",
  UNFILLED: "미체결",
  CANCELLED: "취소",
};

const STATUS_STYLE: Record<OrderStatus, string> = {
  FILLED: "bg-ge-blue-bg text-ge-point",
  PARTIAL: "bg-amber-100 text-amber-900",
  UNFILLED: "bg-canvas-soft text-ink-muted",
  CANCELLED: "bg-hairline text-ink-faint",
};

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 365, label: "1년" },
  { id: 730, label: "전체" },
];

function pct(value: string | null, digits = 2): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

function money(value: string | null, currency: string): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const body = n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency === "KRW" ? `₩${body}` : `$${body}`;
}

function qty(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

export default function OrdersPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(730);
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [picked, setPicked] = useState<OrderItem | null>(null);

  const orders = useQuery({
    queryKey: ["orders", accountId, days, status],
    queryFn: () => getOrders(accountId, days, status),
    staleTime: 30_000,
  });

  const data = orders.data;
  const items = data?.items ?? [];

  // 미체결이 많았던 종목 — "사고 싶었는데 못 산" 목록.
  const missedByTicker = useMemo(() => {
    const map = new Map<string, { ticker: string; name: string | null; count: number }>();
    for (const o of items) {
      if (o.status !== "UNFILLED") continue;
      const row = map.get(o.ticker) ?? { ticker: o.ticker, name: o.asset_name, count: 0 };
      row.count += 1;
      map.set(o.ticker, row);
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [items]);

  const filters = (
    <div className="flex flex-wrap items-center gap-1.5">
      {RANGES.map((r) => (
        <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
          {r.label}
        </Chip>
      ))}
      <span className="mx-0.5 h-3.5 w-px bg-white/25" />
      <Chip active={status === null} onClick={() => setStatus(null)}>
        전체
      </Chip>
      {(["FILLED", "UNFILLED"] as OrderStatus[]).map((s) => (
        <Chip key={s} active={status === s} onClick={() => setStatus(s)}>
          {STATUS_LABEL[s]}
        </Chip>
      ))}
    </div>
  );

  return (
    <>
      <Topbar title="주문/미체결" subtitle="체결 이력이 감추는 것들" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 주문내역" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="총 주문"
            value={data ? `${data.total}` : null}
            hint={
              data?.first_order_date
                ? `${data.first_order_date} ~ ${data.last_order_date}`
                : undefined
            }
            loading={orders.isLoading}
          />
          <StatTile
            label="체결률"
            value={data?.fill_rate ? pct(data.fill_rate, 1).replace("+", "") : null}
            hint={data ? `체결 ${data.filled} / 취소 제외 ${data.filled + data.partial + data.unfilled}` : "취소는 분모에서 제외"}
            loading={orders.isLoading}
          />
          <StatTile
            label="미체결"
            value={data ? `${data.unfilled}` : null}
            hint="주문했지만 체결되지 않음"
            accent="down"
            loading={orders.isLoading}
          />
          <StatTile
            label="평균 체결개선"
            value={data?.avg_improvement ? pct(data.avg_improvement, 3) : null}
            hint="지정가 대비 (양수 = 유리)"
            accent="auto"
            loading={orders.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="주문 목록"
            subtitle={`${items.length}건 · 최근순`}
            action={filters}
            scrollBody
          >
            <DataTable
              columns={["주문일", "종목", "구분", "상태", "주문가", "체결가"]}
              align={["left", "left", "left", "left", "right", "right"]}
              empty={
                orders.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "해당 조건의 주문이 없습니다"
                    : "계좌를 연동하면 주문 내역이 표시됩니다"
              }
            >
              {items.map((o) => (
                <tr
                  key={o.id}
                  onClick={() => setPicked(o)}
                  className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left tone="muted">
                    <span className="flex items-baseline gap-1.5">
                      <span>{o.order_date}</span>
                      {o.order_time && (
                        <span className="text-[10px] text-ink-faint">
                          {o.order_time.slice(0, 5)}
                        </span>
                      )}
                    </span>
                  </Cell>
                  <Cell left strong>
                    <span className="block max-w-[130px] truncate">
                      {o.asset_name ?? o.ticker}
                    </span>
                  </Cell>
                  <Cell left>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold",
                        o.side === "BUY" ? "bg-bid-soft text-bid" : "bg-ask-soft text-ask",
                      )}
                    >
                      {o.side === "BUY" ? "매수" : "매도"}
                    </span>
                  </Cell>
                  <Cell left>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-bold",
                        STATUS_STYLE[o.status],
                      )}
                    >
                      {STATUS_LABEL[o.status]}
                    </span>
                  </Cell>
                  <Cell>{money(o.order_price, o.currency)}</Cell>
                  <Cell strong>{money(o.filled_price, o.currency)}</Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard
            title="못 산 종목"
            subtitle={`미체결 ${missedByTicker.length}종목`}
            scrollBody
          >
            {orders.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : missedByTicker.length === 0 ? (
              <Empty text="미체결 주문이 없습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  주문했지만 체결되지 않은 횟수입니다. 체결 화면에는 남지 않습니다.
                </p>
                <DataTable columns={["종목", "미체결"]} align={["left", "right"]}>
                  {missedByTicker.map((m) => (
                    <tr key={m.ticker} className="border-b border-hairline">
                      <Cell left strong>
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[110px] truncate">
                            {m.name ?? m.ticker}
                          </span>
                          <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                            {m.ticker}
                          </span>
                        </span>
                      </Cell>
                      <Cell strong>{m.count}회</Cell>
                    </tr>
                  ))}
                </DataTable>
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.asset_name ?? picked?.ticker ?? ""}
        subtitle={
          picked
            ? `${picked.order_date} ${picked.order_time ?? ""} · ${picked.side === "BUY" ? "매수" : "매도"} · ${STATUS_LABEL[picked.status]}`
            : undefined
        }
      >
        {picked && <OrderDetail order={picked} />}
      </Modal>
    </>
  );
}

function OrderDetail({ order: o }: { order: OrderItem }) {
  const rows: [string, string][] = [
    ["종목코드", o.ticker],
    ["주문번호", o.order_no],
    ["주문유형", o.order_type ?? "—"],
    ["주문 채널", o.channel ?? "—"],
    ["주문수량", qty(o.order_quantity)],
    ["체결수량", qty(o.filled_quantity)],
    ["취소수량", qty(o.cancelled_quantity)],
    ["미체결 잔량", qty(o.remaining_quantity)],
    ["주문가", money(o.order_price, o.currency)],
    ["체결가", money(o.filled_price, o.currency)],
    ["체결금액", money(o.filled_amount, o.currency)],
    ["체결개선", pct(o.improvement, 3)],
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
      <p className="text-[11px] leading-relaxed text-ink-muted">
        <strong>체결개선</strong>은 지정가 대비 체결가가 얼마나 유리했는지입니다 —
        매수는 싸게, 매도는 비싸게 체결될수록 양수입니다. 미체결이면 체결가가 없어
        계산하지 않습니다(0 으로 두면 &quot;정확히 지정가에 체결&quot;로 읽힙니다).
      </p>
    </div>
  );
}

function Chip({
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
      aria-pressed={active}
      // 카드 헤더(짙은 갈색) 위에 올라가므로 흰 계열로 맞춘다.
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
        active
          ? "bg-white/90 text-ge-header"
          : "text-white/60 hover:bg-white/15 hover:text-white",
      )}
    >
      {children}
    </button>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
