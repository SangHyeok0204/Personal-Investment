"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { StackedBarChart, type StackColumn } from "@/components/charts/stacked-bar-chart";
import { CHART_MUTED } from "@/components/charts/donut-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  ListButton,
  NotConnectedBanner,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getFilings, type Filing, type Filings } from "@/lib/api";
import { CoveragePanel } from "@/components/research/coverage-panel";
import { cn } from "@/lib/utils";

// 공시 — 보유 종목이 SEC 에 무엇을 신고했나.
//
// ★키가 필요 없다. SEC 는 연락처가 담긴 User-Agent 만 요구한다.
//
// ★**내부자 서식을 나열하지 않는다.** 실측(NVDA 최근 1001건): Form 4 가 556건,
//   Form 144 가 247건으로 803건이 임원 서류다. 읽을 만한 건 8-K 62 · 10-Q 19 ·
//   10-K 6 뿐이다. 그대로 쏟으면 중요한 공시가 묻히므로 건수로만 낸다.
//
// ⚠️ETF 는 SEC 개별 공시 대상이 **아니다**(신탁 단위로 낸다). 보유 17종목 중
//   6개가 여기 해당한다 — "공시 없음"으로 적으면 거짓말이 된다.
//   ⚠️단, 전부 그런 건 아니다 — GLD(금 SPDR)는 상품신탁이라 10-K 를 낸다.
//     ETF 라고 하드코딩하지 않고 SEC 에 CIK 가 있는지로만 판단한다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 본문은 **월별 막대**(서식 성격별
//   누적), 목록은 막대·요약 칸·종목 행을 눌러 여는 팝업. 조회 구간이 180일이라
//   월 단위가 맞다 — 일 단위로 쪼개면 막대가 180개라 읽히지 않는다.

// 막대 색은 아래 배지 색과 같은 계열로 둔다 — 막대와 목록의 배지를 눈이 잇도록.
const CATEGORY_COLORS: Record<string, string> = {
  "실적·정기": "#4C2C19",
  수시: "#6390BF",
  지분: "#A33A2A",
  기타: CHART_MUTED,
};

const CATEGORY_TONE: Record<string, string> = {
  "실적·정기": "bg-ge-navy/10 text-ge-navy",
  수시: "bg-ge-point/12 text-ge-point",
  지분: "bg-bid-soft text-bid",
  기타: "bg-canvas-soft text-ink-faint",
};

function daysAgo(iso: string): number {
  const then = new Date(`${iso}T00:00:00`);
  return Math.floor((Date.now() - then.getTime()) / 86_400_000);
}

function whenLabel(iso: string): string {
  const d = daysAgo(iso);
  if (d <= 0) return "오늘";
  if (d === 1) return "어제";
  if (d < 7) return `${d}일 전`;
  return iso.slice(5);
}

export default function FilingsPage() {
  const router = useRouter();
  const { accountId, connected } = useAccount();
  const [category, setCategory] = useState<string | null>(null);
  // 막대·요약 칸·종목 행 → 그 범위의 공시 목록. null 이면 닫힘.
  const [scope, setScope] = useState<ListScope | null>(null);

  const filings = useQuery({
    queryKey: ["filings", accountId],
    queryFn: () => getFilings(accountId),
    // SEC 는 보유 종목 수만큼 두드려야 한다. 서버도 1시간 캐시를 들고 있다.
    staleTime: 30 * 60_000,
  });

  const data = filings.data;
  const all = data?.filings ?? [];
  const inScope = all.filter((f) => scope != null && matchScope(f, scope));
  const rows = inScope.filter((f) => category == null || f.category === category);

  const monthColumns: StackColumn[] = useMemo(() => {
    const acc = new Map<string, Map<string, number>>();
    for (const f of data?.filings ?? []) {
      const m = f.filed_date.slice(0, 7);
      const e = acc.get(m) ?? new Map<string, number>();
      e.set(f.category, (e.get(f.category) ?? 0) + 1);
      acc.set(m, e);
    }
    const order = data?.categories ?? [];
    return [...acc.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([m, e]) => ({
        key: m,
        label: m,
        total: [...e.values()].reduce((sum, v) => sum + v, 0),
        segments: order
          .map((c) => ({ key: c, label: c, value: e.get(c) ?? 0 }))
          .filter((x) => x.value > 0),
      }));
  }, [data]);

  const openScope = (next: ListScope) => {
    setCategory(null);
    setScope(next);
  };

  const recent30 = (data?.filings ?? []).filter((f) => daysAgo(f.filed_date) <= 30);
  const sourceDown = !filings.isLoading && (filings.isError || data?.source_ok === false);
  const emptyText = filings.isLoading
    ? "불러오는 중…"
    : sourceDown
      ? "SEC 에서 받지 못했습니다"
      : connected
        ? "이 구간에 공시가 없습니다"
        : "계좌를 연동하면 보유 종목 공시가 표시됩니다";

  return (
    <>
      <Topbar title="종목 공시" />
      <PageContainer fit>
        <CoveragePanel kind="filings" />
        {!connected && !filings.isLoading && <NotConnectedBanner what="보유 종목" />}
        {sourceDown && connected && (
          <SourceDownBanner
            source="SEC EDGAR"
            detail="수집 실패"
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 30일 공시"
            value={data ? `${recent30.length}건` : null}
            hint={
              data
                ? `${data.window_days}일 내 전체 ${data.filings.length}건`
                : "내부자 서식 제외"
            }
            actionHint="눌러서 목록 보기"
            onClick={() => openScope({ kind: "recent" })}
            loading={filings.isLoading}
          />
          <StatTile
            label="실적·정기"
            value={
              data
                ? `${data.filings.filter((f) => f.category === "실적·정기").length}건`
                : null
            }
            hint="10-K · 10-Q · 20-F"
            actionHint="눌러서 목록 보기"
            onClick={() => openScope({ kind: "category", category: "실적·정기" })}
            loading={filings.isLoading}
          />
          <StatTile
            label="수시보고"
            value={
              data ? `${data.filings.filter((f) => f.category === "수시").length}건` : null
            }
            hint="8-K · 증권신고 · 주총"
            actionHint="눌러서 목록 보기"
            onClick={() => openScope({ kind: "category", category: "수시" })}
            loading={filings.isLoading}
          />
          <StatTile
            label="내부자 서식"
            value={data ? `${data.insider_total}건` : null}
            hint={
              data
                ? `최근 ${data.insider_window_days}일 · 그중 30일 내 ${data.insider_recent_total}건`
                : "3 · 4 · 5 · 144"
            }
            // ★계획 A6 — 판단이 담긴 거래만 센 순매수는 `내부자 거래` 화면에 있다.
            actionHint="눌러서 내부자 거래 화면"
            onClick={() => router.push("/research/insiders")}
            loading={filings.isLoading}
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
            title="월별 공시"
            subtitle={`${all.length}건 · 막대를 누르면 그 달 공시`}
            action={<ListButton onClick={() => openScope({ kind: "all" })} />}
            scrollBody
          >
            {filings.isLoading || all.length === 0 ? (
              <CardEmpty text={emptyText} />
            ) : (
              <StackedBarChart
                columns={monthColumns}
                colors={CATEGORY_COLORS}
                height={420}
                formatTotal={(v) => `${v}건`}
                selected={scope?.kind === "month" ? scope.month : null}
                onSelect={(key, sticky) => {
                  if (sticky && key) openScope({ kind: "month", month: key });
                }}
              />
            )}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              {(data?.categories ?? []).map((c) => (
                <span key={c} className="mr-2 inline-flex items-center gap-1">
                  <span style={{ color: CATEGORY_COLORS[c] ?? CHART_MUTED }} className="font-bold">
                    ■
                  </span>
                  {c}
                </span>
              ))}
              · 제출일 기준 · 첫/이번 달은 일부만 · 내부자 서식(3·4·5·144) 제외
            </p>
          </StubCard>

          <StubCard
            title="종목별"
            subtitle={
              data
                ? `조회 ${data.covered_count} · 대상 아님 ${data.not_covered_count}`
                : "보유 종목"
            }
            scrollBody
          >
            {filings.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (data?.tickers.length ?? 0) === 0 ? (
              <CardEmpty text="보유 종목이 없습니다" />
            ) : (
              <Coverage
                data={data!}
                onPick={(ticker) => openScope({ kind: "ticker", ticker })}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={scope != null}
        onClose={() => setScope(null)}
        title={scope ? scopeTitle(scope, data) : ""}
        subtitle={`${rows.length}건 · 최근이 위 · 제출일을 누르면 SEC 원문`}
        width={820}
      >
        <div className="mb-2 flex flex-wrap gap-1">
          <ModalChip active={category == null} onClick={() => setCategory(null)}>
            전체 {inScope.length}
          </ModalChip>
          {(data?.categories ?? [])
            .filter((c) => scope?.kind !== "category" || scope.category === c)
            .map((c) => (
              <ModalChip key={c} active={category === c} onClick={() => setCategory(c)}>
                {c} {inScope.filter((f) => f.category === c).length}
              </ModalChip>
            ))}
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["종목", "공시", "내용", "제출일"]}
            align={["left", "left", "left", "right"]}
            empty={emptyText}
          >
            {rows.map((f) => (
              <tr
                key={`${f.ticker}-${f.url}`}
                className="border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  <span className="flex items-center gap-1.5">
                    <span className="max-w-[140px] truncate">
                      {f.company ?? f.ticker}
                    </span>
                    <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                      {f.ticker}
                    </span>
                  </span>
                </Cell>
                <Cell left>
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold",
                        CATEGORY_TONE[f.category] ?? CATEGORY_TONE["기타"],
                      )}
                    >
                      {f.form}
                    </span>
                    <span className="truncate text-[11px] font-semibold text-ink-secondary">
                      {f.form_label}
                    </span>
                  </span>
                </Cell>
                <Cell left tone="muted">
                  {/* 8-K 는 항목 코드가 곧 내용이다. 없으면 비워 둔다 —
                      "내용 없음"이라고 적으면 틀린 말이 된다. */}
                  <span className="block max-w-[280px] truncate text-[11px]">
                    {f.item_labels.length > 0 ? f.item_labels.join(" · ") : "—"}
                  </span>
                </Cell>
                <Cell>
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-ge-point underline-offset-2 hover:underline"
                  >
                    {whenLabel(f.filed_date)} ↗
                  </a>
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>
    </>
  );
}

function Coverage({
  data,
  onPick,
}: {
  data: Filings;
  onPick: (ticker: string) => void;
}) {
  const covered = data.tickers.filter((t) => t.cik != null);
  const notCovered = data.tickers.filter((t) => t.cik == null);
  const failed = data.tickers.filter((t) => !t.ok);

  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.ticker).join(", ")} 받지 못함 · 공시 없음과는 다름
        </p>
      )}

      <DataTable
        columns={["종목", "공시", "내부자", "최근 30일"]}
        align={["left", "right", "right"]}
        empty="표시할 종목이 없습니다"
      >
        {covered.map((t) => (
          <tr
            key={t.ticker}
            onClick={() => onPick(t.ticker)}
            className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
          >
            <Cell left strong>
              <span className="flex items-center gap-1.5">
                <span className="max-w-[110px] truncate">{t.name ?? t.ticker}</span>
                <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                  {t.ticker}
                </span>
              </span>
            </Cell>
            <Cell strong={t.filing_count > 0} tone={t.filing_count === 0 ? "muted" : undefined}>
              {t.filing_count}
              {t.truncated && <span className="ml-0.5 text-ask">+</span>}
            </Cell>
            <Cell tone="muted">{t.insider_count}</Cell>
            {/* ⚠️**몰림만 보여 준다.** 고르게 났다면 최근 1/3 구간에 33% 쯤
                들어온다 — 그보다 한참 높으면 무슨 일이 있었다는 뜻이다(락업
                해제·베스팅 등). 방향은 모른다: 서식 4 는 매수·매도·부여를
                모두 담고, SEC 제출 목록에는 그 구분이 없다. */}
            <Cell
              tone={
                t.insider_count >= 10 &&
                t.insider_recent_count / t.insider_count >= 0.6
                  ? undefined
                  : "muted"
              }
              strong={
                t.insider_count >= 10 &&
                t.insider_recent_count / t.insider_count >= 0.6
              }
            >
              {t.insider_count
                ? `${t.insider_recent_count} (${Math.round(
                    (t.insider_recent_count / t.insider_count) * 100,
                  )}%)`
                : "—"}
            </Cell>
          </tr>
        ))}
      </DataTable>

      {notCovered.length > 0 && (
        <div className="rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
          <p className="mb-1 text-[11px] font-bold text-ge-navy">
            SEC 개별 공시 대상 아님 ({notCovered.length})
          </p>
          <p className="mb-1.5 text-[11px] leading-snug text-ink-muted">
            신탁 단위 공시 · <strong>공시 없음 아님</strong>
          </p>
          <div className="flex flex-wrap gap-1">
            {notCovered.map((t) => (
              <span
                key={t.ticker}
                title={t.name ?? undefined}
                className="rounded bg-canvas px-1.5 py-0.5 text-[10px] font-bold text-ink-faint"
              >
                {t.ticker}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

type ListScope =
  | { kind: "all" }
  | { kind: "recent" }
  | { kind: "month"; month: string }
  | { kind: "category"; category: string }
  | { kind: "ticker"; ticker: string };

function matchScope(f: Filing, scope: ListScope): boolean {
  switch (scope.kind) {
    case "all":
      return true;
    case "recent":
      return daysAgo(f.filed_date) <= 30;
    case "month":
      return f.filed_date.startsWith(scope.month);
    case "category":
      return f.category === scope.category;
    case "ticker":
      return f.ticker === scope.ticker;
  }
}

function scopeTitle(scope: ListScope, data: Filings | undefined): string {
  switch (scope.kind) {
    case "all":
      return `공시 전체 (최근 ${data?.window_days ?? "—"}일)`;
    case "recent":
      return "최근 30일 공시";
    case "month":
      return `${scope.month} 공시`;
    case "category":
      return `${scope.category} 공시`;
    case "ticker": {
      const t = data?.tickers.find((x) => x.ticker === scope.ticker);
      return `${t?.name ?? scope.ticker} (${scope.ticker}) 공시`;
    }
  }
}

/** 팝업 안(밝은 바탕)의 서식 성격 필터. */
function ModalChip({
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
        "rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors",
        active
          ? "bg-ge-header text-white"
          : "bg-canvas-soft text-ink-secondary hover:bg-ge-blue-bg",
      )}
    >
      {children}
    </button>
  );
}

