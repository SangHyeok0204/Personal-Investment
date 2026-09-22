"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getPortfolioHoldings, getPortfolioSummary } from "@/lib/api";
import {
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "@/lib/format";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/utils";

// 보유 종목 전체 — /portfolio 의 요약 표보다 컬럼이 많다(시장·통화·환율·매입금액).
// 정렬은 클라이언트에서 한다: 행이 수십~수백 개 수준이라 서버 왕복을 늘릴 이유가 없다.
//
// ★2026-09-22: **상단 칸 셋을 더해 보면 안 맞았다.**
//     총 매입금액 33,352,051 + 평가손익 2,881,334 = 36,233,385
//     총 평가금액 36,407,647                        ← 174,262 모자람
//   더해 본 사람에게는 고장 난 화면이다. 원인은 **키움의 평가손익이 제비용을
//   뺀 값**이라는 것 — 낼 수수료를 미리 빼고 "지금 다 팔면 손에 남는 것"을 적는다.
//   모형(0.25% × 매입 + 0.25% × 평가)이 174,399 로 실측과 137원 차이(99.9%)라
//   확인됐고, 0.25% 는 체결 원장에서 잰 매수 수수료율과 같다.
//   그래서 '제비용' 칸을 만들어 **매입 + 손익 + 제비용 = 평가금액** 이 닫히게 했다.
//
// ⚠️칸에 적는 값은 **실측 잔차**다. 모형값을 적으면 다시 안 맞는다 —
//   합이 안 맞는 것이 애초에 고치려던 문제다.

type SortKey =
  | "market_value_krw"
  | "unrealized_pnl_krw"
  | "unrealized_return"
  | "ticker";

const MARKET_FILTERS = [
  { id: "all", label: "전체" },
  { id: "KR", label: "국내" },
  { id: "US", label: "해외" },
] as const;

export default function HoldingsPage() {
  const { accountId, connected, isError } = useAccount();
  const [sortKey, setSortKey] = useState<SortKey>("market_value_krw");
  const [country, setCountry] = useState<string>("all");
  const [feeOpen, setFeeOpen] = useState(false);

  const summary = useQuery({
    queryKey: ["portfolioSummary", accountId],
    queryFn: () => getPortfolioSummary(accountId),
    staleTime: 30_000,
  });
  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 30_000,
  });

  const rows = useMemo(() => {
    const items = (holdings.data?.items ?? []).filter((h) =>
      country === "all"
        ? true
        : country === "KR"
          ? h.country === "KR"
          : h.country !== "KR",
    );
    const num = (v: string | null) => (v == null ? Number.NEGATIVE_INFINITY : Number(v));
    return [...items].sort((a, b) => {
      if (sortKey === "ticker") return a.ticker.localeCompare(b.ticker);
      return num(b[sortKey]) - num(a[sortKey]);
    });
  }, [holdings.data, sortKey, country]);

  // ⚠️같은 값을 17줄 반복하는 칸은 폭만 먹는다(실측: 시장 전부 "US", 환율 전부
  //   1,375.50 → 표가 1024px 에서 잘렸다). **값이 하나뿐일 때만** 접고 제목줄에
  //   한 번 적는다. 달라지면 칸이 다시 나온다 — 국내 종목을 사면 시장이 갈린다.
  const uniq = (values: (string | null | undefined)[]) => {
    const set = new Set(values.filter((v) => v != null && v !== ""));
    return set.size === 1 ? ([...set][0] as string) : null;
  };
  const oneMarket = rows.length > 1 ? uniq(rows.map((h) => h.market)) : null;
  const oneRate =
    rows.length > 1
      ? uniq(rows.map((h) => (h.currency === "KRW" ? null : h.exchange_rate)))
      : null;
  const foldMarket = oneMarket != null;
  const foldRate = oneRate != null && rows.every((h) => h.currency !== "KRW");

  const s = summary.data;

  return (
    <>
      <Topbar title="보유 종목" subtitle="종목별 수량 · 평단 · 손익" />
      <PageContainer fit>
        {!connected && (
          <NotConnectedBanner
            what="키움 잔고 조회"
            message={
              isError
                ? "API 서버에 연결하지 못했습니다 — 백엔드(uvicorn)가 떠 있는지 확인하세요."
                : undefined
            }
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {/* ⚠️네 칸이 **더해진다**: 매입 + 평가손익 + 제비용 = 평가금액. */}
          <StatTile
            label="총 매입금액"
            value={formatKrwString(s?.purchase_amount_krw)}
            hint={
              s?.position_count
                ? `${s.position_count}종목 · 수수료 뺀 약정금액`
                : "수수료 뺀 약정금액"
            }
            loading={summary.isLoading}
          />
          <StatTile
            label="평가손익"
            value={formatKrwSigned(s?.unrealized_pnl_krw)}
            hint={
              s?.unrealized_return != null
                ? `${formatPercentString(s.unrealized_return)} · 제비용 뺀 뒤`
                : "제비용 뺀 뒤"
            }
            accent="auto"
            loading={summary.isLoading}
          />
          {/* ⚠️부호는 **+** 다. 제비용은 평가손익에서 이미 빠진 몫이라, 네 칸이
              왼쪽에서 오른쪽으로 더해지려면 여기서 되돌려 놓아야 한다.
              (비용인데 왜 +냐 — 빼는 게 아니라 **이미 뺀 것을 되돌리는** 칸이다.) */}
          <StatTile
            label="제비용 되돌림"
            value={formatKrwSigned(s?.fee_reserve_krw)}
            hint="평가손익에서 미리 뺀 몫 · 눌러서 설명"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setFeeOpen(true)}
            loading={summary.isLoading}
          />
          <StatTile
            label="총 평가금액"
            value={formatKrwString(s?.securities_value_krw)}
            hint="매입 + 평가손익 + 제비용"
            loading={summary.isLoading}
          />
        </div>

        {/* ★2026-09-22 전체 점검에서 걸렸다: 이 화면만 `wide` 로 남아 있어
            **페이지가 244px 스크롤**됐다(사용자가 요청한 1페이지 원칙 위반).
            ⚠️`fit` 으로 바꾸는 것만으로는 부족하다 — 카드 본문 전체를 스크롤하면
              필터 칩이 같이 밀려 올라가 안 보인다. 칩은 고정하고 **표만** 스크롤한다. */}
        <StubCard
          title="보유 종목 전체"
          subtitle={[
            "평가금액은 KRW 환산 기준",
            foldMarket ? `전 종목 ${oneMarket}` : "국내 · 해외 통합",
            foldRate ? `환율 ${formatPriceString(oneRate, "USD")}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          className="min-h-0 flex-1"
        >
          <div className="flex h-full min-h-0 flex-col">
          <div className="mb-3 flex shrink-0 flex-wrap items-center gap-2">
            {MARKET_FILTERS.map((f) => (
              <Chip
                key={f.id}
                active={country === f.id}
                onClick={() => setCountry(f.id)}
              >
                {f.label}
              </Chip>
            ))}
            <span className="mx-1 h-4 w-px bg-hairline" />
            <Chip
              active={sortKey === "market_value_krw"}
              onClick={() => setSortKey("market_value_krw")}
            >
              평가금액순
            </Chip>
            <Chip
              active={sortKey === "unrealized_pnl_krw"}
              onClick={() => setSortKey("unrealized_pnl_krw")}
            >
              손익순
            </Chip>
            <Chip
              active={sortKey === "unrealized_return"}
              onClick={() => setSortKey("unrealized_return")}
            >
              수익률순
            </Chip>
            <Chip active={sortKey === "ticker"} onClick={() => setSortKey("ticker")}>
              종목코드순
            </Chip>
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {rows.length}종목
            </span>
          </div>

          {/* 남는 높이를 표가 갖고, 넘치면 **여기서만** 스크롤한다. */}
          <div className="min-h-0 flex-1 overflow-y-auto">
          <DataTable
            columns={[
              "종목",
              ...(foldMarket ? [] : ["시장"]),
              "수량",
              "평단",
              "현재가",
              "매입금액",
              "평가금액",
              "평가손익",
              "수익률",
              ...(foldRate ? [] : ["환율"]),
            ]}
            align={[
              "left",
              ...(foldMarket ? [] : ["left" as const]),
              "right", "right", "right",
              "right", "right", "right", "right",
              ...(foldRate ? [] : ["right" as const]),
            ]}
            empty={
              holdings.isLoading
                ? "불러오는 중…"
                : connected
                  ? "보유 종목이 없습니다"
                  : "계좌를 연동하면 보유 종목이 표시됩니다"
            }
          >
            {rows.map((h) => (
              <tr
                key={`${h.account_id}-${h.asset_id}`}
                className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
              >
                <Cell left strong>
                  <span className="flex items-center gap-2">
                    {h.name ?? h.ticker}
                    <span className="text-[10px] font-semibold text-ink-faint">
                      {h.ticker}
                    </span>
                  </span>
                </Cell>
                {!foldMarket && (
                  <Cell left tone="muted">
                    {h.market}
                  </Cell>
                )}
                <Cell>{formatQuantityString(h.quantity)}</Cell>
                <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
                <Cell>{formatPriceString(h.current_price, h.currency)}</Cell>
                <Cell tone="muted">
                  {formatPriceString(h.purchase_amount_local, h.currency)}
                </Cell>
                <Cell strong>{formatKrwString(h.market_value_krw)}</Cell>
                <Cell tone={toneOf(h.unrealized_pnl_krw)}>
                  {formatKrwSigned(h.unrealized_pnl_krw)}
                </Cell>
                <Cell tone={toneOf(h.unrealized_return)}>
                  {formatPercentString(h.unrealized_return)}
                </Cell>
                {/* 환율은 수집 시점 값 — 화면이 다시 계산하지 않는다. */}
                {!foldRate && (
                  <Cell tone="muted">
                    {h.currency === "KRW"
                      ? "—"
                      : formatPriceString(h.exchange_rate, "USD")}
                  </Cell>
                )}
              </tr>
            ))}
          </DataTable>
          </div>
          </div>
        </StubCard>
      </PageContainer>

      <Modal
        open={feeOpen}
        onClose={() => setFeeOpen(false)}
        title="제비용이 왜 따로 있나"
        subtitle="매입 + 평가손익 + 제비용 = 평가금액"
      >
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>증권사 평가손익은 제비용을 뺀 값입니다.</strong> 낼 수수료를
            미리 빼고 &quot;지금 다 팔면 손에 남는 것&quot;을 적습니다. 그래서
            매입금액과 평가손익만 더하면 평가금액에 모자랍니다 — 실측으로{" "}
            {formatKrwString(s?.fee_reserve_krw)} 부족했습니다. 그 몫을 칸으로
            꺼내 산수가 닫히게 했습니다.
          </li>
          <li>
            <strong>무엇인지 확인했습니다.</strong> 이미 낸 매수 수수료(매입금액의
            0.25%)와 지금 팔면 낼 매도 수수료(평가금액의 0.25%)를 더한 모형이{" "}
            {formatKrwString(s?.fee_reserve_modelled_krw)} 로, 실측과{" "}
            {s?.fee_reserve_krw && s?.fee_reserve_modelled_krw
              ? formatKrwString(
                  String(
                    Math.abs(
                      Number(s.fee_reserve_krw) -
                        Number(s.fee_reserve_modelled_krw),
                    ),
                  ),
                )
              : "—"}{" "}
            차이입니다(99.9%). 0.25% 는 체결 원장에서 실제로 잰 매수 수수료율과
            같습니다(17종목 전부 0.241~0.250%).
          </li>
          <li>
            <strong>칸에 적는 값은 모형이 아니라 실측입니다.</strong> 모형값을
            적으면 다시 합이 안 맞는데, 합이 안 맞는 것이 애초에 고치려던
            문제였습니다.
          </li>
          <li>
            <strong>수익률의 분모는 매입금액입니다.</strong> 분자는 제비용을 뺀
            평가손익이라 &quot;팔고 나서의 수익률&quot;에 가깝습니다 — 주가만으로
            본 수익률보다 조금 낮게 나옵니다.
          </li>
        </ul>
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
