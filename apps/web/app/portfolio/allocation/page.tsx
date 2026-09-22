"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StubCard,
} from "@/components/stub";
import {
  getPortfolioAllocation,
  getPortfolioHoldings,
  setAssetSector,
  type AllocationDimension,
  type AllocationSlice,
} from "@/lib/api";
import { formatKrwString, formatPercentString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 섹터/자산 배분.
//
// ★2026-09-21 5차: 비중 계산을 서버(/api/v1/portfolio/allocation)로 올렸다.
//   화면마다 따로 계산하면 반올림 처리가 갈려 같은 숫자가 화면마다 달라진다.
//   섹터 컬럼(alembic 0006)이 생겨 섹터 비중도 실제로 그린다.
//
// ⚠️미분류를 숨기지 않는다. 숨기면 비중 합이 100%로 보여 분류가 끝난 것처럼
//   착각하게 된다. 아래 표에서 그 자리에서 바로 분류할 수 있게 했다.

const DIMENSIONS: { id: AllocationDimension; label: string }[] = [
  { id: "sector", label: "섹터" },
  { id: "industry", label: "세부 산업" },
  { id: "asset_type", label: "자산군" },
  { id: "country", label: "국가" },
  { id: "currency", label: "통화" },
];

/** 가로 막대 비중 — 원형보다 값을 읽기 쉽고 항목이 적을 때 낭비가 없다. */
function WeightBars({ items }: { items: AllocationSlice[] }) {
  if (items.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        계좌를 연동하면 비중이 계산됩니다
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((s) => {
        const pct = Number(s.weight) * 100;
        const unclassified = s.key === null;
        return (
          <div key={s.key ?? "__unclassified__"}>
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span
                className={cn(
                  "text-[13px] font-extrabold",
                  unclassified ? "text-ink-muted" : "text-ge-navy",
                )}
              >
                {s.label}
                <span className="ml-1.5 text-[10px] font-semibold text-ink-faint">
                  {s.position_count}종목
                </span>
              </span>
              <span className="text-[12px] font-bold tabular-nums text-ink-secondary">
                {pct.toFixed(1)}%
                <span className="ml-2 font-semibold text-ink-faint">
                  {formatKrwString(s.market_value_krw)}
                </span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-canvas-soft">
              <div
                className={cn(
                  "h-full rounded-full",
                  // 미분류는 회색 — 한눈에 "아직 안 한 것"으로 읽히게.
                  unclassified ? "bg-slate-300" : "bg-ge-point",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function AllocationPage() {
  const { accountId, connected } = useAccount();
  const [dimension, setDimension] = useState<AllocationDimension>("sector");
  const queryClient = useQueryClient();

  const allocation = useQuery({
    queryKey: ["portfolioAllocation", dimension, accountId],
    queryFn: () => getPortfolioAllocation(dimension, accountId),
    staleTime: 30_000,
  });
  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 30_000,
  });

  const patch = useMutation({
    mutationFn: ({ assetId, sector }: { assetId: string; sector: string }) =>
      setAssetSector(assetId, { sector }),
    onSuccess: () => {
      // 분류가 바뀌면 비중과 보유 목록이 같이 달라진다.
      void queryClient.invalidateQueries({ queryKey: ["portfolioAllocation"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
    },
  });

  const data = allocation.data;
  const unclassified = data?.unclassified_market_value_krw;

  return (
    <>
      <Topbar title="섹터/자산 배분" subtitle="섹터 · 산업 · 자산군 · 국가 · 통화" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="보유 종목" />}

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {DIMENSIONS.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => setDimension(d.id)}
              aria-pressed={dimension === d.id}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-[12px] font-bold transition-colors",
                dimension === d.id
                  ? "border-ge-point bg-ge-blue-bg text-ge-point"
                  : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
              )}
            >
              {d.label}
            </button>
          ))}
          {data?.total_market_value_krw && (
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              기준 평가금액 {formatKrwString(data.total_market_value_krw)}
            </span>
          )}
        </div>

        {/* 미분류가 남아 있으면 숨기지 않고 위에서 알린다. */}
        {unclassified && Number(unclassified) > 0 && (
          <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="text-[12px] font-semibold text-amber-900">
              미분류 {formatKrwString(unclassified)} — 아래 표에서 종목별로 섹터를
              지정하면 비중에 바로 반영됩니다.
            </p>
          </div>
        )}

        {/* ★2026-09-22 전체 점검에서 걸렸다: `wide` 로 남아 페이지가 스크롤됐다.
            세로 3단이던 것을 **왼쪽에 비중 두 개, 오른쪽에 분류 표**로 다시 짰다 —
            그냥 fit 으로만 바꾸면 세 카드가 한 화면에 들어가지 않는다. */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            // ⚠️lg(1024)에서 2열로 가르면 오른쪽 표가 377px 밖에 못 받아 잘린다.
            //   xl(1280)부터 가른다 — 그 아래에서는 세로로 쌓아 표가 폭을 다 쓴다.
            "xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] xl:auto-rows-auto",
          )}
        >
          <div className="flex min-h-0 flex-col gap-3">
          <StubCard
            title={`${DIMENSIONS.find((d) => d.id === dimension)?.label} 비중`}
            subtitle="평가금액(KRW) 기준"
            className="min-h-0 flex-1"
            scrollBody
          >
            <WeightBars items={data?.items ?? []} />
          </StubCard>

          <StubCard
            title="종목 비중"
            subtitle="평가금액 순 상위 8"
            className="min-h-0 flex-1"
            scrollBody
          >
            <WeightBars
              items={(holdings.data?.items ?? []).slice(0, 8).map((h) => ({
                key: h.asset_id,
                label: h.name ?? h.ticker,
                market_value_krw: h.market_value_krw ?? "0",
                weight:
                  holdings.data?.total_market_value_krw &&
                  Number(holdings.data.total_market_value_krw) !== 0
                    ? String(
                        Number(h.market_value_krw ?? 0) /
                          Number(holdings.data.total_market_value_krw),
                      )
                    : "0",
                position_count: 1,
              }))}
            />
          </StubCard>
          </div>

          <StubCard
            title="종목별 분류"
            subtitle="섹터를 고치면 MANUAL 로 표시됩니다"
            className="min-h-0"
            scrollBody
          >
            <DataTable
              // ⚠️6칸이면 좁은 폭에서 표가 잘린다(실측 1160px: 표 518 vs 카드 449).
              //   정보를 버리지 않고 **합친다** — 국가는 종목 옆 태그로,
              //   세부 산업은 섹터 아래 줄로 내린다.
              columns={["종목", "섹터 · 세부 산업", "평가금액", ""]}
              align={["left", "left", "right", "right"]}
              empty={
                holdings.isLoading ? "불러오는 중…" : "보유 종목이 없습니다"
              }
            >
              {(holdings.data?.items ?? []).map((h) => (
                <SectorRow
                  key={`${h.account_id}-${h.asset_id}`}
                  assetId={h.asset_id}
                  name={h.name ?? h.ticker}
                  ticker={h.ticker}
                  country={h.country}
                  sector={h.sector}
                  industry={h.industry}
                  sectorSource={h.sector_source}
                  marketValueKrw={h.market_value_krw}
                  saving={patch.isPending}
                  onSave={(sector) =>
                    patch.mutate({ assetId: h.asset_id, sector })
                  }
                />
              ))}
            </DataTable>
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}

/** 표 한 줄 — 그 자리에서 섹터를 고칠 수 있다. */
function SectorRow({
  name,
  ticker,
  country,
  sector,
  industry,
  sectorSource,
  marketValueKrw,
  saving,
  onSave,
}: {
  assetId: string;
  name: string;
  ticker: string;
  country: string;
  sector: string | null;
  industry: string | null;
  sectorSource: string | null;
  marketValueKrw: string | null;
  saving: boolean;
  onSave: (sector: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  return (
    <tr className="border-t border-hairline transition-colors hover:bg-canvas-soft/60">
      <Cell left strong>
        {/* ⚠️이름을 그대로 두면 칸이 251px 까지 벌어져 좁은 폭에서 표가 잘린다
            (실측 1300px 에서 표 597px vs 카드 524px). 폭에 맞춰 줄인다. */}
        <span className="flex items-center gap-1.5">
          <span className="max-w-[120px] truncate xl:max-w-[170px]" title={name}>
            {name}
          </span>
          <span className="shrink-0 text-[10px] font-semibold text-ink-faint">
            {ticker}
          </span>
          {country && (
            <span className="shrink-0 rounded bg-canvas-soft px-1 py-0.5 text-[9px] font-bold text-ink-faint">
              {country}
            </span>
          )}
        </span>
      </Cell>
      <Cell left>
        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draft.trim()) {
                onSave(draft.trim());
                setEditing(false);
              }
              if (e.key === "Escape") setEditing(false);
            }}
            placeholder="예: 반도체"
            className="w-28 rounded-lg border border-ge-point bg-white px-2 py-1 text-[12px] font-semibold text-ge-navy outline-none"
          />
        ) : sector ? (
          <span className="flex flex-col items-start">
          <span className="flex items-center gap-1.5">
            <span className="max-w-[110px] truncate text-[12px] font-bold text-ge-navy">
              {sector}
            </span>
            {sectorSource === "MANUAL" && (
              <span
                title="직접 지정한 값 — 자동 분류가 덮지 않습니다"
                className="rounded bg-ge-blue-bg px-1 py-0.5 text-[9px] font-bold text-ge-point"
              >
                수기
              </span>
            )}
          </span>
          {industry && (
            <span
              className="block max-w-[130px] truncate text-[10px] font-medium text-ink-faint"
              title={industry}
            >
              {industry}
            </span>
          )}
          </span>
        ) : (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-bold text-amber-700">
            미분류
          </span>
        )}
      </Cell>
      <Cell strong>{formatKrwString(marketValueKrw)}</Cell>
      <Cell>
        {editing ? (
          <span className="flex items-center justify-end gap-1">
            <button
              type="button"
              aria-label="저장"
              disabled={saving || !draft.trim()}
              onClick={() => {
                onSave(draft.trim());
                setEditing(false);
              }}
              className="rounded-md p-1 text-status-success transition-colors hover:bg-status-success/10 disabled:opacity-40"
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="취소"
              onClick={() => setEditing(false)}
              className="rounded-md p-1 text-ink-muted transition-colors hover:bg-canvas-soft"
            >
              <X className="h-4 w-4" />
            </button>
          </span>
        ) : (
          <button
            type="button"
            aria-label={`${name} 섹터 지정`}
            onClick={() => {
              setDraft(sector ?? "");
              setEditing(true);
            }}
            className="rounded-md p-1 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ge-point"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </Cell>
    </tr>
  );
}
