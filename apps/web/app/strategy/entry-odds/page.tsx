"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Info, Search } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { StubCard } from "@/components/stub";
import { getEntryOdds, getEntryOddsUniverse, type EntryOdds, type EntryOddsCell, type EntryOddsRow } from "@/lib/api-strategy";
import { cn } from "@/lib/utils";

// 투자 전략 › 타점 승률 (1단계).
//
// ★2026-10-28 사용자 요청: 롱온리 장기투자 — "지금 이 상태에서 사면 n개월 이상 들고 있을 때 90% 이상 이익이었나".
//   1단계는 지수 1개 또는 종목 1개. 바스켓(2~3종목)은 다음 단계.
// ⚠️과거 통계다. 겹치는 창의 승률은 표본이 부풀려 보인다 — 칸마다 **독립 회차**와 Wilson 하한을 같이 보이고,
//   독립 회차가 적은 칸은 흐리게 그려 '90% 도달'을 판정하지 않는다(서버 MIN_EPISODES).
// ⚠️지금 OHLCV 는 상장 유지 종목만 있다(상장폐지 없음) — 종목 승률은 실제보다 좋게 나온다.

const pct = (v: number | null | undefined, digits = 0) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const signed = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`);
const horizonLabel = (h: number) => (h % 12 === 0 ? `${h / 12}년` : `${h}개월`);

export default function EntryOddsPage() {
  return (
    <>
      <Topbar title="타점 승률" subtitle="이 상태에서 사서 n개월 들고 있었다면" showAccountContext={false} />
      <PageContainer wide>
        <Suspense fallback={<p className="text-[12px] text-ink-muted">불러오는 중…</p>}>
          <EntryOddsView />
        </Suspense>
      </PageContainer>
    </>
  );
}

function EntryOddsView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const ticker = params.get("ticker");
  const series = ticker ? null : (params.get("series") ?? "SPX");
  const target = ticker ? { ticker } : { series: series! };

  const universe = useQuery({ queryKey: ["entryOddsUniverse"], queryFn: getEntryOddsUniverse, staleTime: 60 * 60_000 });
  const odds = useQuery({
    queryKey: ["entryOdds", ticker ?? `s:${series}`],
    queryFn: () => getEntryOdds(target),
    staleTime: 60 * 60_000,
    retry: false,
  });

  const go = (q: string) => router.replace(`${pathname}?${q}`, { scroll: false });
  const [input, setInput] = useState(ticker ?? "");
  // 지수 칩·뒤로가기로 URL 이 바뀌면 입력창도 따라간다
  useEffect(() => setInput(ticker ?? ""), [ticker]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t) go(`ticker=${encodeURIComponent(t)}`);
  };

  const groups = [
    { grp: "index", title: "지수" },
    { grp: "sector", title: "미국 섹터" },
  ];

  return (
    <div className="space-y-4">
      {/* 고르기 — 지수·섹터 칩 또는 종목 티커 */}
      <StubCard title="무엇을 볼까" subtitle="지수는 월말 종가(가격만) · 종목은 수정주가(배당 포함)">
        <div className="space-y-2.5">
          {groups.map((g) => (
            <div key={g.grp} className="flex flex-wrap items-center gap-1.5">
              <span className="w-14 shrink-0 text-[11px] font-bold text-ink-faint">{g.title}</span>
              {(universe.data?.series ?? [])
                .filter((s) => s.grp === g.grp)
                .map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => go(`series=${s.key}`)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[11px] font-bold transition-colors",
                      !ticker && series === s.key
                        ? "border-ge-point bg-ge-point text-white"
                        : "border-hairline text-ink-muted hover:bg-canvas-soft",
                    )}
                  >
                    {s.label}
                  </button>
                ))}
            </div>
          ))}
          <form onSubmit={submit} className="flex items-center gap-1.5">
            <span className="w-14 shrink-0 text-[11px] font-bold text-ink-faint">종목</span>
            <label className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg border border-hairline px-2.5 py-1.5 sm:max-w-xs">
              <Search className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="티커 (NVDA, 005930.KS …)"
                aria-label="종목 티커"
                className="min-w-0 flex-1 bg-transparent text-[12px] font-semibold text-ink outline-none placeholder:text-ink-faint"
              />
            </label>
            <button type="submit" className="rounded-lg bg-ge-point px-3 py-1.5 text-[11px] font-extrabold text-white hover:bg-ge-point/90">
              보기
            </button>
          </form>
        </div>
      </StubCard>

      {odds.isLoading && <p className="py-10 text-center text-[12px] text-ink-muted">계산 중…</p>}
      {odds.isError && (
        <p className="rounded-xl bg-status-failed/5 px-4 py-3 text-[12px] font-bold text-status-failed">
          {(odds.error as Error).message}
        </p>
      )}
      {odds.data && <OddsResult data={odds.data} />}
    </div>
  );
}

function OddsResult({ data }: { data: EntryOdds }) {
  const [sel, setSel] = useState<{ row: EntryOddsRow; cell: EntryOddsCell } | null>(null);
  const active = data.rows.filter((r) => r.active);
  // 결론은 지금 걸린 조건 중 **가장 좁은(구체적인) 것** 하나로 말한다 — 여러 조건 중 가장 짧은 기간을
  //   골라 쓰면 체리피킹이 된다. 행 순서가 넓은 → 좁은 순이고 '10개월선 아래'는 낙폭 조건 뒤에 둔다.
  const SPECIFIC = ["dd50", "dd30", "dd20", "dd10", "below_ma10", "all"];
  const best = SPECIFIC.map((k) => active.find((r) => r.key === k)).find(Boolean);
  const bestCell = best?.min_months_rate != null ? best.cells.find((c) => c.h === best.min_months_rate) : undefined;
  const solid = bestCell?.lower != null && bestCell.lower >= data.target;

  return (
    <>
      <StubCard
        title={`${data.label} · 지금 상태`}
        subtitle={`${data.basis} · ${data.first_month} ~ ${data.data_until ?? data.last_month} (${data.months}개월)`}
      >
        <div className="flex flex-wrap items-center gap-2 text-[12px] font-semibold text-ink-muted">
          <span>
            고점 대비{" "}
            <b className={cn("text-[15px]", (data.now.drawdown ?? 0) < -0.1 ? "text-ask" : "text-ink")}>{signed(data.now.drawdown)}</b>
          </span>
          <span>·</span>
          <span>
            10개월 이동평균 {data.now.below_ma10 == null ? "—" : data.now.below_ma10 ? <b className="text-ask">아래</b> : <b className="text-ink">위</b>}
          </span>
          <span>·</span>
          <span>해당 조건: {active.map((r) => r.label).join(", ")}</span>
        </div>
        <p className="mt-3 rounded-lg bg-canvas-soft px-3 py-2.5 text-[13px] font-semibold leading-relaxed text-ink">
          {best && bestCell ? (
            <>
              과거에 <b>‘{best.label}’</b> 상태에서 샀다면, <b className="text-status-success">{horizonLabel(best.min_months_rate!)} 이상</b> 들고 있을 때
              {" "}이익이었던 비율이 {Math.round(data.target * 100)}%를 넘었습니다({horizonLabel(bestCell.h)}: {pct(bestCell.win_rate)}).{" "}
              {solid ? (
                <span className="text-status-success">독립 {bestCell.episodes}회로 봐도 하한 {pct(bestCell.lower)}입니다.</span>
              ) : (
                <span className="text-ink-muted">
                  다만 서로 겹치지 않는 회차는 {bestCell.episodes}번뿐이라, 통계적으로 확실하다고 할 수 있는 최저치(하한)는 {pct(bestCell.lower)}입니다.
                </span>
              )}
            </>
          ) : best ? (
            <>
              지금 상태(‘{best.label}’)에서는 독립 회차가 {data.min_episodes}회 이상인 보유기간 가운데 승률이 꾸준히 {Math.round(data.target * 100)}%를 넘는
              기간이 없었습니다.
            </>
          ) : (
            <>지금 상태를 판정할 데이터가 없습니다.</>
          )}
        </p>
      </StubCard>

      <StubCard title="조건 × 보유기간 승률" subtitle="칸 = 이익이었던 비율 · 아래 줄 = 독립 회차 · 하한(95%) — 칸을 누르면 상세">
        <div className="-mx-1 overflow-x-auto px-1">
          <table className="w-full min-w-[640px] border-separate border-spacing-1 text-center">
            <thead>
              <tr className="text-[10.5px] font-bold text-ink-faint">
                <th className="text-left font-bold">진입 조건</th>
                {data.horizons.map((h) => (
                  <th key={h}>{horizonLabel(h)}</th>
                ))}
                <th>{Math.round(data.target * 100)}% 도달</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.key}>
                  <th
                    className={cn(
                      "whitespace-nowrap rounded-md px-2 text-left text-[11.5px] font-bold",
                      row.active ? "bg-ge-blue-bg text-ge-point" : "text-ink-muted",
                    )}
                  >
                    {row.label}
                    {row.active && <span className="ml-1 text-[9.5px] font-extrabold">지금</span>}
                  </th>
                  {row.cells.map((c) => (
                    <OddsCell
                      key={c.h}
                      cell={c}
                      target={data.target}
                      thin={c.episodes < data.min_episodes}
                      selected={sel?.row.key === row.key && sel.cell.h === c.h}
                      onSelect={() => setSel({ row, cell: c })}
                    />
                  ))}
                  <td className="text-[12px] font-extrabold text-ge-navy">
                    {row.min_months_rate != null ? `${horizonLabel(row.min_months_rate)}+` : <span className="text-ink-faint">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sel && (
          <p className="mt-2 rounded-lg bg-canvas-soft px-3 py-2 text-[11.5px] font-medium leading-relaxed text-ink-muted">
            <b className="text-ink">
              {sel.row.label} · {horizonLabel(sel.cell.h)} 보유
            </b>{" "}
            — 진입 {sel.cell.n}개월(겹침 포함) 중 {pct(sel.cell.win_rate)} 이익 · 중앙 수익 {signed(sel.cell.median)} · 최악 {signed(sel.cell.worst)} · 보유 중
            최악 낙폭 {signed(sel.cell.worst_dip)} · 독립 {sel.cell.episodes}회 중 {sel.cell.episode_wins}승(하한 {pct(sel.cell.lower)})
          </p>
        )}
      </StubCard>

      <div className="flex gap-2 rounded-xl border border-hairline bg-white px-4 py-3 text-[11px] font-medium leading-relaxed text-ink-muted">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
        <ul className="space-y-0.5">
          <li>· 과거 통계입니다. 예측이 아닙니다. 매달 말 산 경우를 모두 세었으므로 이웃한 달끼리는 결과가 겹칩니다.</li>
          <li>
            · 그래서 보유기간만큼 건너뛴 <b>독립 회차</b>와 그 Wilson 95% <b>하한</b>을 같이 봅니다. 독립 회차가 {data.min_episodes}회 미만인 칸은 흐리게 두고
            ‘{Math.round(data.target * 100)}% 도달’ 판정에서 뺍니다.
          </li>
          <li>· 지수는 배당을 뺀 가격 기준이라 실제 총수익보다 승률이 조금 낮게 나옵니다.</li>
          {data.dropped_before && <li>· 이 지수는 {data.dropped_before}까지 빈 달이 있어 그 이후만 셉니다.</li>}
          {data.now.partial && <li>· 마지막 달({data.now.month})은 아직 끝나지 않아 지금 상태에만 쓰고 과거 표에서는 뺐습니다.</li>}
          <li>· 종목 데이터는 지금 상장된 종목만 있습니다(상장폐지 없음). 종목 승률은 실제보다 좋게 나옵니다.</li>
        </ul>
      </div>
    </>
  );
}

function OddsCell({
  cell,
  target,
  thin,
  selected,
  onSelect,
}: {
  cell: EntryOddsCell;
  target: number;
  thin: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  if (cell.n === 0) {
    return <td className="rounded-md bg-canvas-soft/60 text-[11px] text-ink-faint">—</td>;
  }
  const w = cell.win_rate ?? 0;
  const tone = w >= target ? "bg-status-success/15 text-status-success" : w >= 0.75 ? "bg-status-success/5 text-ink" : "bg-canvas-soft text-ink-muted";
  return (
    <td className="p-0">
      <button
        type="button"
        onClick={onSelect}
        title={`중앙 ${signed(cell.median)} · 최악 ${signed(cell.worst)} · 보유 중 최악 낙폭 ${signed(cell.worst_dip)}`}
        className={cn(
          "w-full rounded-md px-1 py-1.5 transition-shadow",
          tone,
          thin && "opacity-45",
          selected && "ring-2 ring-ge-point",
        )}
      >
        <span className="block text-[13px] font-extrabold tabular-nums">{pct(cell.win_rate)}</span>
        <span className="block text-[9.5px] font-semibold tabular-nums text-ink-faint">
          {cell.episodes}회 · {pct(cell.lower)}
        </span>
      </button>
    </td>
  );
}
