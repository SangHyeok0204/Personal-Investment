"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  Emphasized,
  NotConnectedBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import {
  addJournal,
  getRebalance,
  putRebalanceTargets,
  type PortfolioCharacter,
  type Rebalance,
  type RebalanceLine,
} from "@/lib/api";
import { formatKrwCompactString, formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 리밸런싱 — 목표 비중과 지금 보유의 차이를 **주수**로 바꾼다.
//
// ★알림이 "SOXL 비중 21.32% > 20%" 를 잡아 준다. 여기는 그 다음 질문에 답한다 —
//   **그래서 몇 주를 팔아야 하나.**
//
// ⚠️분모는 **주식 평가액**이다(예수금 제외). 섹터/자산 배분 화면과 같은 분모여야
//   두 화면의 비중이 같은 말을 한다.
//
// ⚠️목표가 없는 보유 종목을 **0% 로 치지 않는다.** 그렇게 하면 "아직 목표를 안
//   적은 종목을 전부 팔아라"가 되는데, 사용자가 시킨 적 없는 말이다.
//
// ⚠️목표합만 보면 **실행할 수 없는 계획**이 나온다. 목표를 적지 않은 보유가
//   자리를 차지하고 있으면 살 돈이 안 나온다(실측: 목표 80% + 목표없음 39.1%
//   = 119.1% → 순매수 638만인데 예수금 133만). 부족액을 위에서 알린다.

//: 서버가 예수금을 종목처럼 한 줄로 넣을 때 쓰는 가짜 티커.
const CASH_TICKER = "__CASH__";

const BANDS = [
  { value: 0, label: "0%p" },
  { value: 0.005, label: "0.5%p" },
  { value: 0.01, label: "1%p" },
  { value: 0.02, label: "2%p" },
  { value: 0.03, label: "3%p" },
];

type Row = { ticker: string; percent: string; memo: string };

function pct(value: string | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}

function pp(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%p`;
}

const ACTION_STYLE: Record<string, string> = {
  BUY: "bg-bid-soft text-bid",
  SELL: "bg-ask-soft text-ask",
  HOLD: "bg-canvas-soft text-ink-faint",
};
const ACTION_LABEL: Record<string, string> = { BUY: "매수", SELL: "매도", HOLD: "유지" };

export default function RebalancePage() {
  const { accountId, connected } = useAccount();
  const qc = useQueryClient();
  const [band, setBand] = useState(0.01);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [logged, setLogged] = useState<Record<string, boolean>>({});

  const plan = useQuery({
    queryKey: ["rebalance", accountId, band],
    queryFn: () => getRebalance(accountId, band),
    staleTime: 30_000,
  });
  const data = plan.data;

  // ⚠️"한 번만 끌어온다"로 짰더니 **저장 후 편집기가 옛 목표를 들고 있었다.**
  //   저장 → rows=null → 아직 갱신 안 된 data 로 다시 채워짐 → 새 데이터가
  //   와도 rows!=null 이라 무시. 계획에는 BE 가 있는데 편집기엔 없고, 그
  //   상태로 또 저장하면 BE 가 지워진다(실측으로 재현).
  //   → 서버 목표가 **실제로 바뀌었을 때만** 다시 채운다. 지문이 같으면
  //     사용자가 입력 중인 값을 건드리지 않는다.
  const serverSig = useMemo(
    () =>
      (data?.lines ?? [])
        .map((l) => `${l.ticker}:${l.target_weight}:${l.memo ?? ""}`)
        .join("|"),
    [data],
  );
  const [syncedSig, setSyncedSig] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    if (syncedSig === serverSig) return;
    setRows(
      data.lines.map((l) => ({
        ticker: l.ticker,
        percent: String(Number((Number(l.target_weight) * 100).toFixed(4))),
        memo: l.memo ?? "",
      })),
    );
    setSyncedSig(serverSig);
  }, [data, serverSig, syncedSig]);

  const save = useMutation({
    mutationFn: (list: Row[]) =>
      putRebalanceTargets(
        list
          .filter((r) => r.ticker.trim())
          .map((r) => ({
            ticker: r.ticker.trim().toUpperCase(),
            target_weight: String((Number(r.percent) || 0) / 100),
            memo: r.memo.trim() || null,
          })),
        accountId,
        band,
      ),
    onSuccess: (fresh) => {
      setSaveError(null);
      // 저장 응답이 곧 최신 계획이다 — 이걸로 바로 맞춘다.
      setRows(
        fresh.lines.map((l) => ({
          ticker: l.ticker,
          percent: String(Number((Number(l.target_weight) * 100).toFixed(4))),
          memo: l.memo ?? "",
        })),
      );
      setSyncedSig(
        fresh.lines
          .map((l) => `${l.ticker}:${l.target_weight}:${l.memo ?? ""}`)
          .join("|"),
      );
      qc.invalidateQueries({ queryKey: ["rebalance"] });
    },
    onError: (e: unknown) =>
      setSaveError(e instanceof Error ? e.message : "저장하지 못했습니다."),
  });

  // ★계획을 세웠으면 **왜 이 비중인가**가 기록으로 남아야 나중에 복기가 된다.
  //   ⚠️제목 문자열로만 남기면 "계획 11주 중 몇 주가 체결됐나"를 물을 수 없다 —
  //     방향·수량·계획가를 **구조로** 함께 보낸다.
  const log = useMutation({
    mutationFn: (line: RebalanceLine) =>
      addJournal({
        ticker: line.ticker,
        entry_date: new Date().toISOString().slice(0, 10),
        kind: line.action === "SELL" ? "EXIT" : "ENTRY",
        title:
          `리밸런싱 ${line.action === "SELL" ? "매도" : "매수"} 계획 ` +
          `${line.ticker} ${Math.abs(line.delta_shares ?? 0)}주`,
        body:
          `${pct(line.current_weight)} → ${pct(line.target_weight)} ` +
          `(${pp(line.drift)})` + (line.memo ? `\n${line.memo}` : ""),
        planned_side: line.action === "SELL" ? "SELL" : "BUY",
        planned_quantity: String(Math.abs(line.delta_shares ?? 0)),
        planned_price_krw: line.price_krw,
      }),
    onSuccess: (_r, line) => setLogged((p) => ({ ...p, [line.ticker]: true })),
  });

  const draftSum = useMemo(
    () => (rows ?? []).reduce((s, r) => s + (Number(r.percent) || 0), 0),
    [rows],
  );
  const trades = (data?.lines ?? []).filter((l) => l.delta_shares);
  const worst = useMemo(() => {
    const withDrift = (data?.lines ?? []).filter((l) => l.drift != null);
    if (withDrift.length === 0) return null;
    return withDrift.reduce((a, b) =>
      Math.abs(Number(b.drift)) > Math.abs(Number(a.drift)) ? b : a,
    );
  }, [data]);
  const shortfall = data?.shortfall_krw ? Number(data.shortfall_krw) : 0;
  const overAllocated =
    data != null &&
    Number(data.target_sum) + Number(data.untargeted_weight) > 1.0001;

  return (
    <>
      <Topbar title="리밸런싱" subtitle="어긋난 만큼 몇 주를 사고팔아야 하나" />
      <PageContainer fit>
        {!connected && !plan.isLoading && <NotConnectedBanner what="보유 종목" />}

        {/* ⚠️실행할 수 없는 계획을 조용히 내놓지 않는다. */}
        {overAllocated && (
          <div className="flex shrink-0 items-center gap-2 rounded-xl border border-ask/25 bg-ask-soft px-3 py-2">
            <span className="rounded bg-ask/15 px-1.5 py-0.5 text-[10px] font-extrabold text-ask">
              실행 불가
            </span>
            <span className="text-[11px] font-semibold leading-snug text-ink-secondary">
              목표 {pct(data!.target_sum, 0)} + 목표 없는 보유{" "}
              {pct(data!.untargeted_weight, 1)} ={" "}
              <strong>
                {(
                  (Number(data!.target_sum) + Number(data!.untargeted_weight)) *
                  100
                ).toFixed(1)}
                %
              </strong>{" "}
              — 자리가 모자랍니다. 아래 &apos;목표 없음&apos;에서 팔 것을 먼저
              정하거나 목표를 낮추세요
              {shortfall > 0 && (
                <>
                  {" "}
                  (지금 계획대로면 <strong>{formatKrwString(data!.shortfall_krw)}</strong>{" "}
                  부족)
                </>
              )}
              .
            </span>
          </div>
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="가장 어긋난 종목"
            value={worst ? `${worst.ticker} ${pp(worst.drift)}` : null}
            hint={worst ? `${pct(worst.current_weight)} → ${pct(worst.target_weight)}` : "목표 대비"}
            accent="auto"
            loading={plan.isLoading}
          />
          <StatTile
            label="해야 할 거래"
            value={data ? `${data.trade_count}건` : null}
            hint={
              data
                ? `매수 ${formatKrwCompactString(data.buy_krw)} · 매도 ${formatKrwCompactString(data.sell_krw)}`
                : "밴드 밖만"
            }
            loading={plan.isLoading}
          />
          <StatTile
            label="예상 거래비용"
            value={data ? formatKrwString(data.est_cost_krw) : null}
            hint={data ? `실측 비용률 ${pct(data.cost_rate, 3)}` : "수수료 + 세금"}
            accent="down"
            actionHint="눌러서 기준 보기"
            onClick={() => setNotesOpen(true)}
            loading={plan.isLoading}
          />
          <StatTile
            label="필요 현금"
            value={data ? formatKrwSigned(data.net_buy_krw) : null}
            hint={
              data?.cash_krw
                ? `예수금 ${formatKrwString(data.cash_krw)}`
                : "매수 − 매도"
            }
            accent={shortfall > 0 ? "down" : "auto"}
            loading={plan.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)] xl:auto-rows-auto",
          )}
        >
          <StubCard
            title="계획"
            subtitle={`${trades.length}건 거래 · 밴드 밖만`}
            scrollBody
            action={
              <div className="flex shrink-0 items-center gap-1">
                <span className="mr-0.5 text-[10px] font-semibold text-white/60">
                  밴드
                </span>
                {BANDS.map((b) => (
                  <button
                    key={b.value}
                    type="button"
                    onClick={() => setBand(b.value)}
                    className={cn(
                      "rounded-full px-2 py-1 text-[10px] font-bold transition-colors",
                      band === b.value
                        ? "bg-white text-ge-navy"
                        : "bg-white/15 text-white hover:bg-white/25",
                    )}
                  >
                    {b.label}
                  </button>
                ))}
              </div>
            }
          >
            <DataTable
              columns={["종목", "현재 → 목표", "차이", "주수", "금액", ""]}
              align={["left", "left", "right", "right", "right", "right"]}
              empty={
                plan.isLoading
                  ? "불러오는 중…"
                  : connected
                    ? "오른쪽에서 목표 비중을 적어 보세요"
                    : "계좌를 연동하면 계획이 표시됩니다"
              }
            >
              {(data?.lines ?? []).map((l) => (
                <PlanRow
                  key={l.ticker}
                  line={l}
                  logged={!!logged[l.ticker]}
                  busy={log.isPending}
                  onLog={() => log.mutate(l)}
                />
              ))}
            </DataTable>

            {(data?.untargeted.length ?? 0) > 0 && (
              <div className="mt-3 rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
                <p className="mb-1 text-[11px] font-bold text-ge-navy">
                  목표 없음 ({data!.untargeted.length}종목 ·{" "}
                  {pct(data!.untargeted_weight, 1)})
                </p>
                {/* ⚠️0% 로 치지 않는다 — "전부 팔아라"가 되기 때문이다. */}
                <p className="mb-1.5 text-[11px] leading-snug text-ink-muted">
                  목표를 적지 않았습니다. <strong>0% 로 치지 않습니다</strong> —
                  팔라는 말이 아닙니다.
                </p>
                <div className="flex flex-wrap gap-1">
                  {/* ⚠️예수금은 내부 티커(__CASH__)를 쓴다. 그대로 찍으면 화면에
                      코드가 샌다. 그리고 현금에는 목표를 걸 수 없다 — 담아도
                      "몇 주 사라"가 나오지 않는다. */}
                  {data!.untargeted.map((u) =>
                    u.ticker === CASH_TICKER ? (
                      <span
                        key={u.ticker}
                        className="rounded bg-canvas px-1.5 py-0.5 text-[10px] font-bold text-ink-faint"
                      >
                        {u.name ?? "예수금"} {pct(u.current_weight, 1)}
                      </span>
                    ) : (
                    <button
                      key={u.ticker}
                      type="button"
                      title={`${u.name ?? u.ticker} · ${pct(u.current_weight)} — 눌러서 목표에 추가`}
                      onClick={() =>
                        setRows((prev) =>
                          prev?.some((r) => r.ticker === u.ticker)
                            ? prev
                            : [
                                ...(prev ?? []),
                                {
                                  ticker: u.ticker,
                                  percent: String(
                                    Number(
                                      (Number(u.current_weight ?? 0) * 100).toFixed(2),
                                    ),
                                  ),
                                  memo: "",
                                },
                              ],
                        )
                      }
                      className="rounded bg-canvas px-1.5 py-0.5 text-[10px] font-bold text-ink-faint transition-colors hover:bg-ge-navy hover:text-white"
                    >
                      {u.ticker} {pct(u.current_weight, 1)}
                    </button>
                    ),
                  )}
                </div>
              </div>
            )}
          </StubCard>

          <div className="flex min-h-0 flex-col gap-3">
          {/* ★목표를 정하기 전에 **지금 어떤 모양인지** 본다. 비중만 보면
              SOXL 이 20% 지만 3배 상품이라 하루 움직임으로는 60% 다. */}
          {data?.character && (
            <StubCard
              title="지금 이 포트폴리오"
              subtitle="목표를 정하기 전에"
              className="shrink-0"
            >
              <CharacterPanel c={data.character} />
            </StubCard>
          )}

          <StubCard
            title="목표 비중"
            subtitle={`합계 ${draftSum.toFixed(2)}%`}
            className="min-h-0 flex-1"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNotesOpen(true)}
                className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                읽는 법
              </button>
            }
          >
            <div className="space-y-2">
              {/* 합계가 100%가 아니면 말한다 — 조용히 정규화하지 않는다. */}
              <p
                className={cn(
                  "rounded-lg px-2.5 py-1.5 text-[11px] font-semibold",
                  Math.abs(draftSum - 100) < 0.005
                    ? "bg-bid-soft text-bid"
                    : "bg-canvas-soft text-ink-secondary",
                )}
              >
                {Math.abs(draftSum - 100) < 0.005
                  ? "합계 100% — 목표가 모두 채워졌습니다."
                  : `합계 ${draftSum.toFixed(2)}% · 100%까지 ${(100 - draftSum).toFixed(2)}%p 남음 (모자라도 저장됩니다)`}
              </p>

              {(rows ?? []).map((r, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <input
                    value={r.ticker}
                    onChange={(e) =>
                      setRows((p) =>
                        (p ?? []).map((x, j) =>
                          j === i ? { ...x, ticker: e.target.value } : x,
                        ),
                      )
                    }
                    placeholder="NVDA"
                    className="w-[72px] shrink-0 rounded-lg border border-hairline bg-canvas px-2 py-1 text-[12px] font-bold uppercase text-ink placeholder:font-normal placeholder:normal-case placeholder:text-ink-faint"
                  />
                  <input
                    value={r.percent}
                    onChange={(e) =>
                      setRows((p) =>
                        (p ?? []).map((x, j) =>
                          j === i ? { ...x, percent: e.target.value } : x,
                        ),
                      )
                    }
                    inputMode="decimal"
                    className="w-[62px] shrink-0 rounded-lg border border-hairline bg-canvas px-2 py-1 text-right text-[12px] font-bold tabular-nums text-ink"
                  />
                  <span className="shrink-0 text-[11px] font-bold text-ink-faint">%</span>
                  <input
                    value={r.memo}
                    onChange={(e) =>
                      setRows((p) =>
                        (p ?? []).map((x, j) =>
                          j === i ? { ...x, memo: e.target.value } : x,
                        ),
                      )
                    }
                    placeholder="왜 이 비중인가"
                    className="min-w-0 flex-1 rounded-lg border border-hairline bg-canvas px-2 py-1 text-[11px] text-ink placeholder:text-ink-faint"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setRows((p) => (p ?? []).filter((_, j) => j !== i))
                    }
                    className="shrink-0 rounded px-1.5 py-1 text-[10px] font-bold text-ask transition-colors hover:bg-ask-soft"
                  >
                    삭제
                  </button>
                </div>
              ))}

              {/* 빈 상태에서 맨손으로 시작하기 어렵다 — 지금 비중을 그대로
                  옮겨 두면 거기서부터 고치면 된다. ⚠️목표를 우리가 **정해 주지
                  않는다.** 지금 값을 복사할 뿐이고, 그 자체로는 아무것도 바꾸지
                  않는다(전부 0%p 차이 → 거래 0건). */}
              {(rows?.length ?? 0) === 0 && (data?.untargeted.length ?? 0) > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    setRows(
                      (data?.untargeted ?? []).map((u) => ({
                        ticker: u.ticker,
                        percent: String(
                          Number((Number(u.current_weight ?? 0) * 100).toFixed(2)),
                        ),
                        memo: "",
                      })),
                    )
                  }
                  className="w-full rounded-lg border border-ge-point/40 bg-ge-blue-bg px-3 py-2 text-[11px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg/70"
                >
                  지금 보유 비중 그대로 채우기 ({data?.untargeted.length}종목)
                </button>
              )}

              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() =>
                    setRows((p) => [...(p ?? []), { ticker: "", percent: "", memo: "" }])
                  }
                  className="flex-1 rounded-lg border border-dashed border-hairline px-3 py-1.5 text-[11px] font-bold text-ink-muted transition-colors hover:bg-canvas-soft"
                >
                  + 종목 추가
                </button>
                <button
                  type="button"
                  disabled={save.isPending || rows == null}
                  onClick={() => save.mutate(rows ?? [])}
                  className="flex-1 rounded-lg bg-ge-navy px-3 py-1.5 text-[11px] font-bold text-white transition-colors hover:bg-ge-navy/90 disabled:opacity-50"
                >
                  {save.isPending ? "저장 중…" : "목표 저장"}
                </button>
              </div>

              {saveError && (
                <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold text-ask">
                  {saveError}
                </p>
              )}
            </div>
          </StubCard>
          </div>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면 읽는 법"
        subtitle="무엇을 계산하고 무엇을 하지 않나"
      >
        <ul className="space-y-2">
          {(data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                <Emphasized text={text} />
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

/**
 * 지금 포트폴리오의 성격.
 *
 * ⚠️**"3배 오른다"고 말하지 않는다.** 레버리지 배수는 하루 수익률에만
 *   적용되고, 여러 날에 걸치면 변동성 끌림 때문에 배수 × 기간수익률이 되지
 *   않는다. 그 사실을 숫자 바로 옆에 적는다.
 */
function CharacterPanel({ c }: { c: PortfolioCharacter }) {
  const disputed = c.leverage.filter((l) => l.disputed);
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-3 gap-2">
        <Metric
          label="실효 노출"
          value={pct(c.effective_exposure, 0)}
          hint="하루 기준"
          strong
        />
        <Metric
          label="레버리지 비중"
          value={pct(c.leveraged_weight, 1)}
          hint={`${c.leverage.length}종목`}
        />
        <Metric
          label="유효 종목 수"
          value={c.effective_count ?? "—"}
          hint={`상위3 ${pct(c.top3_weight, 0)}`}
        />
      </div>

      {c.leverage.length > 0 && (
        <div className="space-y-1">
          {c.leverage.map((l) => (
            <div key={l.ticker} className="flex items-baseline justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="shrink-0 rounded bg-ask-soft px-1 py-0.5 text-[9px] font-extrabold text-ask">
                  {Number(l.multiplier)}배
                </span>
                <span className="truncate text-[11px] font-bold text-ink">
                  {l.ticker}
                </span>
                {/* ⚠️두 출처가 어긋나면 조용히 한쪽을 고르지 않는다. */}
                {l.disputed && (
                  <span
                    title={l.source}
                    className="shrink-0 cursor-help rounded bg-ge-point/12 px-1 py-0.5 text-[9px] font-extrabold text-ge-point"
                  >
                    출처 불일치
                  </span>
                )}
              </span>
              <span className="shrink-0 text-[11px] font-semibold tabular-nums text-ink-secondary">
                {pct(l.weight, 1)} → <strong className="text-ask">{pct(l.effective_weight, 1)}</strong>
              </span>
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] leading-snug text-ink-muted">
        {c.leverage_note.split(/\*\*(.+?)\*\*/g).map((part, i) =>
          i % 2 === 1 ? (
            <strong key={i} className="text-ink">
              {part}
            </strong>
          ) : (
            part
          ),
        )}
      </p>

      {disputed.length > 0 && (
        <p className="rounded-lg bg-ge-point/8 px-2.5 py-2 text-[11px] leading-snug text-ge-point">
          {disputed.map((d) => d.ticker).join(", ")} 은(는) 내부 표와 증권사
          종목명의 배수가 다릅니다 — <strong>증권사 이름을 따랐습니다.</strong>
        </p>
      )}

      <p className="text-[11px] leading-snug text-ink-muted">
        현금 {pct(c.cash_weight, 1)} · 최대 종목{" "}
        <strong className="text-ink">{c.top1_ticker ?? "—"}</strong>{" "}
        {c.top1_weight ? pct(c.top1_weight, 1) : "—"}
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  strong,
}: {
  label: string;
  value: string;
  hint?: string;
  strong?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-canvas-soft px-2 py-1.5">
      <p className="truncate text-[10px] font-semibold text-ink-faint">{label}</p>
      <p
        className={cn(
          "truncate tabular-nums",
          strong
            ? "text-[15px] font-extrabold text-ask"
            : "text-[13px] font-extrabold text-ge-navy",
        )}
      >
        {value}
      </p>
      {hint && <p className="truncate text-[9px] text-ink-faint">{hint}</p>}
    </div>
  );
}

function PlanRow({
  line,
  logged,
  busy,
  onLog,
}: {
  line: RebalanceLine;
  logged: boolean;
  busy: boolean;
  onLog: () => void;
}) {
  return (
    <tr className={cn("border-b border-hairline", line.within_band && "opacity-60")}>
      <Cell left strong>
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-extrabold",
              ACTION_STYLE[line.action],
            )}
          >
            {ACTION_LABEL[line.action]}
          </span>
          <span className="max-w-[110px] truncate">{line.name ?? line.ticker}</span>
          <span className="shrink-0 text-[10px] font-bold text-ink-faint">
            {line.ticker}
          </span>
        </span>
      </Cell>
      <Cell left tone="muted">
        <span className="text-[11px] tabular-nums">
          {pct(line.current_weight)} → <strong className="text-ink">{pct(line.target_weight)}</strong>
        </span>
      </Cell>
      <Cell
        tone={
          line.within_band
            ? "muted"
            : line.drift == null
              ? "muted"
              : Number(line.drift) > 0
                ? "up"
                : "down"
        }
      >
        {pp(line.drift)}
      </Cell>
      <Cell strong tone={line.action === "BUY" ? "up" : line.action === "SELL" ? "down" : "muted"}>
        {/* ⚠️0 이 나오는 이유가 둘이다 — 밴드 안이라 안 건드리는 것과, 1주
            값보다 차이가 작아 못 사는 것. 같은 "0"으로 적으면 왜 안 하는지
            알 수 없다. ⚠️null 은 또 다른 상태다(가격을 몰라 계산 못 함). */}
        {line.delta_shares == null
          ? "—"
          : line.delta_shares === 0
            ? line.within_band
              ? "밴드 안"
              : "1주 미만"
            : `${line.delta_shares > 0 ? "+" : ""}${line.delta_shares}주`}
      </Cell>
      <Cell tone="muted">
        <span className="text-[11px]">
          {line.delta_shares && line.price_krw
            ? formatKrwSigned(
                String(Math.round(Number(line.price_krw) * line.delta_shares)),
              )
            : line.delta_value_krw
              ? `잔여 ${formatKrwSigned(line.delta_value_krw)}`
              : "—"}
        </span>
      </Cell>
      <Cell>
        {/* 거래할 게 있을 때만 남길 수 있다 — 유지에 일지를 남길 이유가 없다. */}
        {line.delta_shares ? (
          <button
            type="button"
            onClick={onLog}
            disabled={busy || logged}
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
              logged
                ? "text-ink-faint"
                : "text-ge-point hover:bg-ge-blue-bg disabled:opacity-40",
            )}
          >
            {logged ? "기록됨" : "일지"}
          </button>
        ) : null}
      </Cell>
    </tr>
  );
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */
