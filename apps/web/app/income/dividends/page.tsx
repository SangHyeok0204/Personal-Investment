"use client";

import { useState } from "react";
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
import { getDividends } from "@/lib/api";
import { formatKrwString } from "@/lib/format";
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
  const maxMonth = Math.max(1, ...monthly.map((m) => Number(m.amount_krw)));

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
            "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="수령 내역"
            subtitle={`${items.length}건 · 최근순`}
            action={ranges}
            scrollBody
          >
            <DataTable
              columns={["지급일", "종목", "금액"]}
              align={["left", "left", "right"]}
              empty={
                dividends.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "해당 기간에 수령한 배당이 없습니다"
                    : "계좌를 연동하면 배당 이력이 표시됩니다"
              }
            >
              {items.map((d) => (
                <tr key={d.id} className="border-b border-hairline">
                  <Cell left tone="muted">
                    {d.pay_date}
                  </Cell>
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[140px] truncate">
                        {d.asset_name ?? d.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {d.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell strong tone="up">
                    {formatKrwString(d.amount_krw)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="월별 수령" subtitle="배당은 분기 주기가 흔하다" scrollBody>
            {monthly.length > 0 ? (
              <div className="space-y-2">
                {monthly
                  .slice()
                  .reverse()
                  .map((m) => (
                    <div key={m.month}>
                      <div className="mb-0.5 flex items-baseline justify-between">
                        <span className="text-[11px] font-bold text-ge-navy">
                          {m.month}
                        </span>
                        <span className="text-[11px] font-bold tabular-nums text-ink-secondary">
                          {formatKrwString(m.amount_krw)}
                          <span className="ml-1.5 font-semibold text-ink-faint">
                            {m.count}건
                          </span>
                        </span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
                        <div
                          className="h-full rounded-full bg-status-success"
                          style={{
                            width: `${(Number(m.amount_krw) / maxMonth) * 100}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-[12px] font-semibold text-ink-faint">
                {dividends.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
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
            <DataTable
              columns={["종목", "횟수", "금액"]}
              align={["left", "right", "right"]}
              empty={dividends.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {(data?.by_ticker ?? []).map((t) => (
                <tr key={t.ticker} className="border-b border-hairline">
                  <Cell left strong>
                    <span className="block max-w-[130px] truncate">
                      {t.asset_name ?? t.ticker}
                    </span>
                  </Cell>
                  <Cell tone="muted">{t.count}회</Cell>
                  <Cell strong tone="up">
                    {formatKrwString(t.amount_krw)}
                  </Cell>
                </tr>
              ))}
            </DataTable>
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
