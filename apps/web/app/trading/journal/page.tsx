"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import {
  addJournal,
  getJournal,
  getUntrackedTickers,
  removeJournal,
  type JournalEntry,
  type JournalKind,
  type PlanOutcome,
} from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 매매일지.
//
// ★일반 메모장과 다른 점은 **결과가 붙는다**는 것이다. "왜 샀는지" 옆에
//   "그래서 어떻게 됐는지"가 없으면 복기가 안 된다. 서버가 메모마다 그 날
//   이후 7일 안의 실제 체결과 현재 평가손익/실현손익을 찾아 보내 준다.
//   ⚠️창이 **비대칭**이다 — 체결 원장의 날짜가 체결일이 아니라 결제일(T+2)이다.
//
// ★"안 적은 종목"을 따로 띄운다. 비어 있는 자리를 보여주지 않으면 일지는
//   결국 안 쓰게 된다 — 이 화면에서 가장 중요한 칸일 수 있다.

const KIND_LABEL: Record<JournalKind, string> = {
  ENTRY: "진입 근거",
  EXIT: "청산 근거",
  REVIEW: "복기",
  IDEA: "아이디어",
};

const KIND_STYLE: Record<JournalKind, string> = {
  ENTRY: "bg-ge-blue-bg text-ge-point",
  EXIT: "bg-hairline text-ink-secondary",
  REVIEW: "bg-amber-100 text-amber-900",
  IDEA: "bg-canvas-soft text-ink-muted",
};

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** 그 메모가 어떻게 끝났는지 한 줄로. 없으면 null — 0 으로 채우지 않는다. */
function outcome(e: JournalEntry): { text: string; tone: "up" | "down" } | null {
  const value = e.held ? e.unrealized_pnl_krw : e.realized_pnl_krw;
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return {
    text: `${e.held ? "평가" : "실현"} ${formatKrwSigned(value)}`,
    tone: n >= 0 ? "up" : "down",
  };
}

export default function JournalPage() {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<JournalEntry | null>(null);
  const [composing, setComposing] = useState<string | null>(null);
  const [filter, setFilter] = useState<JournalKind | null>(null);

  const journal = useQuery({ queryKey: ["journal"], queryFn: () => getJournal() });
  const untracked = useQuery({
    queryKey: ["journalUntracked"],
    queryFn: getUntrackedTickers,
  });

  // 서버가 변경 후 목록 전체를 돌려준다 — 그대로 캐시에 넣으면 재조회가 없다.
  const settle = (data: unknown) => {
    queryClient.setQueryData(["journal"], data);
    void queryClient.invalidateQueries({ queryKey: ["journalUntracked"] });
  };

  const create = useMutation({
    mutationFn: addJournal,
    onSuccess: (data) => {
      settle(data);
      setComposing(null);
    },
  });
  const drop = useMutation({
    mutationFn: removeJournal,
    onSuccess: (data) => {
      settle(data);
      setPicked(null);
    },
  });

  const all = journal.data?.items ?? [];
  const items = useMemo(
    () => (filter ? all.filter((e) => e.kind === filter) : all),
    [all, filter],
  );

  // 확신도를 적어 둔 메모 중, 결과가 확인된 것만으로 "확신이 맞았나"를 본다.
  const convictionHit = useMemo(() => {
    const scored = all.filter((e) => {
      const o = outcome(e);
      return e.conviction != null && o != null;
    });
    if (scored.length === 0) return null;
    const high = scored.filter((e) => (e.conviction ?? 0) >= 4);
    if (high.length === 0) return null;
    const won = high.filter((e) => outcome(e)!.tone === "up").length;
    return { won, total: high.length };
  }, [all]);

  return (
    <>
      <Topbar title="매매일지" subtitle="진입 근거 · 청산 근거 · 복기" />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="작성한 일지"
            value={journal.data ? `${all.length}` : null}
            hint={
              all.length > 0 ? `최근 ${all[0].entry_date}` : "아직 없습니다"
            }
            loading={journal.isLoading}
          />
          <StatTile
            label="안 적은 보유 종목"
            value={untracked.data ? `${untracked.data.length}` : null}
            hint="근거를 안 남긴 종목"
            accent={untracked.data && untracked.data.length > 0 ? "down" : "neutral"}
            loading={untracked.isLoading}
          />
          <StatTile
            label="복기"
            value={
              journal.data ? `${all.filter((e) => e.kind === "REVIEW").length}` : null
            }
            hint="판 뒤에 돌아본 기록"
            loading={journal.isLoading}
          />
          <StatTile
            label="확신 4↑ 적중"
            value={convictionHit ? `${convictionHit.won}/${convictionHit.total}` : null}
            hint={
              convictionHit
                ? "확신이 높았던 판단의 결과"
                : "확신도를 적은 기록이 쌓이면 표시됩니다"
            }
            loading={journal.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="일지"
            subtitle={`${items.length}건`}
            scrollBody
            action={
              <div className="flex items-center gap-1.5">
                {(["ENTRY", "REVIEW"] as JournalKind[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setFilter(filter === k ? null : k)}
                    aria-pressed={filter === k}
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                      filter === k
                        ? "bg-white/90 text-ge-header"
                        : "text-white/60 hover:bg-white/15 hover:text-white",
                    )}
                  >
                    {KIND_LABEL[k]}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setComposing("")}
                  className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold text-white transition-colors hover:bg-white/30"
                >
                  새 일지
                </button>
              </div>
            }
          >
            {journal.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : items.length === 0 ? (
              <Empty text="일지가 없습니다 — '새 일지'로 시작하세요" />
            ) : (
              <ul className="space-y-1.5">
                {items.map((e) => {
                  const o = outcome(e);
                  return (
                    <li key={e.id}>
                      <button
                        type="button"
                        onClick={() => setPicked(e)}
                        className="w-full rounded-lg border border-hairline px-3 py-2 text-left transition-colors hover:bg-canvas-soft"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold",
                              KIND_STYLE[e.kind],
                            )}
                          >
                            {KIND_LABEL[e.kind]}
                          </span>
                          <span className="shrink-0 text-[11px] tabular-nums text-ink-muted">
                            {e.entry_date}
                          </span>
                          {e.ticker && (
                            <span className="shrink-0 text-[11px] font-bold text-ge-point">
                              {e.ticker}
                            </span>
                          )}
                          <span className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink">
                            {e.title}
                          </span>
                          {o && (
                            <span
                              className={cn(
                                "shrink-0 text-[11px] font-bold tabular-nums",
                                o.tone === "up" ? "text-bid" : "text-ask",
                              )}
                            >
                              {o.text}
                            </span>
                          )}
                        </div>
                        {e.body && (
                          <p className="mt-1 truncate text-[11px] leading-snug text-ink-muted">
                            {e.body}
                          </p>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </StubCard>

          <StubCard
            title="안 적은 보유 종목"
            subtitle={`${untracked.data?.length ?? 0}종목`}
            scrollBody
          >
            {untracked.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (untracked.data?.length ?? 0) === 0 ? (
              <Empty text="보유 종목에 모두 근거를 남겼습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  근거를 안 남긴 종목입니다. 눌러서 바로 적으세요.
                </p>
                <DataTable columns={["종목", ""]} align={["left", "right"]}>
                  {(untracked.data ?? []).map((t) => (
                    <tr key={t} className="border-b border-hairline">
                      <Cell left strong>
                        {t}
                      </Cell>
                      <Cell>
                        <button
                          type="button"
                          onClick={() => setComposing(t)}
                          className="rounded border border-hairline px-2 py-0.5 text-[10px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg"
                        >
                          적기
                        </button>
                      </Cell>
                    </tr>
                  ))}
                </DataTable>
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={composing != null}
        onClose={() => setComposing(null)}
        title="새 일지"
        subtitle={composing ? `${composing} — 왜 들고 있는지` : "종목은 비워 둘 수 있습니다"}
      >
        <Composer
          ticker={composing ?? ""}
          saving={create.isPending}
          error={create.error instanceof Error ? create.error.message : null}
          onSubmit={(body) => create.mutate(body)}
        />
      </Modal>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.title ?? ""}
        subtitle={
          picked
            ? `${KIND_LABEL[picked.kind]} · ${picked.entry_date}${picked.ticker ? ` · ${picked.ticker}` : ""}`
            : undefined
        }
      >
        {picked && (
          <EntryDetail
            entry={picked}
            removing={drop.isPending}
            onRemove={() => drop.mutate(picked.id)}
          />
        )}
      </Modal>
    </>
  );
}

function Composer({
  ticker: initialTicker,
  saving,
  error,
  onSubmit,
}: {
  ticker: string;
  saving: boolean;
  error: string | null;
  onSubmit: (body: {
    ticker: string | null;
    entry_date: string;
    kind: JournalKind;
    title: string;
    body: string | null;
    conviction: number | null;
  }) => void;
}) {
  const [ticker, setTicker] = useState(initialTicker);
  const [date, setDate] = useState(today());
  const [kind, setKind] = useState<JournalKind>("ENTRY");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [conviction, setConviction] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-bold text-amber-900">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {(Object.keys(KIND_LABEL) as JournalKind[]).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            aria-pressed={kind === k}
            className={cn(
              "rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-colors",
              kind === k
                ? "border-ge-point bg-ge-blue-bg text-ge-point"
                : "border-hairline text-ink-muted hover:bg-canvas-soft",
            )}
          >
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="종목 (비워도 됩니다)">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="예: SOXL"
            className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] focus:border-ge-point focus:outline-none"
          />
        </Field>
        <Field label="판단한 날">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] tabular-nums focus:border-ge-point focus:outline-none"
          />
        </Field>
      </div>

      <Field label="한 줄 요약">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="예: 반도체 사이클 회복 베팅"
          className="w-full rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] focus:border-ge-point focus:outline-none"
        />
      </Field>

      <Field label="근거 / 복기">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={4}
          placeholder="무엇을 보고 그렇게 판단했는지. 나중에 읽을 사람은 본인입니다."
          className="w-full resize-none rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] leading-relaxed focus:border-ge-point focus:outline-none"
        />
      </Field>

      <Field label="확신도 (선택 — 안 적어도 됩니다)">
        <div className="flex gap-1.5">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setConviction(conviction === n ? null : n)}
              aria-pressed={conviction === n}
              className={cn(
                "h-7 w-7 rounded-lg border text-[12px] font-bold transition-colors",
                conviction === n
                  ? "border-ge-point bg-ge-point text-white"
                  : "border-hairline text-ink-muted hover:bg-canvas-soft",
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </Field>

      <button
        type="button"
        disabled={saving || !title.trim()}
        onClick={() =>
          onSubmit({
            ticker: ticker.trim() === "" ? null : ticker.trim(),
            entry_date: date,
            kind,
            title: title.trim(),
            body: body.trim() === "" ? null : body.trim(),
            conviction,
          })
        }
        className="rounded-lg bg-ge-point px-3.5 py-1.5 text-[12px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {saving ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

function EntryDetail({
  entry: e,
  removing,
  onRemove,
}: {
  entry: JournalEntry;
  removing: boolean;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const o = outcome(e);

  return (
    <div className="space-y-3">
      {e.body && (
        <p className="whitespace-pre-wrap rounded-lg bg-canvas-soft px-3.5 py-3 text-[13px] leading-relaxed text-ink-secondary">
          {e.body}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        <Row label="종목" value={e.asset_name ?? e.ticker ?? "종목 무관"} />
        <Row label="확신도" value={e.conviction == null ? "—" : `${e.conviction} / 5`} />
        <Row label="현재 상태" value={e.held ? "보유 중" : "미보유"} />
        <Row
          label={e.held ? "평가손익" : "실현손익"}
          value={o?.text.replace(/^(평가|실현)\s/, "") ?? "—"}
          tone={o?.tone}
        />
      </dl>

      {/* ★계획을 적어 둔 메모에만 붙는다 — 계획이 실제로 어떻게 됐나. */}
      {e.plan && <PlanOutcomeBlock plan={e.plan} />}

      {e.nearby_trades.length > 0 ? (
        <div>
          <p className="mb-1.5 text-[11px] font-bold text-ink-muted">
            {/* ⚠️"±3일"이라고 적었는데 창이 비대칭이다(결제일 T+2 때문). 화면이
                실제로 찾는 범위를 그대로 적는다. */}
            이 날 이후 7일 안의 실제 체결 (결제일 기준)
          </p>
          <DataTable
            columns={["체결일", "구분", "수량", "금액"]}
            align={["left", "left", "right", "right"]}
          >
            {e.nearby_trades.map((t, i) => (
              <tr key={`${t.trade_date}-${i}`} className="border-b border-hairline">
                <Cell left tone="muted">
                  {t.trade_date}
                </Cell>
                <Cell left>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold",
                      t.side === "BUY" ? "bg-bid-soft text-bid" : "bg-ask-soft text-ask",
                    )}
                  >
                    {t.side === "BUY" ? "매수" : "매도"}
                  </span>
                </Cell>
                <Cell>{Number(t.quantity).toLocaleString()}</Cell>
                <Cell strong>
                  {t.amount_local == null
                    ? "—"
                    : `$${Number(t.amount_local).toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      ) : (
        <p className="text-[11px] leading-relaxed text-ink-muted">
          이 날 이후 7일 안에 체결이 없습니다 — 생각만 하고 실행하지 않았거나, 날짜가
          실제 체결과 떨어져 있습니다.
        </p>
      )}

      <div className="flex items-center">
        {confirming ? (
          <>
            <span className="text-[11px] font-bold text-ink-secondary">
              정말 삭제할까요?
            </span>
            <button
              type="button"
              disabled={removing}
              onClick={onRemove}
              className="ml-2 rounded-lg bg-ask px-3 py-1.5 text-[12px] font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              삭제
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="ml-2 text-[12px] font-bold text-ink-muted hover:text-ink"
            >
              취소
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="ml-auto text-[12px] font-bold text-ink-muted hover:text-ask"
          >
            삭제
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * 계획 대비 결과.
 *
 * ⚠️**안 한 것과 못 한 것을 구분한다.** 계획 8주 중 0주 체결일 때, 주문을 안
 *   낸 것과 주문은 냈는데 안 걸린 것은 완전히 다른 복기다.
 *
 * ⚠️**두 원장이 갈릴 때 한쪽만 보여 주지 않는다.** (근거로 삼았던 SKHY 사례는
 *   원장 불일치가 아니라 동기화 지연 + 좁은 창이었다 — 2026-09-22 정정.)
 *
 * ⚠️슬리피지는 **양수면 손해**다(매수는 비싸게, 매도는 싸게). 환율을 모르면
 *   비우고, 0 으로 두지 않는다 — 0 은 "정확히 계획대로"라는 뜻이 된다.
 */
function PlanOutcomeBlock({ plan }: { plan: PlanOutcome }) {
  const planned = Number(plan.planned_quantity);
  const filled = Number(plan.filled_quantity);
  const orderFilled = Number(plan.order_filled_quantity);
  const rate = plan.fill_rate == null ? null : Number(plan.fill_rate);
  const slip = plan.slippage_rate == null ? null : Number(plan.slippage_rate);

  return (
    <div className="rounded-xl border border-ge-point/25 bg-ge-point/5 px-3.5 py-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-extrabold text-ge-point">계획 대비</span>
        <span className="text-[11px] font-bold text-ink-secondary">
          {plan.planned_side === "SELL" ? "매도" : "매수"} {planned}주
          {plan.planned_price_krw && (
            <span className="ml-1.5 font-semibold text-ink-faint">
              @ {formatKrwString(plan.planned_price_krw)}
            </span>
          )}
        </span>
      </div>

      {/* ⚠️두 원장이 갈리면 숫자를 하나로 합치지 않는다. */}
      {plan.sources_disagree && (
        <p className="mb-2 rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          체결 내역은 {filled}주, 주문 내역은 {orderFilled}주라고 합니다 — 증권사
          두 원장이 다른 말을 합니다. 어느 쪽도 임의로 고르지 않았습니다.
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        <Row
          label="체결 (체결 원장)"
          value={`${filled}주${rate != null ? ` · ${(rate * 100).toFixed(0)}%` : ""}`}
          tone={rate != null && rate >= 0.999 ? "up" : undefined}
        />
        <Row label="체결 (주문 원장)" value={`${orderFilled}주`} />
        <Row
          label="주문"
          value={
            plan.no_order
              ? "주문 없음"
              : `${Number(plan.ordered_quantity)}주`
          }
          tone={plan.no_order ? "down" : undefined}
        />
        <Row
          label="미체결"
          value={
            plan.no_order
              ? "—"
              : `${Number(plan.unfilled_quantity)}주${
                  Number(plan.cancelled_quantity) > 0
                    ? ` (취소 ${Number(plan.cancelled_quantity)}주)`
                    : ""
                }`
          }
        />
        <Row
          label="평균 체결가"
          value={
            plan.avg_fill_price == null
              ? "—"
              : `$${Number(plan.avg_fill_price).toLocaleString("en-US", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
          }
        />
        <Row
          label="슬리피지"
          value={
            // ⚠️못 잰 이유가 둘이다 — 체결이 없어서와 환율을 몰라서.
            //   하나로 뭉뚱그리면 틀린 이유를 대게 된다(실제로 "환율 없음"이라고
            //   적었는데 사실은 체결이 없던 것이었다).
            slip != null
              ? `${slip > 0 ? "+" : ""}${(slip * 100).toFixed(2)}%`
              : plan.avg_fill_price == null
                ? "— (체결 없음)"
                : plan.planned_price_krw == null
                  ? "— (계획가 없음)"
                  : "— (환율 없음)"
          }
          tone={slip == null ? undefined : slip > 0 ? "down" : "up"}
        />
      </dl>

      <p className="mt-2 text-[11px] leading-snug text-ink-muted">
        {plan.no_order ? (
          <>
            <strong>주문을 내지 않았습니다.</strong> 계획을 세우고 실행하지 않은
            것이라, 안 걸린 것과는 다른 복기입니다.
          </>
        ) : (
          <>
            슬리피지는 <strong>양수면 손해</strong>입니다 — 매수는 비싸게 샀을
            때, 매도는 싸게 팔았을 때입니다.
          </>
        )}
      </p>
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="flex items-baseline justify-between border-b border-hairline py-2">
      <dt className="text-[12px] text-ink-secondary">{label}</dt>
      <dd
        className={cn(
          "text-[13px] font-bold tabular-nums text-ink",
          tone === "up" && "text-bid",
          tone === "down" && "text-ask",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-bold text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
