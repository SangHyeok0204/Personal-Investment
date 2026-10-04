"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { SignedStackedBarChart } from "@/components/charts/signed-stacked-bar-chart";
import { CHART_PALETTE } from "@/components/charts/donut-chart";
import { CardEmpty, Cell, DataTable, ListButton, StatTile, StubCard } from "@/components/stub";
import { getInsiderMonth, getInsiderOverview, type InsiderTrade } from "@/lib/api";
import { cn } from "@/lib/utils";

// 내부자 거래 — 내 보유 + 관심종목의 Form 4 (계획 A6, 와이어프레임 A-2).
//
// ★순매수는 **판단이 담긴 거래만** 센다: 비파생 · 코드 P(장내 매수)/S(장내 매도) · 계획매매(10b5-1·직원주식매입 ESPP) 제외
//   · 정정(4/A)으로 대체된 행 제외. 보상 부여(A)·옵션 행사(M)·세금(F)·증여(G)는 경영진의 판단이 아니고,
//   장내 매도의 73% 가 몇 달 전에 정해 둔 계획매도라 섞으면 매도가 3배 넘게 부푼다.
//   제외한 거래는 버리지 않고 월 상세에 회색으로(계획매도는 "계획" 배지).
// ⚠️거래 없는 달은 막대가 없다(0원 순매수와 다르다). 종목마다 수집 시작이 달라 시작 전 달은 '조용했다'가 아니다.

function usd(v: number | null | undefined, signed = true): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "−" : signed && v > 0 ? "+" : "";
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}

function num(v: number | null | undefined): string {
  return v == null ? "—" : Math.round(v).toLocaleString();
}

export default function InsidersPage() {
  const [month, setMonth] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [d13Open, setD13Open] = useState(false);
  const [multiOpen, setMultiOpen] = useState(false);

  const q = useQuery({ queryKey: ["insiderOverview"], queryFn: getInsiderOverview, staleTime: 5 * 60_000 });
  const d = q.data;
  const detail = useQuery({
    queryKey: ["insiderMonth", month],
    queryFn: () => getInsiderMonth(month!),
    enabled: month != null,
    staleTime: 5 * 60_000,
  });

  // 종목 색: 24개월 |순매수| 합이 큰 순서.
  const colors = useMemo(() => {
    const tot = new Map<string, number>();
    for (const m of d?.monthly ?? [])
      for (const t of m.by_ticker) tot.set(t.ticker, (tot.get(t.ticker) ?? 0) + Math.abs(t.net_value));
    const out: Record<string, string> = {};
    [...tot.entries()]
      .sort((a, b) => b[1] - a[1])
      .forEach(([k], i) => (out[k] = CHART_PALETTE[i % CHART_PALETTE.length]));
    return out;
  }, [d]);

  const columns = useMemo(
    () =>
      (d?.monthly ?? []).map((m) => ({
        key: m.month,
        label: m.month.slice(2).replace("-", "."),
        segments: m.by_ticker.map((t) => ({ key: t.ticker, value: t.net_value })),
      })),
    [d],
  );
  const lastWithTrades = [...(d?.monthly ?? [])].reverse().find((m) => m.n_trades > 0);
  const shown = d?.monthly.find((m) => m.month === hover) ?? lastWithTrades;
  const late = (d?.data_from ?? []).filter((x) => x.from > (d?.monthly[0]?.month ?? "") + "-01");

  return (
    <>
      <Topbar
        title="내부자 거래"
        subtitle={
          d
            ? `보유·관심 ${d.targets.length}종목 · 순매수* = ${d.rule}`
            : "보유·관심종목 Form 4 · 판단이 담긴 거래만 순매수로"
        }
      />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label={`${d?.window_days ?? 90}일 순매수*`}
            value={d ? usd(d.net_value_window) : null}
            accent="auto"
            hint={d ? `장내 매수 ${d.buy_count_window} · 매도 ${d.sell_count_window}건 · 계획매도 제외` : undefined}
            loading={q.isLoading}
          />
          <StatTile
            label="장내 매수 건수"
            value={d ? `${d.buy_count_window}건` : null}
            hint="드묾 — 원본 4.8만 건 중 약 1천 건"
            loading={q.isLoading}
          />
          <StatTile
            label="여러 임원 동시 매수"
            value={d ? `${d.multi_insider_buys.length}종목` : null}
            hint={
              d
                ? d.multi_insider_buys.length
                  ? d.multi_insider_buys.map((x) => `${x.ticker} ${x.n_insiders}명`).join(" · ")
                  : `최근 ${d.window_days}일 2명 이상 장내 매수 없음`
                : undefined
            }
            onClick={d?.multi_insider_buys.length ? () => setMultiOpen(true) : undefined}
            actionHint="눌러서 목록"
            loading={q.isLoading}
          />
          <StatTile
            label="최근 13D (행동주의)"
            value={d ? (d.recent_13d.length ? `${d.recent_13d.length}건` : "없음") : null}
            hint={
              d
                ? d.recent_13d.length
                  ? d.recent_13d.map((x) => x.issuer_name ?? x.watch_name).join(" · ")
                  : `최근 ${d.window_days}일 · 내 종목이 대상인 것만`
                : undefined
            }
            onClick={d?.recent_13d.length ? () => setD13Open(true) : undefined}
            actionHint="눌러서 목록"
            loading={q.isLoading}
          />
        </div>

        <StubCard
          title="월별 내부자 순매수*"
          subtitle="종목별 누적 · 위 = 순매수, 아래 = 순매도 · 막대를 누르면 그 달 거래"
          className="min-h-0 flex-1"
          scrollBody
          action={lastWithTrades ? <ListButton onClick={() => setMonth(lastWithTrades.month)} /> : undefined}
        >
          {q.isLoading || !d ? (
            <CardEmpty text={q.isLoading ? "불러오는 중…" : "데이터 없음"} />
          ) : (
            <div className="flex h-full flex-col gap-2">
              <SignedStackedBarChart
                columns={columns}
                colors={colors}
                height={280}
                unit="개월"
                formatValue={(v) => usd(v)}
                selected={shown?.month}
                onHover={setHover}
                onPick={setMonth}
              />
              {shown && (
                <div className="rounded-lg bg-ge-th/60 px-3 py-2">
                  <div className="mb-1 flex items-baseline justify-between text-[11px] font-bold text-ink">
                    <span>
                      {shown.month} · 센 거래 {shown.n_trades}건 · 순매수 {usd(shown.net_value)}
                    </span>
                  </div>
                  {shown.by_ticker.length ? (
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 sm:grid-cols-4">
                      {shown.by_ticker.map((t) => (
                        <div key={t.ticker} className="flex items-center gap-1.5 text-[11px]">
                          <span className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: colors[t.ticker] }} />
                          <span className="font-semibold text-ink-secondary">{t.ticker}</span>
                          <span
                            className={cn(
                              "ml-auto font-semibold tabular-nums",
                              t.net_value > 0 ? "text-bid" : t.net_value < 0 ? "text-ask" : "text-ink-faint",
                            )}
                          >
                            {usd(t.net_value)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-ink-faint">센 거래 없음(0원과 다름)</p>
                  )}
                </div>
              )}
              <div className="mt-auto space-y-0.5 text-[10.5px] font-semibold text-ink-faint">
                <p>
                  * 순매수 = {d.rule}. 보상 부여(A)·옵션 행사(M)·세금(F)·증여(G)·계획매매(10b5-1·ESPP)는 월 상세에 회색으로만.
                </p>
                <p>
                  수집 시작이 늦은 종목(그 전 달은 &apos;조용했다&apos;가 아님):{" "}
                  {late.map((x) => `${x.ticker} ${x.from.slice(2, 7).replace("-", ".")}~`).join(" · ") || "없음"}
                  {d.no_data.length ? ` · Form 4 없음(ETF 등): ${d.no_data.join(", ")}` : ""}
                  {d.future_dated ? ` · 미래 날짜 ${d.future_dated}건 제외(데이터 오류)` : ""}
                </p>
              </div>
            </div>
          )}
        </StubCard>
      </PageContainer>

      <Modal
        open={month != null}
        onClose={() => setMonth(null)}
        title={`${month ?? ""} 내부자 거래`}
        subtitle={
          detail.data
            ? `센 거래 ${detail.data.n_counted}건 · 순매수 ${usd(detail.data.net_value)} · 제외 ${detail.data.n_excluded}건(회색)`
            : undefined
        }
        width={900}
      >
        {detail.isLoading || !detail.data ? (
          <CardEmpty text="불러오는 중…" />
        ) : (
          <TradeTable trades={detail.data.trades} />
        )}
      </Modal>

      <Modal open={d13Open} onClose={() => setD13Open(false)} title="최근 13D (행동주의)" subtitle="내 종목이 대상인 것만">
        <DataTable columns={["제출일", "대상", "요약"]} align={["left", "left", "left"]}>
          {(d?.recent_13d ?? []).map((x) => (
            <tr key={x.source_url} className="border-b border-hairline">
              <Cell left>{x.filing_date}</Cell>
              <Cell left strong>
                {x.issuer_name ?? x.watch_name}
              </Cell>
              <Cell left>
                <a href={x.source_url} target="_blank" rel="noreferrer" className="underline">
                  {x.headline}
                </a>
              </Cell>
            </tr>
          ))}
        </DataTable>
      </Modal>

      <Modal open={multiOpen} onClose={() => setMultiOpen(false)} title="여러 임원 동시 매수">
        <DataTable columns={["종목", "장내 매수한 내부자"]}>
          {(d?.multi_insider_buys ?? []).map((x) => (
            <tr key={x.ticker} className="border-b border-hairline">
              <Cell left strong>
                {x.ticker}
              </Cell>
              <Cell>{x.n_insiders}명</Cell>
            </tr>
          ))}
        </DataTable>
      </Modal>
    </>
  );
}

function TradeTable({ trades }: { trades: InsiderTrade[] }) {
  // 센 거래를 위로, 제외한 거래는 아래에 회색으로.
  const rows = [...trades.filter((t) => t.counted), ...trades.filter((t) => !t.counted)];
  return (
    <DataTable
      columns={["일자", "종목", "내부자 · 직위", "구분", "주수", "가격", "금액"]}
      align={["left", "left", "left", "left", "right", "right", "right"]}
      empty="이 달에는 거래가 없습니다"
    >
      {rows.map((t, i) => {
        const muted = !t.counted;
        return (
          <tr key={`${t.accession}-${i}`} className={cn("border-b border-hairline", muted && "opacity-55")}>
            <Cell left tone={muted ? "muted" : undefined}>
              {t.date.slice(5)}
            </Cell>
            <Cell left strong={!muted} tone={muted ? "muted" : undefined}>
              {t.ticker}
            </Cell>
            <Cell left tone={muted ? "muted" : undefined} className="max-w-[260px] truncate">
              {t.insider}
              {t.role && <span className="ml-1 text-ink-faint">· {t.role}</span>}
            </Cell>
            <Cell left tone={muted ? "muted" : t.code === "P" ? "up" : "down"}>
              {t.code_label}
              {t.planned && (
                <span className="ml-1 rounded bg-ink-faint/20 px-1 text-[10px] font-bold text-ink-muted">계획</span>
              )}
              {muted && !t.planned && t.excluded_reason !== t.code_label && (
                <span className="ml-1 text-[10px]">({t.excluded_reason})</span>
              )}
            </Cell>
            <Cell tone={muted ? "muted" : undefined}>{num(t.shares)}</Cell>
            <Cell tone={muted ? "muted" : undefined}>{t.price != null ? `$${t.price.toFixed(2)}` : "—"}</Cell>
            <Cell tone={muted ? "muted" : t.code === "P" ? "up" : "down"}>
              {t.counted ? usd(t.signed_value) : usd(t.value, false)}
            </Cell>
          </tr>
        );
      })}
    </DataTable>
  );
}
