"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import { AnimatedNumber } from "@/components/ui/animated-number";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import {
  getFxExposure,
  getFxRate,
  getInclusion,
  getPortfolioHoldings,
  getPortfolioSummary,
  type InclusionEvent,
  type InclusionHolding,
  type PortfolioHolding,
} from "@/lib/api";
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

// ★2026-09-25 사용자 지시: 국내/해외 필터 칩 대신 **상장거래소 열**을 둔다.
//   후보는 이 여섯 개로 고정한다. 코드는 상장 국가(country)로 고른다.
const EXCHANGE_LABELS: Record<string, string> = {
  US: "미국",
  CN: "중국",
  KR: "한국",
  HK: "홍콩",
  JP: "일본",
  IN: "인도",
};

function exchangeOf(h: PortfolioHolding): string {
  return EXCHANGE_LABELS[h.country] ?? EXCHANGE_LABELS[h.market] ?? "기타";
}

// ★2026-09-25 사용자 지시: 정렬 칩 대신 **제목 칸을 눌러** 오름/내림차순을 바꾼다.
//   `value` 가 null 이면 방향과 무관하게 맨 아래로 보낸다 — 값이 없는 종목이
//   오름차순에서 맨 위를 차지하면 정렬이 고장 난 것처럼 보인다.
type Column = {
  label: string;
  align: "left" | "right";
  value: (h: PortfolioHolding) => number | string | null;
};

const num = (v: string | null | undefined) => (v == null ? null : Number(v));

// ★2026-09-25 편입비 화면을 없애고 그 내용을 이 표의 열로 옮겼다(사용자 지시).
//   ⚠️편입비는 **원가(USD) 기준**이고 매매 이력 **전체**를 되감은 값이다 — 이 표의
//     다른 열(평가액 기준, KRW)과 뜻이 다르다. 제목줄 안내문에 적어 둔다.
//   '원가' 열은 옮기지 않았다. 매입금액 열과 같은 값이다.
const KIND_LABEL: Record<InclusionEvent["kind"], string> = {
  ENTRY: "신규 편입",
  ADD: "추가 매수",
  TRIM: "일부 매도",
  EXIT: "전량 청산",
};

const KIND_STYLE: Record<InclusionEvent["kind"], string> = {
  ENTRY: "bg-ge-blue-bg text-ge-point",
  ADD: "bg-canvas-soft text-ink-secondary",
  TRIM: "bg-canvas-soft text-ink-secondary",
  EXIT: "bg-hairline text-ink-muted",
};

function pct(value: string | null | undefined, digits = 1): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}

function usd(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

// ★2026-09-25 환노출 화면을 없애고 이 표의 토글로 옮겼다(사용자 지시).
//   증권사 KRW 평가손익은 "현지통화 손익 × 현재 환율"이다(SOXL 로 검산) — 원금에
//   붙은 환차가 빠져 있다. 그래서 두 관점을 현지통화 값과 두 환율로 다시 계산한다:
//     ON  (환 반영)   평가금액 = 현지평가 × 현재환율
//                     평가손익 = 현지손익 × 현재환율 + 현지원가 × (현재환율 − 매입환율)
//     OFF (환 미반영) 매입 환율이 그대로였다고 보고 — 평가금액 = 현지평가 × 매입환율,
//                     평가손익 = 현지손익 × 매입환율 (주가 손익만)
//   현재환율 = 네이버(하나은행 고시), 못 받으면 증권사. 매입환율 = 매수 체결일
//   종가 환율의 **추정**(증권사가 매입 환율을 주지 않는다). 추정이 없는 종목은
//   현재환율로 두어 환차를 0 으로 본다 — 없는 환차를 지어내지 않는다.
type FxView = { value: number | null; pnl: number | null; ret: number | null };

function fxView(
  h: PortfolioHolding,
  on: boolean,
  now: number | null,
  entry: number | null,
): FxView | null {
  if (h.currency === "KRW" || now == null) return null;
  const vl = num(h.market_value_local);
  const cl = num(h.purchase_amount_local);
  const pl = num(h.unrealized_pnl_local);
  const re = entry ?? now;
  if (on) {
    const pnl = pl == null || cl == null ? null : pl * now + cl * (now - re);
    return {
      value: vl == null ? null : vl * now,
      pnl,
      ret: pnl == null || cl == null || cl === 0 ? null : pnl / (cl * re),
    };
  }
  return {
    value: vl == null ? null : vl * re,
    pnl: pl == null ? null : pl * re,
    ret: pl == null || cl == null || cl === 0 ? null : pl / cl,
  };
}

const krw = (v: number | null) => (v == null ? null : String(Math.round(v)));

function days(n: number): string {
  if (n >= 365) return `${(n / 365).toFixed(1)}년`;
  return `${n}일`;
}

export default function HoldingsPage() {
  const { accountId, connected, isError } = useAccount();
  const live = useLiveQueryOptions();
  const [eventsOpen, setEventsOpen] = useState(false);
  const [fxOn, setFxOn] = useState(true);

  // ★자동 갱신에 얹는다(자산 현황과 같은 주기). 값이 바뀌면 칸의 숫자가 굴러간다.
  const summary = useQuery({
    queryKey: ["portfolioSummary", accountId],
    queryFn: () => getPortfolioSummary(accountId),
    staleTime: 3_000,
    ...live,
  });
  const holdings = useQuery({
    queryKey: ["portfolioHoldings", accountId],
    queryFn: () => getPortfolioHoldings(accountId),
    staleTime: 3_000,
    ...live,
  });

  const inclusion = useQuery({
    queryKey: ["inclusion", accountId],
    queryFn: () => getInclusion(accountId),
    ...live,
  });

  const fxRate = useQuery({
    queryKey: ["fxRate", accountId],
    queryFn: () => getFxRate(accountId),
    staleTime: 30_000,
    ...live,
  });
  // 종목별 추정 매입 환율만 쓴다. 하루에 한 번 바뀔까 말까 한 값이라 폴링하지 않는다.
  const fxExposure = useQuery({
    queryKey: ["fxExposure", accountId],
    queryFn: () => getFxExposure(accountId),
    staleTime: 10 * 60_000,
  });

  const items = holdings.data?.items ?? [];

  const nowRate = num(fxRate.data?.rate);
  const entryByTicker = useMemo(() => {
    const map = new Map<string, number>();
    for (const p of fxExposure.data?.positions ?? []) {
      if (p.estimated_entry_rate != null) map.set(p.ticker, Number(p.estimated_entry_rate));
    }
    return map;
  }, [fxExposure.data]);
  // 원화 종목(null)은 환과 무관하므로 증권사 값을 그대로 쓴다.
  const fx = (h: PortfolioHolding) =>
    fxView(h, fxOn, nowRate, entryByTicker.get(h.ticker) ?? null);
  const valueOf = (h: PortfolioHolding) => {
    const v = fx(h);
    return v ? v.value : num(h.market_value_krw);
  };
  const pnlOf = (h: PortfolioHolding) => {
    const v = fx(h);
    return v ? v.pnl : num(h.unrealized_pnl_krw);
  };
  const retOf = (h: PortfolioHolding) => {
    const v = fx(h);
    return v ? v.ret : num(h.unrealized_return);
  };

  // 티커 → 편입 이력. 청산(CLOSED) 종목은 보유 표에 행이 없으니 뺀다.
  const incByTicker = useMemo(() => {
    const map = new Map<string, InclusionHolding>();
    for (const h of inclusion.data?.holdings ?? []) {
      if (h.status !== "CLOSED") map.set(h.ticker, h);
    }
    return map;
  }, [inclusion.data]);
  const inc = (h: PortfolioHolding) => incByTicker.get(h.ticker);

  // ⚠️같은 값을 17줄 반복하는 칸은 폭만 먹는다(실측: 시장 전부 "US", 환율 전부
  //   1,375.50 → 표가 1024px 에서 잘렸다). **값이 하나뿐일 때만** 접고 제목줄에
  //   한 번 적는다. 달라지면 칸이 다시 나온다 — 국내 종목을 사면 시장이 갈린다.
  const uniq = (values: (string | null | undefined)[]) => {
    const set = new Set(values.filter((v) => v != null && v !== ""));
    return set.size === 1 ? ([...set][0] as string) : null;
  };
  const oneRate =
    items.length > 1
      ? uniq(items.map((h) => (h.currency === "KRW" ? null : h.exchange_rate)))
      : null;
  const foldRate = oneRate != null && items.every((h) => h.currency !== "KRW");

  const columns: Column[] = [
    { label: "종목", align: "left", value: (h) => h.name ?? h.ticker },
    { label: "상장거래소", align: "left", value: exchangeOf },
    { label: "수량", align: "right", value: (h) => num(h.quantity) },
    { label: "평단", align: "right", value: (h) => num(h.average_purchase_price) },
    { label: "현재가", align: "right", value: (h) => num(h.current_price) },
    { label: "매입금액", align: "right", value: (h) => num(h.purchase_amount_local) },
    { label: "평가금액", align: "right", value: valueOf },
    { label: "평가손익", align: "right", value: pnlOf },
    { label: "수익률", align: "right", value: retOf },
    { label: "편입비", align: "right", value: (h) => num(inc(h)?.weight) },
    { label: "최초 편입", align: "right", value: (h) => inc(h)?.first_entry ?? null },
    { label: "보유기간", align: "right", value: (h) => inc(h)?.holding_days ?? null },
    {
      label: "매수/매도",
      align: "right",
      value: (h) => {
        const i = inc(h);
        return i ? i.buy_count + i.sell_count : null;
      },
    },
    ...(foldRate
      ? []
      : [{ label: "환율", align: "right" as const, value: (h: PortfolioHolding) => num(h.exchange_rate) }]),
  ];

  // 정렬은 **라벨**로 기억한다. 환율 칸이 접혔다 펴지면 번호가 밀린다.
  const [sort, setSort] = useState<{ label: string; dir: "asc" | "desc" }>({
    label: "평가금액",
    dir: "desc",
  });
  const sortIndex = Math.max(
    columns.findIndex((c) => c.label === sort.label),
    0,
  );
  const onSort = (i: number) => {
    const col = columns[i];
    setSort((prev) =>
      prev.label === col.label
        ? { label: col.label, dir: prev.dir === "asc" ? "desc" : "asc" }
        : // 처음 누르면 숫자는 큰 것부터, 글자는 가나다순부터.
          { label: col.label, dir: col.align === "right" ? "desc" : "asc" },
    );
  };

  const rows = useMemo(() => {
    const col = columns[sortIndex];
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...items].sort((a, b) => {
      const va = col.value(a);
      const vb = col.value(b);
      if (va == null || vb == null) return va == null ? (vb == null ? 0 : 1) : -1;
      const cmp =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb), "ko");
      return cmp * sign;
    });
    // columns 는 렌더마다 새로 만들지만 정렬 기준은 sortIndex·dir 로 결정된다.
  }, [items, sortIndex, sort.dir, incByTicker, fxOn, nowRate, entryByTicker]);

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
                ? "API 서버에 연결하지 못했습니다"
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
            hint="평가손익에서 미리 뺀 몫"
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
            foldRate ? `증권사 환율 ${formatPriceString(oneRate, "USD")}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          className="min-h-0 flex-1"
          action={
            <button
              type="button"
              onClick={() => setEventsOpen(true)}
              className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
            >
              편입·청산 이력
            </button>
          }
        >
          <div className="flex h-full min-h-0 flex-col">
          {/* 환노출 토글 — 표 바로 위. 평가금액·평가손익·수익률 세 칸만 바뀐다. */}
          <div className="mb-2 flex shrink-0 flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold text-ink">환노출</span>
            <div className="inline-flex overflow-hidden rounded-lg border border-hairline">
              {[
                { on: true, label: "ON · 환 반영" },
                { on: false, label: "OFF · 환 미반영" },
              ].map((o) => (
                <button
                  key={o.label}
                  type="button"
                  onClick={() => setFxOn(o.on)}
                  aria-pressed={fxOn === o.on}
                  className={cn(
                    "px-2.5 py-1 text-[11px] font-bold transition-colors",
                    fxOn === o.on
                      ? "bg-ge-point text-white"
                      : "bg-white text-ink-muted hover:bg-canvas-soft",
                  )}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <span className="text-[11px] font-semibold text-ink-muted">
              {fxOn ? (
                nowRate != null ? (
                  <>
                    현재 환율 <b className="text-ink">{formatPriceString(fxRate.data?.rate ?? null, "USD")}</b>
                    {" · "}
                    {fxRate.data?.source === "naver"
                      ? `네이버(${fxRate.data.bank ?? "은행"} ${fxRate.data.round ?? ""}회차 ${fxRate.data.traded_at?.slice(11, 16) ?? ""})${fxRate.data.stale ? " · 재요청 실패, 마지막 값" : ""}`
                      : "증권사 환율(네이버 수신 실패)"}
                    {" · 원금 환차까지 손익에 넣음"}
                  </>
                ) : (
                  "환율을 불러오는 중…"
                )
              ) : (
                <>
                  매입 환율 고정(매수일 종가 환율로 <b className="text-ink">추정</b>) · 주가 손익만
                  {fxExposure.data?.estimated_entry_rate
                    ? ` · 평균 ${formatPriceString(fxExposure.data.estimated_entry_rate, "USD")}`
                    : ""}
                </>
              )}
            </span>
          </div>
          <div className="mb-2 flex shrink-0 items-center">
            <span className="text-[11px] font-semibold text-ink-faint">
              <b className="text-ink-muted">편입비는 원가(USD) 기준</b>
              {inclusion.data?.first_trade_date
                ? ` · 매매 이력 ${inclusion.data.first_trade_date}부터`
                : ""}
            </span>
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {rows.length}종목
            </span>
          </div>

          {/* 남는 높이를 표가 갖고, 넘치면 **여기서만** 스크롤한다. */}
          <div className="min-h-0 flex-1 overflow-y-auto">
          <DataTable
            columns={columns.map((c) => c.label)}
            align={columns.map((c) => c.align)}
            sort={{ column: sortIndex, dir: sort.dir, onSort }}
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
                <Cell left tone="muted">
                  {exchangeOf(h)}
                </Cell>
                <Cell>{formatQuantityString(h.quantity)}</Cell>
                <Cell>{formatPriceString(h.average_purchase_price, h.currency)}</Cell>
                {/* 갱신되는 칸 — 상단 요약 칸과 같이 옛 숫자는 내려가고 새 숫자가
                    위에서 내려온다. */}
                <Cell>
                  <Rolling value={formatPriceString(h.current_price, h.currency)} />
                </Cell>
                <Cell tone="muted">
                  {formatPriceString(h.purchase_amount_local, h.currency)}
                </Cell>
                <Cell strong>
                  <Rolling value={formatKrwString(krw(valueOf(h)))} />
                </Cell>
                <Cell tone={toneOf(krw(pnlOf(h)))}>
                  <Rolling value={formatKrwSigned(krw(pnlOf(h)))} />
                </Cell>
                <Cell tone={toneOf(retOf(h) == null ? null : String(retOf(h)))}>
                  <Rolling
                    value={formatPercentString(retOf(h) == null ? null : String(retOf(h)))}
                  />
                </Cell>
                <IncCells item={inc(h)} />
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
        open={eventsOpen}
        onClose={() => setEventsOpen(false)}
        title="편입 · 청산 전체 이력"
        subtitle={
          inclusion.data?.first_trade_date
            ? `${inclusion.data.first_trade_date} ~ ${inclusion.data.last_trade_date} · 원가(USD) 기준`
            : undefined
        }
      >
        <EventTable events={inclusion.data?.events ?? []} />
      </Modal>
    </>
  );
}

/** 편입비 화면에서 옮겨 온 네 칸. 이력이 없는 종목은 "—". */
function IncCells({ item }: { item?: InclusionHolding }) {
  if (!item) {
    return (
      <>
        <Cell tone="muted">—</Cell>
        <Cell tone="muted">—</Cell>
        <Cell tone="muted">—</Cell>
        <Cell tone="muted">—</Cell>
      </>
    );
  }
  // ⚠️STALE(매매 이력에 매도가 빠짐)은 편입비 분모에서 빠진다. "제외"로 적는다.
  const stale = item.status === "STALE";
  return (
    <>
      <Cell tone={stale ? "muted" : undefined}>
        {stale ? (
          <span title="매매 이력에 매도가 빠져 편입비 분모에서 뺐습니다">제외</span>
        ) : (
          pct(item.weight)
        )}
      </Cell>
      <Cell tone="muted">{item.first_entry.slice(2)}</Cell>
      <Cell>{days(item.holding_days)}</Cell>
      <Cell tone="muted">
        {item.buy_count}회 / {item.sell_count}회
      </Cell>
    </>
  );
}

function EventTable({ events }: { events: InclusionEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="py-10 text-center text-[12px] font-semibold text-ink-faint">
        이력이 없습니다
      </p>
    );
  }
  return (
    <div className="max-h-[60vh] overflow-y-auto">
      <DataTable
        columns={["날짜", "구분", "종목", "수량", "금액", "편입비 변화", "보유"]}
        align={["left", "left", "left", "right", "right", "right", "right"]}
      >
        {events.map((e, i) => (
          <tr key={`${e.event_date}-${e.ticker}-${i}`} className="border-b border-hairline">
            <Cell left>{e.event_date}</Cell>
            <Cell left>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-bold",
                  KIND_STYLE[e.kind],
                )}
              >
                {KIND_LABEL[e.kind]}
              </span>
            </Cell>
            <Cell left strong>
              {e.ticker}
            </Cell>
            <Cell>{Number(e.quantity).toLocaleString()}</Cell>
            <Cell>{usd(e.amount)}</Cell>
            <Cell>
              {pct(e.weight_before)} → {pct(e.weight_after)}
            </Cell>
            <Cell tone="muted">{e.holdings_after}</Cell>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

/** 표 칸용 굴러가는 숫자 — 12px 본문에 맞춘 줄 높이. */
function Rolling({ value }: { value: string }) {
  return <AnimatedNumber value={value} lineHeight={16} />;
}
