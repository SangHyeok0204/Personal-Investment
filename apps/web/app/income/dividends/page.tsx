"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StatTile,
  StubCard,
} from "@/components/stub";
import { DonutChart, colorForKeys, type DonutSlice } from "@/components/charts/donut-chart";
import {
  StackedBarChart,
  type StackColumn,
} from "@/components/charts/stacked-bar-chart";
import { getDividends } from "@/lib/api";
import { formatKrwCompactString, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 배당 수령 이력 — 키움 usa21730 의 dvid_amt.
//
// ⚠️키움에 **배당 전용 TR 이 없다.** 일별 종목수익률 응답에 배당금이 섞여 오고,
//   종목코드와 거래소구분이 둘 다 필수라 종목별로 조회해야 한다(실측). 그래서
//   "예상 배당"이나 "배당락 캘린더"는 이 원천으로 만들 수 없다 — 받은 것만 안다.
//   화면이 약속하지 않도록 제목도 '배당 이력'으로 둔다.
//
// ★2026-09-22: 1페이지 압축. "이 화면이 하지 않는 것"은 늘 펼쳐 둘 내용이 아니라
//   카드 헤더의 버튼 → 팝업으로 옮겼다. 설계 메모는 남기되 자리는 차지하지 않는다.
//
// ★2026-09-22 사용자 요청으로 구성을 바꿨다: 수령 내역(건별 목록)을 없애고
//   **월별 누적 세로막대**를 왼쪽 큰 박스에, 종목별을 **도넛**으로 오른쪽에 뒀다.
//   건별 목록은 20건을 훑어야 "언제 얼마"가 보였는데, 누적막대는 **월 추이와
//   종목 구성을 한 번에** 보여 준다. 잃은 정보(개별 지급일)는 막대를 짚으면
//   그 달의 종목별 내역 표로 되돌려 준다.
//
// ⚠️누적막대의 조각은 **items 에서 직접** 쌓는다(월×종목). 서버의 monthly 합계와
//   맞는지 화면에서 검산하고, 어긋나면 **그 사실을 띄운다** — 조용히 다른 숫자를
//   그리면 두 카드가 서로 다른 말을 하게 된다.

const RANGES = [
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function DividendsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [limitsOpen, setLimitsOpen] = useState(false);

  const dividends = useQuery({
    queryKey: ["dividends", accountId, days],
    queryFn: () => getDividends(accountId, days),
    staleTime: 60_000,
  });

  const data = dividends.data;
  const items = data?.items ?? [];
  const monthly = data?.monthly ?? [];
  const byTicker = data?.by_ticker ?? [];

  // 종목 색은 **금액 순서**로 고정한다(서버가 그 순서로 준다). 도넛과 막대가
  // 같은 색을 쓰도록 한 곳에서 만든다.
  const colors = useMemo(
    () => colorForKeys(byTicker.map((t) => t.ticker)),
    [byTicker],
  );
  const tickerName = useMemo(() => {
    const map: Record<string, string> = {};
    for (const t of byTicker) map[t.ticker] = t.asset_name ?? t.ticker;
    return map;
  }, [byTicker]);

  // 월 × 종목. items 는 조회 구간 전체를 담고 있어 여기서 정확히 쌓을 수 있다.
  const columns: StackColumn[] = useMemo(() => {
    const buckets = new Map<string, Map<string, number>>();
    for (const d of items) {
      const month = d.pay_date.slice(0, 7);
      const inner = buckets.get(month) ?? new Map<string, number>();
      inner.set(d.ticker, (inner.get(d.ticker) ?? 0) + Number(d.amount_krw));
      buckets.set(month, inner);
    }
    // 서버의 monthly 가 정본 순서다(오름차순). 거기 없는 달은 만들지 않는다.
    return monthly.map((m) => {
      const inner = buckets.get(m.month) ?? new Map<string, number>();
      // 조각 순서도 금액 순서로 — 큰 종목이 아래로 깔려야 막대가 안 흔들린다.
      const segments = byTicker
        .filter((t) => (inner.get(t.ticker) ?? 0) > 0)
        .map((t) => ({
          key: t.ticker,
          label: tickerName[t.ticker] ?? t.ticker,
          value: inner.get(t.ticker) ?? 0,
        }));
      return {
        key: m.month,
        label: m.month,
        total: Number(m.amount_krw),
        segments,
      };
    });
  }, [items, monthly, byTicker, tickerName]);

  // ⚠️검산. 쌓은 조각의 합이 서버 월합계와 다르면 **그 사실을 띄운다.**
  const mismatched = useMemo(
    () =>
      columns.filter((c) => {
        const stacked = c.segments.reduce((sum, s) => sum + s.value, 0);
        return Math.abs(stacked - c.total) > 1;
      }),
    [columns],
  );

  const [picked, setPicked] = useState<string | null>(null);
  const [sticky, setSticky] = useState(false);
  // 짚은 달이 없으면 **가장 최근 달**을 보여 준다 — 표 자리가 비어 있지 않도록.
  // ⚠️기간을 좁히면 고정해 둔 달이 사라질 수 있다. 그때 표를 통째로 비우지 않고
  //   최근 달로 되돌린다(실제로 전체 → 6개월 전환에서 표가 사라졌다).
  const fallbackMonth = columns.length > 0 ? columns[columns.length - 1].key : null;
  const pickedExists = picked != null && columns.some((c) => c.key === picked);
  const shownMonth = pickedExists ? picked : fallbackMonth;
  const shownColumn = columns.find((c) => c.key === shownMonth) ?? null;

  const donutSlices: DonutSlice[] = useMemo(
    () =>
      byTicker.map((t) => ({
        key: t.ticker,
        label: t.asset_name ?? t.ticker,
        value: Number(t.amount_krw),
        caption: `${formatKrwString(t.amount_krw)} · ${t.count}회`,
      })),
    [byTicker],
  );

  // 월평균 — 배당이 찍힌 달만 세면 과대평가된다. 조회 기간의 개월 수로 나눈다.
  const months = Math.max(1, Math.round(days / 30));
  const monthlyAvg =
    data?.total_amount_krw != null
      ? Math.round(Number(data.total_amount_krw) / months)
      : null;

  const ranges = (
    <div className="flex flex-wrap items-center gap-1.5">
      {RANGES.map((r) => (
        <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
          {r.label}
        </Chip>
      ))}
    </div>
  );

  return (
    <>
      <Topbar title="배당 이력" subtitle="수령한 배당 (원화)" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="키움 배당 조회" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="총 수령 배당"
            value={formatKrwString(data?.total_amount_krw)}
            hint={
              data?.first_pay_date
                ? `${data.first_pay_date} ~ ${data.last_pay_date}`
                : "조회 기간 합계"
            }
            loading={dividends.isLoading}
          />
          <StatTile
            label="수령 횟수"
            value={data ? `${data.total}` : undefined}
            hint={
              data?.by_ticker.length ? `${data.by_ticker.length}종목` : undefined
            }
            loading={dividends.isLoading}
          />
          <StatTile
            label="월평균"
            value={monthlyAvg == null ? undefined : formatKrwString(String(monthlyAvg))}
            hint={`조회 기간 ${months}개월 기준`}
            loading={dividends.isLoading}
          />
          <StatTile
            label="최근 수령"
            value={data?.last_pay_date ?? undefined}
            hint={
              items[0] ? `${items[0].asset_name ?? items[0].ticker}` : undefined
            }
            loading={dividends.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="월별 수령"
            subtitle="막대를 짚으면 그 달의 종목별 내역"
            action={ranges}
            scrollBody
          >
            {dividends.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : columns.length === 0 ? (
              <Empty
                text={
                  connected
                    ? "해당 기간에 수령한 배당이 없습니다"
                    : "계좌를 연동하면 배당 이력이 표시됩니다"
                }
              />
            ) : (
              <div className="space-y-3">
                {/* ⚠️조용히 다른 숫자를 그리지 않는다 — 어긋나면 말한다. */}
                {mismatched.length > 0 && (
                  <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
                    {mismatched.map((c) => c.label).join(", ")} 의 종목별 합이 월
                    합계와 다릅니다 — 막대의 조각 구성을 그대로 믿지 마세요.
                  </p>
                )}

                <StackedBarChart
                  columns={columns}
                  colors={colors}
                  formatTotal={(v) => formatKrwCompactString(String(v))}
                  selected={shownMonth}
                  onSelect={(key, isSticky) => {
                    if (key == null) {
                      // 고정해 둔 달이 있으면 마우스가 나가도 유지한다.
                      if (!sticky) setPicked(null);
                      return;
                    }
                    if (isSticky) {
                      const same = picked === key && sticky;
                      setSticky(!same);
                      setPicked(same ? null : key);
                      return;
                    }
                    if (!sticky) setPicked(key);
                  }}
                />

                {shownColumn && (
                  <div>
                    <div className="mb-1.5 flex items-baseline justify-between">
                      <span className="text-[11px] font-bold text-ge-navy">
                        {shownColumn.label}
                        {sticky && pickedExists && picked === shownColumn.key && (
                          <span className="ml-1.5 rounded bg-ge-navy/10 px-1 py-0.5 text-[9px] font-extrabold text-ge-navy">
                            고정
                          </span>
                        )}
                      </span>
                      <span className="text-[11px] font-extrabold tabular-nums text-ink">
                        {formatKrwString(String(shownColumn.total))}
                        <span className="ml-1.5 font-semibold text-ink-faint">
                          {shownColumn.segments.length}종목
                        </span>
                      </span>
                    </div>
                    <DataTable
                      columns={["종목", "금액", "비중"]}
                      align={["left", "right", "right"]}
                      empty="이 달에는 수령한 배당이 없습니다"
                    >
                      {shownColumn.segments.map((seg) => (
                        <tr key={seg.key} className="border-b border-hairline">
                          <Cell left strong>
                            <span className="flex items-center gap-1.5">
                              {/* 막대 조각과 같은 색 점 — 눈이 둘을 잇는다. */}
                              <span
                                className="h-2 w-2 shrink-0 rounded-[2px]"
                                style={{ backgroundColor: colors[seg.key] }}
                              />
                              <span className="max-w-[150px] truncate">
                                {seg.label}
                              </span>
                              <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                                {seg.key}
                              </span>
                            </span>
                          </Cell>
                          <Cell strong tone="up">
                            {formatKrwString(String(seg.value))}
                          </Cell>
                          <Cell tone="muted">
                            {shownColumn.total > 0
                              ? `${((seg.value / shownColumn.total) * 100).toFixed(0)}%`
                              : "—"}
                          </Cell>
                        </tr>
                      ))}
                    </DataTable>
                    <p className="mt-1.5 text-[11px] leading-snug text-ink-muted">
                      막대에 마우스를 올리면 그 달로 바뀌고, <strong>누르면
                      고정</strong>됩니다. 지급일 하나하나는 이 화면에서 빼고
                      월 단위로 모았습니다.
                    </p>
                  </div>
                )}
              </div>
            )}
          </StubCard>

          <StubCard
            title="종목별"
            subtitle="누가 배당을 주고 있나"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setLimitsOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                한계
              </button>
            }
          >
            {dividends.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : donutSlices.length === 0 ? (
              <Empty text="데이터가 없습니다" />
            ) : (
              <DonutChart
                slices={donutSlices}
                size={168}
                centerLabel="총 배당"
                centerValue={formatKrwCompactString(data?.total_amount_krw)}
                maxLegend={9}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={limitsOpen}
        onClose={() => setLimitsOpen(false)}
        title="이 화면이 하지 않는 것"
        subtitle="원천 데이터의 한계 — 약속하지 않으려고 적어 둔다"
      >
        <PlannedList
          items={[
            "예상 배당·배당락 캘린더는 만들지 않았다 — 키움에 배당 전용 TR 이 없고, 이 원천(usa21730)은 '받은 배당'만 알려준다. 미래를 약속하려면 별도 배당 일정 데이터가 필요하다",
            "세전/세후 구분 없음 — 증권사가 이 TR 로 원화 금액 하나만 준다",
            "배당수익률(yield)은 보유 평가액이 시점마다 달라 정의를 먼저 정해야 한다",
          ]}
        />
      </Modal>
    </>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
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
