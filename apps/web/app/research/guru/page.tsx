"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { SignedStackedBarChart } from "@/components/charts/signed-stacked-bar-chart";
import { CHART_MUTED, CHART_PALETTE } from "@/components/charts/donut-chart";
import { CardEmpty, Cell, DataTable, HeaderChip, ListButton, StatTile, StubCard } from "@/components/stub";
import { CoveragePanel } from "@/components/research/coverage-panel";
import {
  getGuruOverview,
  getGuruQuarter,
  getGuruStock,
  type GuruMyHolding,
  type GuruStockMove,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { GuruManager } from "./guru-manager";

// 거장 13F — 거장 23명의 분기 변동과 내 보유 종목 (계획 A5, docs/plans/2026-09-26-integration-…md 와이어프레임 A-1).
//
// ★예측 화면이 아니다. 같은 데이터로 만든 시그널 24조합 검증에서 통과 0 — "무슨 일이 있었나"만 본다.
// 숫자가 조용히 틀리지 않게 화면이 스스로 말하게 한 것:
//   1. 제출률 50% 미만인 분기는 비교하지 않는다(정족수) — 마감 전엔 1명짜리 "합의"가 된다.
//   2. 최근 분기를 안 낸 거장은 직전 보유를 이월하지 않는다 — 제출 현황에 "미제출 · 마지막 분기" 배지.
//   3. 섹터 맵이 못 덮는 비중은 '미분류'(회색)로 그대로 둔다. 두 분기 커버리지 격차가 1%p 이상이면
//      미분류의 순변화는 매핑 결손 탓일 수 있다 — 막대 라벨에 * 표시.
//   4. 비중은 거장마다 따로 낸 뒤 **거장 평균**으로 합친다(금액을 더하지 않는다 — 단위가 섞여 있다).

const UNCLASSIFIED = "미분류";

function bp(v: number | null | undefined, signed = true): string {
  if (v == null) return "—";
  const s = signed && v > 0 ? "+" : "";
  return `${s}${Math.round(v).toLocaleString()}bp`;
}

function wpct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v / 100).toFixed(v >= 100 ? 1 : 2)}%`;
}

function nameOf(r: { ticker: string | null; name: string | null }): string {
  return r.ticker ?? r.name ?? "—";
}

type QuarterTab = "entries" | "exits" | "rebalance" | "sector";

export default function GuruPage() {
  const [rosterOpen, setRosterOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [moveList, setMoveList] = useState<"entries" | "exits" | null>(null);
  const [mineOpen, setMineOpen] = useState(false);
  const [quarter, setQuarter] = useState<string | null>(null);
  const [tab, setTab] = useState<QuarterTab>("entries");
  const [stock, setStock] = useState<GuruMyHolding | null>(null);
  const [hoverQ, setHoverQ] = useState<string | null>(null);

  const q = useQuery({ queryKey: ["guruOverview"], queryFn: getGuruOverview, staleTime: 10 * 60_000 });
  const d = q.data;

  const detail = useQuery({
    queryKey: ["guruQuarter", quarter],
    queryFn: () => getGuruQuarter(quarter!),
    enabled: quarter != null,
    staleTime: 10 * 60_000,
  });
  const trend = useQuery({
    queryKey: ["guruStock", stock?.ticker],
    queryFn: () => getGuruStock(stock!.ticker),
    enabled: stock != null,
    staleTime: 10 * 60_000,
  });

  // 섹터 색: 전체 기간 |순유입| 합이 큰 순서로 팔레트 — 미분류는 늘 회색.
  const colors = useMemo(() => {
    const tot = new Map<string, number>();
    for (const h of d?.sector_history ?? [])
      for (const r of h.rows) tot.set(r.sector, (tot.get(r.sector) ?? 0) + Math.abs(r.net_bp));
    const keys = [...tot.entries()].filter(([k]) => k !== UNCLASSIFIED).sort((a, b) => b[1] - a[1]).map(([k]) => k);
    const out: Record<string, string> = { [UNCLASSIFIED]: CHART_MUTED };
    keys.forEach((k, i) => (out[k] = CHART_PALETTE[i % CHART_PALETTE.length]));
    return out;
  }, [d]);

  const columns = useMemo(
    () =>
      (d?.sector_history ?? []).map((h) => ({
        key: h.period,
        label: h.label,
        flag: h.unclassified_unreliable,
        segments: h.rows.map((r) => ({ key: r.sector, value: r.net_bp })),
      })),
    [d],
  );
  const shownQ = d?.sector_history.find((h) => h.period === hoverQ) ?? d?.sector_history.at(-1);

  const latest = d?.latest;
  const quorumOk = latest?.usable ?? false;
  const heldMine = d?.my_holdings.filter((h) => h.n_gurus > 0).length ?? 0;
  const pair = d?.curr && d?.prev ? `${d.curr.label} vs ${d.prev.label}` : "—";
  const openQuarter = (period: string, t: QuarterTab = "entries") => {
    setTab(t);
    setQuarter(period);
  };

  return (
    <>
      <Topbar
        title="거장 포트폴리오(13F)"
        subtitle={
          d?.curr
            ? `거장 ${d.n_gurus}명 · 비교 ${pair} · 공시 기준(분기말 +45일) · 예측 아님`
            : "거장 13F 분기 변동 · 예측 아님"
        }
      />
      <PageContainer fit>
        <CoveragePanel kind="guru" />
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label={latest ? `${latest.label} 제출 ${latest.n_filed}/${latest.n_gurus}` : "이번 분기 제출"}
            value={latest ? `${latest.filed_pct.toFixed(0)}%` : null}
            hint={
              latest
                ? quorumOk
                  ? `정족수(50%) 통과 · 미제출 ${latest.n_gurus - latest.n_filed}명`
                  : `집계 대기 — 정족수 미달, 비교는 ${pair}`
                : undefined
            }
            onClick={() => setRosterOpen(true)}
            actionHint="눌러서 제출 현황"
            loading={q.isLoading}
          />
          <StatTile
            label="여럿이 새로 산 종목"
            value={d ? `${d.multi_entries.length}종목` : null}
            hint={d ? `${d.multi_entries.slice(0, 3).map(nameOf).join(" · ") || "없음"} · 2명 이상 · ${pair}` : undefined}
            onClick={() => setMoveList("entries")}
            actionHint="눌러서 목록"
            loading={q.isLoading}
          />
          <StatTile
            label="여럿이 전량 판 종목"
            value={d ? `${d.multi_exits.length}종목` : null}
            hint={d ? `${d.multi_exits.slice(0, 3).map(nameOf).join(" · ") || "없음"} · 2명 이상 · ${pair}` : undefined}
            onClick={() => setMoveList("exits")}
            actionHint="눌러서 목록"
            loading={q.isLoading}
          />
          <StatTile
            label="내 보유 × 거장"
            value={d ? `${heldMine}/${d.my_holdings.length} 종목에 거장` : null}
            hint={d ? `${d.curr?.label ?? ""} 기준 · 미국 보유 종목` : undefined}
            onClick={() => setMineOpen(true)}
            actionHint="눌러서 표"
            loading={q.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "lg:auto-rows-auto lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="분기별 섹터 순유입"
            subtitle="거장 평균 비중 변화(bp) · 막대를 누르면 그 분기 종목 변동"
            scrollBody
            action={d?.curr ? <ListButton onClick={() => openQuarter(d.curr!.period)} /> : undefined}
          >
            {q.isLoading || !d ? (
              <CardEmpty text={q.isLoading ? "불러오는 중…" : "데이터 없음"} />
            ) : (
              <div className="flex h-full flex-col gap-2">
                <SignedStackedBarChart
                  columns={columns}
                  colors={colors}
                  height={260}
                  formatValue={(v) => bp(v)}
                  selected={shownQ?.period}
                  onHover={setHoverQ}
                  onPick={(k) => openQuarter(k, "sector")}
                />
                {shownQ && (
                  <div className="rounded-lg bg-ge-th/60 px-3 py-2">
                    <div className="mb-1 flex items-baseline justify-between text-[11px] font-bold text-ink">
                      <span>
                        {shownQ.label} vs {shownQ.prev.label} · 거장 {shownQ.n_participants}명
                      </span>
                      <span
                        className={cn(
                          "text-[10px] font-semibold",
                          shownQ.unclassified_unreliable ? "text-ge-point" : "text-ink-faint",
                        )}
                      >
                        섹터 커버리지 {shownQ.coverage_prev}% → {shownQ.coverage_curr}%
                        {shownQ.unclassified_unreliable ? " · * 미분류 변화는 매핑 격차 탓일 수 있음" : ""}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 sm:grid-cols-3">
                      {shownQ.rows.map((r) => (
                        <div key={r.sector} className="flex items-center gap-1.5 text-[11px]">
                          <span className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: colors[r.sector] }} />
                          <span className="truncate text-ink-secondary">{r.sector}</span>
                          <span
                            className={cn(
                              "ml-auto font-semibold tabular-nums",
                              r.net_bp > 0 ? "text-bid" : r.net_bp < 0 ? "text-ask" : "text-ink-faint",
                            )}
                          >
                            {bp(r.net_bp)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <p className="mt-auto text-[10.5px] font-semibold text-ink-faint">⚠️ {d.disclaimer}</p>
              </div>
            )}
          </StubCard>

          <StubCard
            title="내 보유 종목 × 거장"
            subtitle={d?.curr ? `${pair} · 행을 누르면 거장별 비중 추이` : undefined}
            scrollBody
          >
            {q.isLoading || !d ? (
              <CardEmpty text={q.isLoading ? "불러오는 중…" : "데이터 없음"} />
            ) : (
              <MineTable rows={d.my_holdings} onPick={setStock} />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={rosterOpen}
        onClose={() => setRosterOpen(false)}
        title="거장 제출 현황"
        subtitle={latest ? `${latest.label} ${latest.n_filed}/${latest.n_gurus}명 · 정족수 50%` : undefined}
      >
        {d && (
          <div className="space-y-4">
            <DataTable columns={["분기", "제출", "제출률", "비교에 씀"]}>
              {d.period_meta.slice(0, 8).map((m) => (
                <tr key={m.period} className="border-b border-hairline">
                  <Cell left strong>{m.label}</Cell>
                  <Cell>{m.n_filed}</Cell>
                  <Cell>{m.filed_pct.toFixed(0)}%</Cell>
                  <Cell tone={m.usable ? undefined : "muted"}>{m.usable ? "예" : "집계 대기"}</Cell>
                </tr>
              ))}
            </DataTable>
            <DataTable columns={["거장", "운용사", "최근 제출"]} align={["left", "left", "right"]}>
              {d.roster.map((r) => (
                <tr key={r.cik} className="border-b border-hairline">
                  <Cell left strong>{r.guru}</Cell>
                  <Cell left>{r.firm}</Cell>
                  <Cell tone={r.filed_latest ? undefined : "down"}>
                    {r.filed_latest ? r.last_period?.label : `미제출 · 마지막 ${r.last_period?.label ?? "없음"}`}
                  </Cell>
                </tr>
              ))}
            </DataTable>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setRosterOpen(false);
                  setManageOpen(true);
                }}
                className="shrink-0 rounded-lg bg-ge-header px-3 py-1.5 text-[12px] font-bold text-white"
              >
                + 거장 추가 · 관리
              </button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        title="거장 관리"
        subtitle="SEC 검색 → 추가 → 2013Q2 부터 백필 · 끄면 분석에서만 빠짐"
        width={860}
      >
        {manageOpen && <GuruManager />}
      </Modal>

      <Modal
        open={moveList != null}
        onClose={() => setMoveList(null)}
        title={moveList === "exits" ? "여럿이 전량 판 종목" : "여럿이 새로 산 종목"}
        subtitle={`${pair} · 두 분기 모두 낸 거장 ${d?.n_participants ?? 0}명 중 2명 이상`}
      >
        {d && <MoveTable rows={moveList === "exits" ? d.multi_exits : d.multi_entries} />}
      </Modal>

      <Modal open={mineOpen} onClose={() => setMineOpen(false)} title="내 보유 종목 × 거장" subtitle={pair}>
        {d && (
          <MineTable
            rows={d.my_holdings}
            onPick={(r) => {
              setMineOpen(false);
              setStock(r);
            }}
          />
        )}
      </Modal>

      <Modal
        open={quarter != null}
        onClose={() => setQuarter(null)}
        title={detail.data ? `${detail.data.curr.label} vs ${detail.data.prev.label} 종목 변동` : "분기 종목 변동"}
        subtitle={detail.data ? `두 분기 모두 낸 거장 ${detail.data.n_participants}명 · 예측 아님` : undefined}
        width={860}
      >
        <div className="mb-3 flex gap-1 rounded-lg bg-ge-header px-2 py-1.5">
          {(
            [
              ["entries", "새로 산"],
              ["exits", "전량 판"],
              ["rebalance", "동시 조정"],
              ["sector", "섹터"],
            ] as const
          ).map(([k, l]) => (
            <HeaderChip key={k} active={tab === k} onClick={() => setTab(k)}>
              {l}
            </HeaderChip>
          ))}
        </div>
        {detail.isLoading || !detail.data ? (
          <CardEmpty text="불러오는 중…" />
        ) : tab === "entries" ? (
          <MoveTable rows={detail.data.entries} total={detail.data.total_entries} />
        ) : tab === "exits" ? (
          <MoveTable rows={detail.data.exits} total={detail.data.total_exits} />
        ) : tab === "rebalance" ? (
          <DataTable columns={["종목", "조정 거장", "늘림/줄임", "총량", "순방향", "일치도"]}>
            {detail.data.rebalance.map((r) => (
              <tr key={r.key} className="border-b border-hairline">
                <Cell left strong>
                  {nameOf(r)}
                  {r.ticker && <span className="ml-1.5 font-normal text-ink-faint">{r.name}</span>}
                </Cell>
                <Cell>{r.movers}</Cell>
                <Cell>
                  {r.buyers}/{r.sellers}
                </Cell>
                <Cell>{bp(r.gross_bp, false)}</Cell>
                <Cell tone={r.net_bp > 0 ? "up" : r.net_bp < 0 ? "down" : undefined}>{bp(r.net_bp)}</Cell>
                <Cell tone={r.agreement < 0.5 ? "muted" : undefined}>{(r.agreement * 100).toFixed(0)}%</Cell>
              </tr>
            ))}
          </DataTable>
        ) : (
          <DataTable columns={["섹터", "순유입", "직전 비중", "지금 비중", "늘림/줄임", "주요 종목"]}>
            {detail.data.sector.rows.map((r) => (
              <tr key={r.sector} className="border-b border-hairline">
                <Cell left strong>
                  <span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: colors[r.sector] }} />
                  {r.sector}
                </Cell>
                <Cell tone={r.net_bp > 0 ? "up" : r.net_bp < 0 ? "down" : undefined}>{bp(r.net_bp)}</Cell>
                <Cell>{wpct(r.prev_wgt_bp)}</Cell>
                <Cell>{wpct(r.curr_wgt_bp)}</Cell>
                <Cell>
                  {r.up}/{r.down}
                </Cell>
                <Cell left tone="muted">
                  {r.top
                    .slice(0, 3)
                    .map((t) => `${nameOf(t)} ${bp(t.delta_bp)}`)
                    .join(" · ")}
                </Cell>
              </tr>
            ))}
          </DataTable>
        )}
      </Modal>

      <Modal
        open={stock != null}
        onClose={() => setStock(null)}
        title={stock ? `${stock.ticker} × 거장` : ""}
        subtitle={stock ? `거장별 포트폴리오 비중 추이 · 빈칸 = 그 분기 미제출(이월하지 않음)` : undefined}
        width={860}
      >
        {trend.isLoading || !trend.data ? (
          <CardEmpty text="불러오는 중…" />
        ) : (
          <DataTable columns={["거장", ...trend.data.periods.map((p) => p.label)]}>
            {trend.data.gurus.map((g) => (
              <tr key={g.cik} className="border-b border-hairline">
                <Cell left strong>
                  {g.guru}
                </Cell>
                {g.points.map((v, i) => (
                  <Cell key={i} tone={v == null ? "muted" : v === 0 ? "muted" : undefined}>
                    {v == null ? "" : v === 0 ? "·" : wpct(v)}
                  </Cell>
                ))}
              </tr>
            ))}
          </DataTable>
        )}
      </Modal>
    </>
  );
}

function MoveTable({ rows, total }: { rows: GuruStockMove[]; total?: number }) {
  return (
    <div className="space-y-2">
      <DataTable columns={["종목", "거장 수", "합계 비중", "거장(비중)"]} align={["left", "right", "right", "left"]}>
        {rows.map((r) => (
          <tr key={r.key} className="border-b border-hairline">
            <Cell left strong>
              {nameOf(r)}
              {r.ticker && <span className="ml-1.5 font-normal text-ink-faint">{r.name}</span>}
            </Cell>
            <Cell>{r.n_gurus}</Cell>
            <Cell>{wpct(r.total_bp)}</Cell>
            <Cell left tone="muted" className="whitespace-normal">
              {r.gurus.map((g) => `${g.guru} ${wpct(g.bp)}`).join(" · ")}
            </Cell>
          </tr>
        ))}
      </DataTable>
      {total != null && total > rows.length && (
        <p className="text-[11px] text-ink-faint">
          전체 {total}종목 중 상위 {rows.length} (거장 수 → 합계 비중 순)
        </p>
      )}
    </div>
  );
}

function MineTable({ rows, onPick }: { rows: GuruMyHolding[]; onPick: (r: GuruMyHolding) => void }) {
  return (
    <DataTable columns={["종목", "든 거장", "거장 평균 비중", "직전 대비"]}>
      {rows.map((r) => (
        <tr
          key={r.ticker}
          className="cursor-pointer border-b border-hairline transition-colors hover:bg-ge-th/60"
          onClick={() => onPick(r)}
        >
          <Cell left strong>
            {r.ticker}
            <span className="ml-1.5 font-normal text-ink-faint">{r.name}</span>
          </Cell>
          <Cell tone={r.n_gurus === 0 ? "muted" : undefined}>{r.n_gurus}명</Cell>
          <Cell tone={r.n_gurus === 0 ? "muted" : undefined}>{wpct(r.avg_bp)}</Cell>
          <Cell tone={r.delta_bp == null || r.delta_bp === 0 ? "muted" : r.delta_bp > 0 ? "up" : "down"}>
            {bp(r.delta_bp)}
          </Cell>
        </tr>
      ))}
    </DataTable>
  );
}
