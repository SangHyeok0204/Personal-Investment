"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { SeriesChart } from "@/components/charts/series-chart";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getPerformance } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수익률 추이.
//
// ★2026-09-21: 키움 usa21670(일별계좌수익률현황)에 배선했다. 스냅샷을 쌓는 배치를
//   만들지 않은 이유 — 증권사가 이미 과거 일별 시계열을 들고 있다(실측 531일).
//   우리가 오늘부터 새로 쌓으면 과거가 영영 비어 있게 된다.
//
// ⚠️여기서 TWR/MWR 을 계산해 내보이지 않는다. 제대로 하려면 일별 현금흐름이
//   정확해야 하는데, 지금 있는 것은 입출금 일계(ina_amt/pymn_amt)뿐이라 같은 날
//   입금과 매매가 겹치면 시점 가정이 필요하다. 근거 없는 숫자를 "TWR" 이라고
//   써 붙이면 그 숫자로 판단하게 된다 — 대신 **입출금을 뺀 순수 증감**을 보여준다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function ReturnsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [notesOpen, setNotesOpen] = useState(false);
  const [metric, setMetric] = useState<"assets" | "cumulative">("assets");

  const perf = useQuery({
    queryKey: ["performance", accountId, days],
    queryFn: () => getPerformance(accountId, days),
    staleTime: 60_000,
  });

  const data = perf.data;
  const items = data?.items ?? [];

  // 원금(순입금) 대비 증감률. 분모가 0이면 계산하지 않는다.
  const netDeposit = Number(data?.net_deposit_krw ?? 0);
  const start = Number(data?.start_assets_krw ?? 0);
  const base = start + netDeposit;
  const gain = data?.gain_krw == null ? null : Number(data.gain_krw);
  const gainRate = gain != null && base > 0 ? (gain / base) * 100 : null;

  // 월별 집계 — 월말 예탁자산과 그 달의 손익 합.
  const monthly = aggregateMonthly(items);

  return (
    <>
      <Topbar title="수익률 추이" subtitle="예탁자산 · 누적손익" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="계좌 성과" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="현재 예탁자산"
            value={formatKrwString(data?.end_assets_krw)}
            hint={data?.last_date ?? undefined}
            loading={perf.isLoading}
          />
          {/* ⚠️입출금 화면의 '순입금'과 **다른 값**이다. 여기는 조회 구간
              시작일 이후만 세고(시작 자산에 이미 반영된 첫날 입금은 제외),
              입출금 화면은 계좌 개설 이후 전부를 센다. 실측 차이 979,221원 =
              첫날 입금액. 두 화면의 '증감'은 정확히 같다(1,169,220원) —
              분해 방식만 다르다. 이름을 구분해 두지 않으면 버그로 읽힌다. */}
          <StatTile
            label="순입금 (구간 중)"
            value={formatKrwString(data?.net_deposit_krw)}
            hint="시작일 이후 입금 − 출금"
            loading={perf.isLoading}
          />
          <StatTile
            label="입출금 제외 증감"
            value={formatKrwSigned(data?.gain_krw)}
            hint="(끝자산 − 시작자산 − 순입금)"
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="원금 대비"
            value={gainRate == null ? undefined : `${gainRate > 0 ? "+" : ""}${gainRate.toFixed(2)}%`}
            hint="증감 ÷ (시작자산 + 순입금)"
            accent="auto"
            loading={perf.isLoading}
          />
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {RANGES.map((r) => (
            <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
              {r.label}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-hairline" />
          <Chip active={metric === "assets"} onClick={() => setMetric("assets")}>
            예탁자산
          </Chip>
          <Chip active={metric === "cumulative"} onClick={() => setMetric("cumulative")}>
            누적손익
          </Chip>
          {data?.first_date && (
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {data.first_date} ~ {data.last_date} ({items.length}일)
            </span>
          )}
        </div>

        {/* ★2026-09-22 전체 점검에서 걸렸다: `wide` 로 남아 페이지가 스크롤됐다.
            '여기서 하지 않는 것' 카드는 카드 자리를 차지하는 대신 헤더 버튼 →
            팝업으로 옮겼다(다른 화면과 같은 규약). */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            // ⚠️lg(1024)에서 가르면 오른쪽 월별 표가 좁아 잘린다. xl 부터 가른다.
            "md:grid-cols-2 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] xl:auto-rows-auto",
          )}
        >
          <StubCard
            title={metric === "assets" ? "예탁자산 추이" : "누적손익 추이"}
            subtitle={metric === "assets" ? "현금 + 주식 평가" : "증권사 산출 누적손익"}
            className="min-h-0"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNotesOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                이 화면의 범위
              </button>
            }
          >
            {items.length > 0 ? (
              <SeriesChart
                height={300}
                includeZero={metric === "cumulative"}
                points={items.map((p) => {
                  const raw =
                    metric === "assets" ? p.deposit_assets_krw : p.cumulative_pnl_krw;
                  return { date: p.base_date, value: raw == null ? null : Number(raw) };
                })}
                tooltipFormat={(p) =>
                  formatKrwString(p.value == null ? null : String(Math.round(p.value)))
                }
              />
            ) : (
              <div className="flex h-[300px] items-center justify-center text-[12px] font-semibold text-ink-faint">
                {perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
              </div>
            )}
          </StubCard>

          <StubCard
            title="월별"
            subtitle="월말 자산 · 월 손익 합"
            className="min-h-0"
            scrollBody
          >
            <DataTable
              columns={["월", "월말 예탁자산", "월 손익"]}
              align={["left", "right", "right"]}
              empty={perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {monthly.map((m) => (
                <tr
                  key={m.month}
                  className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
                >
                  <Cell left strong>
                    {m.month}
                  </Cell>
                  <Cell>{formatKrwString(String(Math.round(m.assets)))}</Cell>
                  <Cell tone={toneOf(String(m.pnl))}>
                    {formatKrwSigned(String(Math.round(m.pnl)))}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면의 범위"
        subtitle="여기서 하지 않는 것과, 그걸 하는 화면"
      >
        {/* ⚠️2026-09-22 정정: 예전엔 "TWR·벤치마크·리스크 지표는 하지 않는다"고
            적혀 있었는데 **그 뒤에 전부 만들었다.** 화면이 사실과 다른 말을
            하고 있었다. 안 하는 이유가 아니라 **어디서 하는지**를 적는다. */}
        <PlannedList
          items={[
            "여기는 **금액**을 본다 — 예탁자산과 누적손익의 추이. 입출금이 섞이면 금액은 늘지만 잘 굴린 것은 아니라서, '입출금 제외 증감'을 따로 낸다",
            "시간가중 수익률(TWR)·변동성·MDD·샤프는 '성과 분석' 화면에서 본다 — 일별 현금흐름 보정(reconcile_flows)을 거쳐 계산한다",
            "S&P 500·필라델피아 반도체 대비는 '벤치마크 비교' 화면에서 본다 (원화 환산 기준)",
            "월·분기·연도를 잘라 보는 것은 '기간 리포트' 화면이다",
          ]}
        />
      </Modal>
    </>
  );
}

/** 월말 예탁자산과 그 달 손익 합. 최근 달이 위로. */
function aggregateMonthly(items: { base_date: string; deposit_assets_krw: string | null; pnl_krw: string | null }[]) {
  const acc = new Map<string, { month: string; assets: number; pnl: number }>();
  for (const p of items) {
    const month = p.base_date.slice(0, 7);
    const entry = acc.get(month) ?? { month, assets: 0, pnl: 0 };
    // 마지막으로 본 값이 월말 값이다(items 는 날짜 오름차순).
    if (p.deposit_assets_krw != null) entry.assets = Number(p.deposit_assets_krw);
    entry.pnl += Number(p.pnl_krw ?? 0);
    acc.set(month, entry);
  }
  return [...acc.values()].reverse();
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
      className={cn(
        "rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-colors",
        active
          ? "border-ge-point bg-ge-blue-bg text-ge-point"
          : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {children}
    </button>
  );
}
