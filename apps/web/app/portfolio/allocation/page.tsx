"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { Modal } from "@/components/ui/modal";
import {
  getPortfolioAllocation,
  getPortfolioHoldings,
  setAssetSector,
  type AllocationDimension,
  type AllocationSlice,
  type PortfolioHolding,
} from "@/lib/api";
import { formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 섹터/자산 배분.
//
// ★2026-09-21 5차: 비중 계산을 서버(/api/v1/portfolio/allocation)로 올렸다.
//   화면마다 따로 계산하면 반올림 처리가 갈려 같은 숫자가 화면마다 달라진다.
//   섹터 컬럼(alembic 0006)이 생겨 섹터 비중도 실제로 그린다.
//
// ⚠️미분류를 숨기지 않는다. 숨기면 비중 합이 100%로 보여 분류가 끝난 것처럼
//   착각하게 된다. '미분류' 타일을 늘 띄우고, 누르면 그 자리에서 분류하는 팝업이 뜬다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 화면에는 **대표 숫자 하나씩**,
//   세부는 눌러서 팝업으로. 비중은 스냅샷이라 월별 막대는 없다 —
//   막대(분류)를 누르면 그 분류에 든 종목 바스켓, 종목별 분류 표는 '분류 편집' 팝업.

const DIMENSIONS: { id: AllocationDimension; label: string }[] = [
  { id: "sector", label: "섹터" },
  { id: "industry", label: "세부 산업" },
  { id: "asset_type", label: "자산군" },
  { id: "country", label: "국가" },
  { id: "currency", label: "통화" },
];

/** 그 축에서 이 종목이 들어가는 조각 키. 서버 /allocation 의 group by 컬럼과 같은 값이다
 *  (null = 미분류). 자산 현황의 axisKeyOf 와 같은 생각이다. */
function axisKeyOf(h: PortfolioHolding, dim: AllocationDimension): string | null {
  switch (dim) {
    case "sector":
      return h.sector;
    case "industry":
      return h.industry;
    case "asset_type":
      return h.asset_type;
    case "country":
      return h.country;
    case "currency":
      return h.currency;
    default:
      return null;
  }
}

/** 가로 막대 비중 — 원형보다 값을 읽기 쉽고 항목이 적을 때 낭비가 없다.
 *  `onPick` 을 주면 누를 수 있는 막대(`canPick` 이 참인 것만)가 버튼이 된다. */
function WeightBars({
  items,
  onPick,
  canPick,
}: {
  items: AllocationSlice[];
  onPick?: (s: AllocationSlice) => void;
  canPick?: (s: AllocationSlice) => boolean;
}) {
  if (items.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
        계좌를 연동하면 비중이 계산됩니다
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {items.map((s) => {
        const pct = Number(s.weight) * 100;
        const unclassified = s.key === null;
        const pickable = onPick != null && (canPick?.(s) ?? true);
        return (
          <div
            key={s.key ?? "__unclassified__"}
            role={pickable ? "button" : undefined}
            tabIndex={pickable ? 0 : undefined}
            onClick={pickable ? () => onPick(s) : undefined}
            onKeyDown={
              pickable
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onPick(s);
                    }
                  }
                : undefined
            }
            className={cn(
              "rounded-lg px-1.5 py-1",
              pickable &&
                "cursor-pointer transition-colors hover:bg-canvas-soft focus:outline-none focus-visible:bg-canvas-soft",
            )}
          >
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
  // 막대(분류) → 그 분류에 든 종목 바스켓.
  const [basket, setBasket] = useState<AllocationSlice | null>(null);
  // 분류 전체 목록(비중 표) / 종목 비중 전체 / 분류 편집 표. 편집은 '전부'와
  // '미분류만' 두 가지로 연다 — 미분류 타일에서 열면 할 일만 보여야 한다.
  const [slicesOpen, setSlicesOpen] = useState(false);
  const [holdingsOpen, setHoldingsOpen] = useState(false);
  const [classify, setClassify] = useState<"all" | "unclassified" | null>(null);
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
  const rows = useMemo(() => holdings.data?.items ?? [], [holdings.data]);
  const dimLabel = DIMENSIONS.find((d) => d.id === dimension)?.label ?? "";

  // 종목이 든 조각만 바스켓을 연다. 예수금 조각은 종목이 없다.
  const hasHoldings = (s: AllocationSlice) =>
    rows.some((h) => h.market_value_krw != null && axisKeyOf(h, dimension) === s.key);
  const classified = (data?.items ?? []).filter((s) => s.key != null && hasHoldings(s));
  // 목록은 이미 큰 순(미분류는 맨 뒤)이라 첫 분류가 가장 크다.
  const largest = classified[0] ?? null;
  const unclassifiedRows = rows.filter((h) => axisKeyOf(h, dimension) == null);

  // ⚠️분모는 **위 카드와 같은 총자산**이어야 한다. 예전에는 여기만
  //   주식 평가액(holdings.total)으로 나눠서, 같은 화면에서 SOXL 이
  //   섹터 쪽 기준으로는 19.9% 인데 이 카드에서는 20.6% 로 보였다.
  //   머리글에 적힌 '기준 총자산' 과도 어긋났다. 리밸런싱 화면과
  //   분모가 갈려 같은 버그를 한 번 고친 적이 있는데, 이 카드가
  //   클라이언트에서 따로 계산하는 바람에 되살아나 있었다.
  const holdingSlices: AllocationSlice[] = rows.map((h) => ({
    key: h.asset_id,
    label: h.name ?? h.ticker,
    market_value_krw: h.market_value_krw ?? "0",
    weight:
      data?.total_market_value_krw && Number(data.total_market_value_krw) !== 0
        ? String(Number(h.market_value_krw ?? 0) / Number(data.total_market_value_krw))
        : "0",
    position_count: 1,
  }));

  // 조각 하나에 든 종목들. 값은 /allocation 과 같은 **동기화 스냅샷**(market_value_krw).
  const basketRows = useMemo(() => {
    if (!basket) return [];
    return rows
      .filter((h) => h.market_value_krw != null && axisKeyOf(h, dimension) === basket.key)
      .sort((a, b) => Number(b.market_value_krw) - Number(a.market_value_krw));
  }, [basket, rows, dimension]);
  const basketTotal = basketRows.reduce((sum, h) => sum + Number(h.market_value_krw), 0);

  const classifyRows = classify === "unclassified" ? unclassifiedRows : rows;

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
        </div>

        {/* 요약 4칸 — 대표 숫자 하나씩, 누르면 세부. */}
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="기준 총자산"
            value={formatKrwString(data?.total_market_value_krw)}
            hint="주식 + 예수금 · 마지막 동기화"
            loading={allocation.isLoading}
            onClick={() => setHoldingsOpen(true)}
            actionHint="눌러서 종목 비중 전체 보기"
          />
          <StatTile
            label={`${dimLabel} 분류 수`}
            value={data ? `${classified.length}개` : null}
            hint="미분류·예수금 제외"
            loading={allocation.isLoading}
            onClick={() => setSlicesOpen(true)}
            actionHint="눌러서 분류별 비중 보기"
          />
          <StatTile
            label={`가장 큰 ${dimLabel}`}
            value={largest ? `${(Number(largest.weight) * 100).toFixed(1)}%` : null}
            hint={
              largest
                ? `${largest.label} · ${formatKrwString(largest.market_value_krw)}`
                : "총자산 대비"
            }
            loading={allocation.isLoading}
            onClick={largest ? () => setBasket(largest) : undefined}
            actionHint="눌러서 담긴 종목 보기"
          />
          {/* ⚠️미분류는 0원이어도 타일을 빼지 않는다 — 숨기지 않고 늘 같은 자리에 둔다. */}
          <StatTile
            label="미분류"
            value={formatKrwString(unclassified ?? (data ? "0" : null))}
            hint={
              unclassifiedRows.length > 0
                ? `${unclassifiedRows.length}종목`
                : "모두 분류됨"
            }
            loading={allocation.isLoading}
            onClick={() => setClassify("unclassified")}
            actionHint="눌러서 그 자리에서 분류하기"
          />
        </div>

        {/* ★2026-09-22 전체 점검에서 걸렸다: `wide` 로 남아 페이지가 스크롤됐다.
            ★2026-09-25: 종목별 분류 표는 **화면에서 뺐다** — '분류 편집' 버튼과
              미분류 타일이 여는 팝업으로 옮겼다. 남은 두 막대 카드가 나란히 선다. */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            // ⚠️`auto-rows-[minmax(0,1fr)]` 가 없으면 1열일 때 행이 내용 높이로 자라 페이지가 넘친다.
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:grid-cols-2",
          )}
        >
          <StubCard
            title={`${dimLabel} 비중`}
            subtitle="평가금액(KRW) 기준 · 막대를 누르면 담긴 종목"
            scrollBody
            action={
              <HeaderButton label="분류 편집" onClick={() => setClassify("all")} />
            }
          >
            <WeightBars
              items={data?.items ?? []}
              onPick={setBasket}
              canPick={hasHoldings}
            />
          </StubCard>

          <StubCard
            title="종목 비중"
            subtitle="총자산 대비 · 평가금액 순 상위 8"
            scrollBody
            action={<HeaderButton label="전체 목록" onClick={() => setHoldingsOpen(true)} />}
          >
            <WeightBars items={holdingSlices.slice(0, 8)} />
          </StubCard>
        </div>
      </PageContainer>

      {/* 막대(분류) → 그 분류 바스켓. 비중의 분모는 총자산이 아니라 **그 분류의
          종목 합계**다(자산 현황 배분 도넛과 같은 규칙). */}
      <Modal
        open={basket != null}
        onClose={() => setBasket(null)}
        title={basket?.label ?? ""}
        subtitle={
          basket
            ? `${dimLabel} · ${basketRows.length}종목 · 분류 합계 ${formatKrwString(String(basketTotal))} · 마지막 동기화 기준`
            : undefined
        }
        width={640}
      >
        <DataTable
          columns={["종목", "평가금액", "분류 내 비중"]}
          align={["left", "right", "right"]}
          empty="이 분류에 든 종목이 없습니다"
        >
          {basketRows.map((h) => {
            const share = basketTotal > 0 ? Number(h.market_value_krw) / basketTotal : 0;
            return (
              <tr
                key={`${h.account_id}-${h.asset_id}`}
                className="border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    <span>{h.ticker}</span>
                    <span className="max-w-[200px] truncate text-[10px] font-semibold text-ink-muted">
                      {h.name}
                    </span>
                  </span>
                </Cell>
                <Cell>{formatKrwString(h.market_value_krw)}</Cell>
                <Cell strong>{`${(share * 100).toFixed(1)}%`}</Cell>
              </tr>
            );
          })}
        </DataTable>
      </Modal>

      <Modal
        open={slicesOpen}
        onClose={() => setSlicesOpen(false)}
        title={`${dimLabel}별 비중`}
        subtitle={
          data?.total_market_value_krw
            ? `기준 총자산 ${formatKrwString(data.total_market_value_krw)} · 주식 + 예수금 · 마지막 동기화`
            : undefined
        }
        width={640}
      >
        <DataTable
          columns={["분류", "종목 수", "평가금액", "총자산 대비"]}
          align={["left", "right", "right", "right"]}
          empty={allocation.isLoading ? "불러오는 중…" : "계좌를 연동하면 비중이 계산됩니다"}
        >
          {(data?.items ?? []).map((s) => {
            const pickable = hasHoldings(s);
            return (
              <tr
                key={s.key ?? "__unclassified__"}
                onClick={
                  pickable
                    ? () => {
                        setSlicesOpen(false);
                        setBasket(s);
                      }
                    : undefined
                }
                className={cn(
                  "border-b border-hairline transition-colors",
                  pickable && "cursor-pointer hover:bg-canvas-soft",
                )}
              >
                <Cell left strong>
                  <span className={s.key === null ? "text-ink-muted" : undefined}>{s.label}</span>
                </Cell>
                <Cell>{s.position_count}</Cell>
                <Cell>{formatKrwString(s.market_value_krw)}</Cell>
                <Cell strong>{`${(Number(s.weight) * 100).toFixed(1)}%`}</Cell>
              </tr>
            );
          })}
        </DataTable>
      </Modal>

      <Modal
        open={holdingsOpen}
        onClose={() => setHoldingsOpen(false)}
        title="종목 비중"
        subtitle={
          data?.total_market_value_krw
            ? `총자산 ${formatKrwString(data.total_market_value_krw)} 대비 · ${rows.length}종목 · 평가금액 순`
            : "총자산 대비 · 평가금액 순"
        }
        width={640}
      >
        <WeightBars items={holdingSlices} />
      </Modal>

      <Modal
        open={classify != null}
        onClose={() => setClassify(null)}
        title={classify === "unclassified" ? `${dimLabel} 미분류 종목` : "종목별 분류"}
        subtitle="섹터를 고치면 MANUAL 로 표시됩니다"
        width={720}
      >
        <DataTable
          // ⚠️6칸이면 좁은 폭에서 표가 잘린다(실측 1160px: 표 518 vs 카드 449).
          //   정보를 버리지 않고 **합친다** — 국가는 종목 옆 태그로,
          //   세부 산업은 섹터 아래 줄로 내린다.
          columns={["종목", "섹터 · 세부 산업", "평가금액", ""]}
          align={["left", "left", "right", "right"]}
          empty={
            holdings.isLoading
              ? "불러오는 중…"
              : classify === "unclassified"
                ? "미분류 종목이 없습니다"
                : "보유 종목이 없습니다"
          }
        >
          {classifyRows.map((h) => (
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
              onSave={(sector) => patch.mutate({ assetId: h.asset_id, sector })}
            />
          ))}
        </DataTable>
      </Modal>
    </>
  );
}

/** 카드 헤더의 작은 버튼('전체 목록' 등). */
function HeaderButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
    >
      {label}
    </button>
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
