"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { StubCard } from "@/components/stub";
import {
  getLabDip,
  getLabMeta,
  type DipRow,
  type DipStudy,
  type DipSumm,
} from "@/lib/api-strategy";
import { cn } from "@/lib/utils";

// 투자 전략 › 웅덩이 매수 (전략2).
//
// ★2026-10-29 사용자 정의: '웅덩이가 파졌을 때 샀다면?' — ① n 영업일 연속 종가 하락(3·4·5일) ② 종가가 볼린저 하단(20일, 2σ) 이탈.
//   조건이 처음 성립한 날의 다음 영업일 종가에 사고 5·10 영업일 뒤 수익을, 같은 기간 아무 날 샀을 때(기준선)와 비교한다.
//   종목 기준(바스켓 편입 51종목)과 바스켓 기준(15개 동일가중 지수)을 따로 보인다.

const pct = (v: number | null | undefined, d = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;
const sgn = (v: number | null | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
// ★2026-10-29 2회차: 두 조건이 겹친 날(볼린저 하단을 처음 깬 날에 이미 3일 연속 하락 중)을 맨 위에 둔다.
const COND_ORDER = ["bb_down3", "bb", "down3", "down4", "down5"];
const COND_LABEL: Record<string, string> = {
  bb_down3: "볼린저 이탈 + 3일 하락",
  bb: "볼린저 하단 이탈",
  down3: "3일 연속 하락",
  down4: "4일 연속 하락",
  down5: "5일 연속 하락",
};

export default function DipBuyPage() {
  const [unit, setUnit] = useState<"stock" | "basket">("stock");
  const dip = useQuery({
    queryKey: ["labDip"],
    queryFn: getLabDip,
    staleTime: 30 * 60_000,
  });
  const meta = useQuery({
    queryKey: ["labMeta"],
    queryFn: getLabMeta,
    staleTime: 30 * 60_000,
  });
  const nameOf = (k: string | null) =>
    meta.data?.baskets.find((x) => x.key === k)?.name ?? k ?? "—";

  const d = dip.data;
  const u = d?.[unit];

  return (
    <>
      <Topbar
        title="웅덩이 매수"
        subtitle="연속 하락·볼린저 하단 이탈 뒤에 샀다면"
        showAccountContext={false}
      />
      <PageContainer wide>
        {dip.isLoading && (
          <p className="py-10 text-center text-[12px] text-ink-muted">
            가격을 불러오는 중…
          </p>
        )}
        {dip.isError && (
          <p className="text-[12px] font-bold text-status-failed">
            {(dip.error as Error).message}
          </p>
        )}
        {d && u && (
          <div className="space-y-4">
            <DipVerdict d={d} />
            <StubCard
              title="조건별 결과"
              subtitle={`${meta.data?.start ?? "2026-01-21"} ~ ${d.as_of} · 다음 영업일 종가 매수`}
            >
              <div className="mb-3 flex gap-1.5">
                {(["stock", "basket"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setUnit(k)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-[11px] font-bold",
                      unit === k
                        ? "border-ge-point bg-ge-point text-white"
                        : "border-hairline text-ink-muted hover:bg-canvas-soft",
                    )}
                  >
                    {k === "stock"
                      ? "종목 기준 (51종목)"
                      : "바스켓 기준 (15개)"}
                  </button>
                ))}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-[12px]">
                  <thead className="text-[10.5px] text-ink-faint">
                    <tr>
                      <th className="py-1 text-left">조건</th>
                      <th className="text-right">보유</th>
                      <th className="text-right">횟수</th>
                      <th className="text-right">평균 수익</th>
                      <th className="text-right">이긴 비율</th>
                      <th className="text-right">+5% 이상</th>
                      <th className="text-right">
                        손절 −7% 적용 시 평균 · +5%
                      </th>
                      <th className="text-right">
                        기준선 평균 · 이긴 비율 · +5%
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {COND_ORDER.flatMap((c) =>
                      u.table
                        .filter((r) => r.cond === c)
                        .map((r) => {
                          const better =
                            r.avg != null &&
                            r.base.avg != null &&
                            r.avg - r.base.avg >= 0.01;
                          return (
                            <tr
                              key={`${c}-${r.hold}`}
                              className="border-t border-hairline"
                            >
                              <td className="py-1.5 font-bold text-ge-navy">
                                {r.hold === 5 ? COND_LABEL[c] : ""}
                              </td>
                              <td className="text-right tabular-nums">
                                {r.hold}일
                              </td>
                              <td className="text-right tabular-nums">{r.n}</td>
                              <td
                                className={cn(
                                  "text-right font-bold tabular-nums",
                                  better ? "text-status-success" : "text-ink",
                                )}
                              >
                                {sgn(r.avg)}
                              </td>
                              <td className="text-right tabular-nums">
                                {pct(r.win)}
                              </td>
                              <td className="text-right tabular-nums">
                                {pct(r.hit)}
                              </td>
                              <td className="text-right tabular-nums text-ink-muted">
                                {r.stop
                                  ? `${sgn(r.stop.avg)} · ${pct(r.stop.hit)}`
                                  : "—"}
                              </td>
                              <td className="text-right tabular-nums text-ink-muted">
                                {sgn(r.base.avg)} · {pct(r.base.win)} ·{" "}
                                {pct(r.base.hit)}
                              </td>
                            </tr>
                          );
                        }),
                    )}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-ink-muted">
                초록 = 기준선(같은 기간 아무 날 매수)보다 평균 수익이 1%p 이상
                높음. 손절 = 보유 중 종가가 진입가 대비 −7% 이하로 닫힌 첫날 그
                종가에 판다.
              </p>
            </StubCard>

            {d.check && <CheckCard check={d.check} main={d.stock.table} />}
            {d.regime && <RegimeCard rows={d.regime} />}

            <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
              <StubCard
                title="바스켓별 · 10일 보유"
                subtitle={
                  unit === "stock"
                    ? "편입 종목의 신호를 바스켓별로 묶음"
                    : "바스켓 지수 자체의 신호"
                }
              >
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-[12px]">
                    <thead className="text-[10.5px] text-ink-faint">
                      <tr>
                        <th className="py-1 text-left">바스켓</th>
                        {COND_ORDER.map((c) => (
                          <th key={c} className="text-right">
                            {COND_LABEL[c]}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(meta.data?.baskets ?? []).map((b) => (
                        <tr key={b.key} className="border-t border-hairline">
                          <td className="py-1.5 font-semibold">{b.name}</td>
                          {COND_ORDER.map((c) => (
                            <Cell key={c} s={u.by_basket[b.key]?.[c]} />
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[11px] text-ink-muted">
                  칸 = 평균 수익 · (횟수). 횟수가 적은 칸은 흐리게.
                </p>
              </StubCard>

              <StubCard
                title="지금 웅덩이"
                subtitle={`최근 3 영업일 안에 조건이 처음 성립한 종목 · ${d.as_of} 종가`}
              >
                <ul className="space-y-1.5 text-[12px]">
                  {d.recent.map((r) => (
                    <li
                      key={r.ticker}
                      className="flex flex-wrap items-baseline gap-x-2 rounded-lg px-2 py-1.5 hover:bg-canvas-soft"
                    >
                      <b className="text-ge-navy">{r.ticker}</b>
                      <span className="text-ink-faint">{nameOf(r.basket)}</span>
                      <span className="tabular-nums text-ask">
                        5일 {sgn(r.chg5)}
                      </span>
                      <span className="text-ink-muted">
                        {r.conds.map((c) => COND_LABEL[c]).join(" · ")}
                      </span>
                    </li>
                  ))}
                  {d.recent.length === 0 && (
                    <li className="text-ink-faint">
                      지금 조건을 만족하는 종목이 없습니다.
                    </li>
                  )}
                </ul>
              </StubCard>
            </div>

            <div className="flex gap-2 rounded-xl border border-hairline bg-white px-4 py-3 text-[11px] font-medium leading-relaxed text-ink-muted">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
              <ul className="space-y-0.5">
                <li>
                  · 조건은 처음 성립한 날만 센다(5일 연속 하락이면 3·4일 신호는
                  그 전에 이미 난 것). 같은 종목은 보유 중 새 신호를 무시한다.
                </li>
                <li>
                  · 볼린저 하단 = 20일 이동평균 − 2 × 20일 표준편차. 기준선 =
                  같은 종목들을 같은 기간 아무 날 샀을 때.
                </li>
                <li>
                  · 9개월 남짓의 결과다. 대체로 오른 시기라 기준선도 높다 —
                  하락장에서는 '웅덩이'가 더 깊어질 수 있다.
                </li>
              </ul>
            </div>
          </div>
        )}
      </PageContainer>
    </>
  );
}

function Cell({ s }: { s: DipSumm | undefined }) {
  if (!s || !s.n) return <td className="text-right text-ink-faint">—</td>;
  return (
    <td
      className={cn(
        "text-right tabular-nums",
        s.n < 3 && "opacity-40",
        (s.avg ?? 0) > 0 ? "text-status-success" : "text-status-failed",
      )}
    >
      {sgn(s.avg)} <span className="text-[10px] text-ink-faint">({s.n})</span>
    </td>
  );
}

/** ★2026-10-29 3회차 — 같은 규칙을 분석 기간 직전 1년에 돌린 결과. 분석 기간에서만 통했는지 본다. */
function CheckCard({
  check,
  main,
}: {
  check: { start: string; end: string; table: DipRow[] };
  main: DipRow[];
}) {
  const rows = COND_ORDER.flatMap((c) =>
    check.table.filter((r) => r.cond === c && r.hold === 10),
  );
  const bbMain = main.find((r) => r.cond === "bb" && r.hold === 10);
  const bbCheck = check.table.find((r) => r.cond === "bb" && r.hold === 10);
  const holds =
    bbMain &&
    bbCheck &&
    bbCheck.avg != null &&
    bbCheck.base.avg != null &&
    bbCheck.avg - bbCheck.base.avg >= 0.01;
  return (
    <StubCard
      title="다른 기간에서도 통하나 · 10일 보유"
      subtitle={`검증 기간 ${check.start} ~ ${check.end} (분석 기간 직전 1년, 종목 기준)`}
    >
      <p
        className={cn(
          "mb-3 rounded-lg px-3 py-2 text-[12.5px] font-semibold leading-relaxed",
          holds
            ? "bg-status-success/10 text-status-success"
            : "bg-status-failed/10 text-status-failed",
        )}
      >
        {holds
          ? "검증 기간에서도 볼린저 하단 이탈 매수가 기준선보다 나았습니다."
          : `검증 기간에는 볼린저 하단 이탈 매수가 기준선보다 못했습니다(평균 ${sgn(bbCheck?.avg)} vs ${sgn(bbCheck?.base.avg)}). 분석 기간의 좋은 결과는 그 시기(급락 뒤 빠른 반등)에 묶인 것일 수 있습니다.`}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-[12px]">
          <thead className="text-[10.5px] text-ink-faint">
            <tr>
              <th className="py-1 text-left">조건</th>
              <th className="text-right">횟수</th>
              <th className="text-right">평균 수익</th>
              <th className="text-right">이긴 비율</th>
              <th className="text-right">+5% 이상</th>
              <th className="text-right">기준선 평균 · +5%</th>
              <th className="text-right">분석 기간 평균</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const m = main.find((x) => x.cond === r.cond && x.hold === 10);
              const better =
                r.avg != null &&
                r.base.avg != null &&
                r.avg - r.base.avg >= 0.01;
              const worse =
                r.avg != null &&
                r.base.avg != null &&
                r.avg - r.base.avg <= -0.01;
              return (
                <tr key={r.cond} className="border-t border-hairline">
                  <td className="py-1.5 font-bold text-ge-navy">
                    {COND_LABEL[r.cond]}
                  </td>
                  <td className="text-right tabular-nums">{r.n}</td>
                  <td
                    className={cn(
                      "text-right font-bold tabular-nums",
                      better
                        ? "text-status-success"
                        : worse
                          ? "text-status-failed"
                          : "text-ink",
                    )}
                  >
                    {sgn(r.avg)}
                  </td>
                  <td className="text-right tabular-nums">{pct(r.win)}</td>
                  <td className="text-right tabular-nums">{pct(r.hit)}</td>
                  <td className="text-right tabular-nums text-ink-muted">
                    {sgn(r.base.avg)} · {pct(r.base.hit)}
                  </td>
                  <td className="text-right tabular-nums text-ink-muted">
                    {sgn(m?.avg)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </StubCard>
  );
}

/** ★2026-10-29 4회차 — 시장이 상승 국면(SPY 200일선 위)일 때만 샀다면. 기준선도 같은 날들로만 재야 공정하다. */
function RegimeCard({
  rows,
}: {
  rows: NonNullable<import("@/lib/api-strategy").DipStudy["regime"]>;
}) {
  return (
    <StubCard
      title="시장 국면 필터 · 10일 보유"
      subtitle="SPY 가 200일 이동평균 위인 날에만 산다 · 기준선도 같은 날들로 계산"
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[12px]">
          <thead className="text-[10.5px] text-ink-faint">
            <tr>
              <th className="py-1 text-left">기간</th>
              <th className="text-left">필터</th>
              <th className="text-left">조건</th>
              <th className="text-right">횟수</th>
              <th className="text-right">평균 수익 · +5%</th>
              <th className="text-right">기준선 평균 · +5%</th>
              <th className="text-right">평균 차이</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const edge =
                r.avg != null && r.base.avg != null ? r.avg - r.base.avg : null;
              return (
                <tr
                  key={`${r.period}-${r.filter}-${r.cond}`}
                  className="border-t border-hairline"
                >
                  <td className="py-1.5 font-semibold">{r.period}</td>
                  <td className="text-ink-muted">
                    {r.filter ? "SPY 200일선 위" : "필터 없음"}
                  </td>
                  <td className="font-bold text-ge-navy">
                    {COND_LABEL[r.cond]}
                  </td>
                  <td className="text-right tabular-nums">{r.n}</td>
                  <td className="text-right tabular-nums">
                    {sgn(r.avg)} · {pct(r.hit)}
                  </td>
                  <td className="text-right tabular-nums text-ink-muted">
                    {sgn(r.base.avg)} · {pct(r.base.hit)}
                  </td>
                  <td
                    className={cn(
                      "text-right font-bold tabular-nums",
                      edge == null
                        ? ""
                        : edge >= 0.01
                          ? "text-status-success"
                          : edge <= -0.01
                            ? "text-status-failed"
                            : "text-ink-muted",
                    )}
                  >
                    {edge == null
                      ? "—"
                      : `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)}%p`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
        필터는 검증 기간의 최악 거래를 일부 걸러 내지만(볼린저 이탈 평균 +0.9% →
        +2.0%), 같은 날들의 기준선(+3.4%)은 여전히 넘지 못한다. 상승 국면
        필터만으로는 이 전략을 믿을 근거가 생기지 않는다.
      </p>
    </StubCard>
  );
}

/** ★2026-10-29 정리 회차 — '실전에 써도 되나'를 한 줄로. 볼린저 하단 이탈(10일)을 대표로 두 기간·국면 필터를 함께 본다. */
function DipVerdict({ d }: { d: DipStudy }) {
  const main = d.stock.table.find((r) => r.cond === "bb" && r.hold === 10);
  const chk = d.check?.table.find((r) => r.cond === "bb" && r.hold === 10);
  const reg = d.regime?.find(
    (r) => r.period === "검증 기간" && r.filter && r.cond === "bb",
  );
  const edge = (r?: { avg: number | null; base: { avg: number | null } }) =>
    r && r.avg != null && r.base.avg != null ? r.avg - r.base.avg : null;
  const eMain = edge(main);
  const eChk = edge(chk);
  const eReg = edge(reg);
  const usable = (eMain ?? -1) >= 0.01 && (eChk ?? -1) >= 0.01;
  const pp = (v: number | null) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%p`;
  return (
    <section
      className={cn(
        "rounded-xl border px-4 py-3",
        usable
          ? "border-status-success/40 bg-status-success/5"
          : "border-status-failed/40 bg-status-failed/5",
      )}
    >
      <p
        className={cn(
          "text-[13px] font-extrabold",
          usable ? "text-status-success" : "text-status-failed",
        )}
      >
        결론 ·{" "}
        {usable
          ? "웅덩이 매수를 매수 근거로 쓸 수 있다"
          : "웅덩이 매수를 단독 신호로 쓰지 않는다"}
      </p>
      <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-[12px] leading-relaxed text-ink">
        <li>
          볼린저 하단 이탈 매수(10일 보유)의 평균 수익은 기준선보다 분석 기간{" "}
          <b>{pp(eMain)}</b>, 검증 기간 <b>{pp(eChk)}</b> 다.
        </li>
        <li>
          시장 상승 국면(SPY 200일선 위)에만 사도 검증 기간 차이는 {pp(eReg)}{" "}
          다.
        </li>
        <li>−7% 손절은 모든 조건에서 평균 수익을 낮췄다.</li>
        <li>
          {usable
            ? "두 기간 모두 기준선보다 높다."
            : "좋은 결과가 분석 기간(급락 뒤 빠른 반등장)에만 나왔다. 이 신호는 반등장이 확인된 뒤에 보조 지표로만 본다."}
        </li>
      </ol>
    </section>
  );
}
