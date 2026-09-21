"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { SeriesChart } from "@/components/charts/series-chart";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, NotConnectedBanner, StatTile, StubCard } from "@/components/stub";
import { getCashflow, type Cashflow } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 입출금 — "내가 넣은 돈이 얼마고 지금 얼마인가".
//
// ★수익률 화면과 **다른 질문**에 답한다. 성과 분석은 "얼마나 잘 굴렸나"(TWR),
//   여기는 "실제로 얼마가 늘었나"(금액). 입금 시점이 다르면 두 숫자는 갈린다 —
//   늦게 넣은 돈이 많으면 수익률은 좋은데 금액 증감은 작을 수 있다.
//
// ⚠️현재 자산은 **일별 데이터 기준일**의 값이다. 자산 현황 화면은 실시간 시세로
//   계산하므로 숫자가 다르다. 기준일을 화면에 박아 두지 않으면 "어느 쪽이
//   맞느냐"는 질문이 계속 생긴다.
//
// ⚠️입출금 날짜는 증권사 장부 그대로다. 수익률 계산에서 쓰는 날짜 보정
//   (reconcile_flows)을 여기 적용하지 않는다 — 출납 기록은 원본이어야 대조가 된다.

export default function TransfersPage() {
  const { accountId, connected } = useAccount();
  const [trendOpen, setTrendOpen] = useState(false);

  const cashflow = useQuery({
    queryKey: ["cashflow", accountId],
    queryFn: () => getCashflow(accountId),
    staleTime: 60_000,
  });

  const data = cashflow.data;
  const events = data?.events ?? [];

  // 누적 순입금 곡선 — 언제 얼마씩 넣었는지가 한눈에 보인다.
  const cumulative = useMemo(() => {
    if (!data) return [];
    let running = Number(data.opening_balance_krw ?? 0);
    // events 는 최근순이라 되돌려서 쌓는다.
    return [...events].reverse().map((e) => {
      running += Number(e.net_krw);
      return { date: e.base_date, value: running };
    });
  }, [data, events]);

  const biggest = useMemo(
    () =>
      [...events].sort(
        (a, b) => Math.abs(Number(b.net_krw)) - Math.abs(Number(a.net_krw)),
      )[0],
    [events],
  );

  return (
    <>
      <Topbar title="입출금" subtitle="넣은 돈 대비 지금" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 일별 계좌수익률" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {/* ⚠️수익률 추이 화면의 '순입금 (구간 중)'과 다른 값이다 —
              여기는 첫날 입금까지 **전부** 센다. 증감은 두 화면이 같다. */}
          <StatTile
            label="순입금 (전체)"
            value={formatKrwString(data?.net_deposit_krw)}
            hint={
              data
                ? `입금 ${formatKrwString(data.total_deposit_krw)} · 출금 ${formatKrwString(data.total_withdrawal_krw)}`
                : "입금 − 출금"
            }
            loading={cashflow.isLoading}
          />
          <StatTile
            label="현재 자산"
            value={formatKrwString(data?.current_assets_krw)}
            // ⚠️기준일을 반드시 적는다. 자산 현황은 실시간이라 숫자가 다르다.
            hint={data?.last_date ? `${data.last_date} 예탁자산 기준` : "예탁자산"}
            loading={cashflow.isLoading}
          />
          <StatTile
            label="증감"
            value={formatKrwSigned(data?.gain_krw)}
            hint={
              data?.gain_ratio != null
                ? `순입금 대비 ${(Number(data.gain_ratio) * 100).toFixed(2)}%`
                : "현재 자산 − 순입금"
            }
            accent="auto"
            loading={cashflow.isLoading}
          />
          <StatTile
            label="입출금 횟수"
            value={data ? `${events.length}` : null}
            hint={
              biggest
                ? `최대 ${formatKrwSigned(biggest.net_krw)} (${biggest.base_date})`
                : "납입·인출 합계"
            }
            onClick={() => setTrendOpen(true)}
            actionHint="눌러서 누적 추이 보기"
            loading={cashflow.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="입출금 이력"
            subtitle={`${events.length}건 · 최근순`}
            scrollBody
          >
            <DataTable
              columns={["날짜", "구분", "금액", "그날 자산"]}
              align={["left", "left", "right", "right"]}
              empty={
                cashflow.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "입출금 기록이 없습니다"
                    : "계좌를 연동하면 입출금이 표시됩니다"
              }
            >
              {events.map((e) => {
                const isIn = e.deposit_krw != null;
                return (
                  <tr key={e.base_date} className="border-b border-hairline">
                    <Cell left tone="muted">
                      {e.base_date}
                    </Cell>
                    <Cell left>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-bold",
                          isIn ? "bg-bid-soft text-bid" : "bg-ask-soft text-ask",
                        )}
                      >
                        {isIn ? "입금" : "출금"}
                      </span>
                    </Cell>
                    <Cell strong tone={isIn ? "up" : "down"}>
                      {formatKrwString(isIn ? e.deposit_krw : e.withdrawal_krw)}
                    </Cell>
                    <Cell tone="muted">{formatKrwString(e.assets_after_krw)}</Cell>
                  </tr>
                );
              })}
            </DataTable>
          </StubCard>

          <StubCard
            title="월별 순입금"
            subtitle={`${data?.monthly.length ?? 0}개월`}
            scrollBody
          >
            {cashflow.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.monthly.length ?? 0) === 0 ? (
              <Empty text="입출금이 있던 달이 없습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  입출금이 없던 달은 생략했습니다.
                </p>
                <MonthlyBars months={data!.monthly} />
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        title="누적 순입금 추이"
        subtitle={
          data?.first_date ? `${data.first_date} ~ ${data.last_date}` : undefined
        }
        width={880}
      >
        {cumulative.length > 0 ? (
          <>
            <SeriesChart
              height={300}
              points={cumulative}
              includeZero
              tooltipFormat={(p) =>
                `${p.date} · ${formatKrwString(p.value == null ? null : String(Math.round(p.value)))}`
              }
            />
            <dl className="mt-3 grid grid-cols-2 gap-3 border-t border-hairline pt-3 sm:grid-cols-4">
              <Figure label="구간 시작 전 잔고" value={formatKrwString(data?.opening_balance_krw)} />
              <Figure label="순입금" value={formatKrwString(data?.net_deposit_krw)} />
              <Figure label="현재 자산" value={formatKrwString(data?.current_assets_krw)} />
              <Figure
                label="증감"
                value={formatKrwSigned(data?.gain_krw)}
                tone={Number(data?.gain_krw ?? 0) >= 0 ? "up" : "down"}
              />
            </dl>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
              <strong>증감은 금액이지 수익률이 아닙니다.</strong> 성과 분석의 기간
              수익률은 &quot;얼마나 잘 굴렸나&quot;를, 여기는 &quot;얼마가
              늘었나&quot;를 봅니다 — 늦게 넣은 돈이 많으면 수익률이 좋아도 금액
              증감은 작을 수 있습니다.
              {data?.opening_balance_krw != null &&
                Math.abs(Number(data.opening_balance_krw)) < 100_000 && (
                  <>
                    {" "}
                    구간 시작 전 잔고가 사실상 0 이므로, 이 계좌는 조회 구간에서
                    시작했다고 볼 수 있습니다.
                  </>
                )}
            </p>
          </>
        ) : (
          <Empty text="표시할 추이가 없습니다" />
        )}
      </Modal>
    </>
  );
}

/** 월별 순입금 막대 — 입금은 위로, 출금은 아래로. */
function MonthlyBars({ months }: { months: Cashflow["monthly"] }) {
  const max = Math.max(...months.map((m) => Math.abs(Number(m.net_krw))), 1);
  return (
    <div className="space-y-2">
      {[...months].reverse().map((m) => {
        const net = Number(m.net_krw);
        const width = (Math.abs(net) / max) * 100;
        return (
          <div key={m.month}>
            <div className="mb-0.5 flex items-baseline justify-between">
              <span className="text-[11px] font-bold text-ge-navy">{m.month}</span>
              <span
                className={cn(
                  "text-[11px] font-bold tabular-nums",
                  net >= 0 ? "text-bid" : "text-ask",
                )}
              >
                {formatKrwSigned(m.net_krw)}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
              <div
                className={cn(
                  "h-full rounded-full",
                  net >= 0 ? "bg-bid" : "bg-ask",
                )}
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <div className="text-[11px] font-bold text-ink-muted">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-[15px] font-extrabold tabular-nums text-ink",
          tone === "up" && "text-bid",
          tone === "down" && "text-ask",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
