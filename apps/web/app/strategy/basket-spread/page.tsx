"use client";

import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { StubCard } from "@/components/stub";
import { SpreadChart } from "@/components/strategy/spread-chart";
import {
  getLabLeaderboard,
  getLabMeta,
  getLabSpread,
  type LabMeta,
  type LabRow,
} from "@/lib/api-strategy";
import { cn } from "@/lib/utils";

// 투자 전략 › 바스켓 괴리 (전략1).
//
// ★2026-10-29 사용자 정의: 괴리 = 바스켓 A 의 n일 지표 − 바스켓 B 의 n일 지표(지표 = 수익률 또는 MA5/20/60 변화율).
//   괴리가 직전 120 영업일의 상위 10% 로 커지면 A 가 비싸다 → B 매수, 하위 10% 면 A 매수.
//   hit = 산 바스켓이 5·10 영업일 뒤 +5% 이상. 분석 기간 2026-01-21 ~ 최근 종가.
// ⚠️조합이 1,680개라 1등 hit ratio 는 운으로도 높다 — 표본 수·기준선(아무 날 매수)을 늘 같이 보인다.

const pct = (v: number | null | undefined, d = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;
const sgn = (v: number | null | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export default function BasketSpreadPage() {
  return (
    <>
      <Topbar
        title="바스켓 괴리"
        subtitle="두 바스켓의 지표 차이가 벌어졌을 때 싼 쪽을 산다면"
        showAccountContext={false}
      />
      <PageContainer wide>
        <Suspense
          fallback={<p className="text-[12px] text-ink-muted">불러오는 중…</p>}
        >
          <View />
        </Suspense>
      </PageContainer>
    </>
  );
}

function View() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const meta = useQuery({
    queryKey: ["labMeta"],
    queryFn: getLabMeta,
    staleTime: 30 * 60_000,
  });

  // 주소창 값이 목록에 없으면(손으로 고친 URL 등) 기본값으로 — 서버가 422 를 내기 전에 막는다.
  const pick = <T,>(v: T, ok: T[] | undefined, dflt: T) =>
    ok && !ok.includes(v) ? dflt : v;
  const keys = meta.data?.baskets.map((x) => x.key);
  const a = pick(params.get("a") ?? "SEMI", keys, "SEMI");
  const b = pick(params.get("b") ?? "HYPER", keys, "HYPER");
  const ind = pick(
    params.get("ind") ?? "ret",
    meta.data ? Object.keys(meta.data.indicators) : undefined,
    "ret",
  );
  const n = pick(Number(params.get("n") ?? 20), meta.data?.ns, 20);
  const hold = pick(Number(params.get("hold") ?? 10), meta.data?.holds, 10);
  const set = (patch: Record<string, string | number>) => {
    const q = new URLSearchParams({
      a,
      b,
      ind,
      n: String(n),
      hold: String(hold),
    });
    Object.entries(patch).forEach(([k, v]) => q.set(k, String(v)));
    router.replace(`${pathname}?${q}`, { scroll: false });
  };

  const spread = useQuery({
    queryKey: ["labSpread", a, b, ind, n, hold],
    queryFn: () => getLabSpread({ a, b, ind, n, hold }),
    enabled: a !== b && !!meta.data,
    staleTime: 30 * 60_000,
    retry: false,
  });
  const [scope, setScope] = useState<"all" | "same" | "cross">("all");
  const board = useQuery({
    queryKey: ["labBoard", hold, scope],
    queryFn: () => getLabLeaderboard(hold, scope),
    enabled: !!meta.data, // 허용 값 목록을 받은 뒤에(주소창의 잘못된 hold 가 400 을 내지 않게)
    staleTime: 30 * 60_000,
  });

  const m = meta.data;
  const nameOf = (k: string) => m?.baskets.find((x) => x.key === k)?.name ?? k;

  if (meta.isLoading)
    return (
      <p className="py-10 text-center text-[12px] text-ink-muted">
        가격을 불러오는 중…(처음엔 몇 초 걸립니다)
      </p>
    );
  if (meta.isError || !m)
    return (
      <p className="text-[12px] font-bold text-status-failed">
        {(meta.error as Error)?.message ?? "불러오지 못했습니다."}
      </p>
    );

  const s = spread.data;
  const lb = board.data;
  const missing = m.missing ?? [];

  return (
    <div className="space-y-4">
      {lb?.direction && <SpreadVerdict rows={lb.direction} hold={hold} />}
      {missing.length > 0 && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-[12px] font-semibold text-amber-800">
          야후에서 받지 못한 종목: {missing.join(", ")} — 그 종목은 바스켓
          평균에서 빠졌습니다(다음 요청 때 다시 받습니다).
        </p>
      )}
      {/* 전체 그림 — 고르기 전에 '이 전략이 대체로 통하나'부터 */}
      {lb && (
        <StubCard
          title="전체 그림"
          subtitle={`${m.start} ~ ${m.as_of} · 보유 ${hold}일 · 조합 ${lb.configs.toLocaleString()}개`}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi
              label="모든 신호의 hit ratio"
              value={pct(lb.pooled_hit)}
              sub={`신호 ${lb.pooled_signals.toLocaleString()}개 합산`}
            />
            <Kpi
              label="아무 날 샀을 때(기준선)"
              value={pct(lb.baseline_avg)}
              sub={`${hold}일 뒤 +5% 이상일 확률, 바스켓 평균`}
            />
            <Kpi
              label="차이"
              value={
                lb.pooled_hit != null && lb.baseline_avg != null
                  ? `${((lb.pooled_hit - lb.baseline_avg) * 100).toFixed(0)}%p`
                  : "—"
              }
              sub="작으면 괴리 신호가 보탠 게 적다"
              tone={
                lb.pooled_hit != null &&
                lb.baseline_avg != null &&
                lb.pooled_hit - lb.baseline_avg >= 0.05
                  ? "good"
                  : "muted"
              }
            />
          </div>
          {/* ★2026-10-29 2회차 — 같은 묶음(섹터·밸류체인)끼리의 괴리가 더 잘 되돌아오나 */}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] text-[12px]">
              <thead className="text-[10.5px] text-ink-faint">
                <tr>
                  <th className="py-1 text-left">쌍 종류</th>
                  <th className="text-right">신호</th>
                  <th className="text-right">hit ratio</th>
                  <th className="text-right">산 바스켓 기준선</th>
                  <th className="text-right">차이</th>
                  <th className="text-right">검증 기간 hit · 기준선</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["all", "전체"],
                    ["same", "같은 묶음끼리 (예: 반도체 top3 − 반도체 장비)"],
                    ["cross", "다른 묶음끼리 (예: 반도체 top3 − 바이오 대장)"],
                  ] as const
                ).map(([k, label]) => {
                  const c = lb.check?.[k];
                  const p = lb.pooled[k];
                  const edge =
                    p.hit != null && p.baseline != null
                      ? p.hit - p.baseline
                      : null;
                  return (
                    <tr key={k} className="border-t border-hairline">
                      <td className="py-1.5 font-semibold">{label}</td>
                      <td className="text-right tabular-nums">
                        {p.signals.toLocaleString()}
                      </td>
                      <td className="text-right font-bold tabular-nums">
                        {pct(p.hit)}
                      </td>
                      <td className="text-right tabular-nums text-ink-muted">
                        {pct(p.baseline)}
                      </td>
                      <td
                        className={cn(
                          "text-right font-bold tabular-nums",
                          (edge ?? 0) >= 0.05
                            ? "text-status-success"
                            : "text-ink-muted",
                        )}
                      >
                        {edge == null
                          ? "—"
                          : `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)}%p`}
                      </td>
                      <td className="text-right tabular-nums text-ink-muted">
                        {c ? `${pct(c.hit)} · ${pct(c.baseline)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1.5 text-[11px] text-ink-muted">
            기준선 = 신호마다 산 바스켓을 같은 기간 아무 날 샀을 때의 +5%
            확률(신호 수로 가중). 검증 기간 = 분석 기간 직전 1년
            {lb.check ? `(${lb.check.start} ~ ${lb.check.end})` : ""}에 같은
            규칙. 두 기간 모두 차이가 작으면 괴리 신호만으로는 근거가 약하다.
          </p>
        </StubCard>
      )}

      {lb?.direction && (
        <StubCard
          title="어느 쪽을 사야 하나"
          subtitle={`같은 신호에서 뒤처진 쪽 vs 앞선 쪽 · 보유 ${hold}일 · 두 기간`}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-[12px]">
              <thead className="text-[10.5px] text-ink-faint">
                <tr>
                  <th className="py-1 text-left">기간</th>
                  <th className="text-left">살 쪽</th>
                  <th className="text-right">신호</th>
                  <th className="text-right">hit ratio</th>
                  <th className="text-right">기준선</th>
                  <th className="text-right">차이</th>
                </tr>
              </thead>
              <tbody>
                {lb.direction.map((r) => {
                  const edge =
                    r.hit != null && r.baseline != null
                      ? r.hit - r.baseline
                      : null;
                  return (
                    <tr
                      key={`${r.period}-${r.mode}`}
                      className="border-t border-hairline"
                    >
                      <td className="py-1.5 font-semibold">{r.period}</td>
                      <td>
                        {r.mode === "reversion"
                          ? "뒤처진 쪽(되돌림)"
                          : "앞선 쪽(추세)"}
                      </td>
                      <td className="text-right tabular-nums">
                        {r.signals.toLocaleString()}
                      </td>
                      <td className="text-right font-bold tabular-nums">
                        {pct(r.hit)}
                      </td>
                      <td className="text-right tabular-nums text-ink-muted">
                        {pct(r.baseline)}
                      </td>
                      <td
                        className={cn(
                          "text-right font-bold tabular-nums",
                          (edge ?? 0) >= 0.05
                            ? "text-status-success"
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
          <p className="mt-1.5 text-[11px] text-ink-muted">
            두 방향 모두, 두 기간 모두 기준선과의 차이가 ±3%p 안이다 — 괴리
            신호는 어느 바스켓을 살지 알려 주지 않는다.
          </p>
        </StubCard>
      )}

      <StubCard
        title="쌍 고르기"
        subtitle="괴리 = A 지표 − B 지표 · 상위 10% 면 B 매수, 하위 10% 면 A 매수"
      >
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <BasketSelect
              label="A"
              value={a}
              meta={m}
              onChange={(v) => set({ a: v })}
            />
            <span className="text-[12px] font-bold text-ink-faint">−</span>
            <BasketSelect
              label="B"
              value={b}
              meta={m}
              onChange={(v) => set({ b: v })}
            />
          </div>
          <Chips
            label="지표"
            items={Object.entries(m.indicators).map(([k, v]) => [k, v])}
            value={ind}
            onPick={(v) => set({ ind: v })}
          />
          <Chips
            label="n일"
            items={m.ns.map((x) => [String(x), `${x}일`])}
            value={String(n)}
            onPick={(v) => set({ n: v })}
          />
          <Chips
            label="보유"
            items={m.holds.map((x) => [String(x), `${x}일`])}
            value={String(hold)}
            onPick={(v) => set({ hold: v })}
          />
        </div>
      </StubCard>

      {a === b && (
        <p className="text-[12px] font-bold text-status-failed">
          서로 다른 바스켓 두 개를 고르세요.
        </p>
      )}
      {spread.isError && (
        <p className="text-[12px] font-bold text-status-failed">
          {(spread.error as Error).message}
        </p>
      )}
      {s && (
        <StubCard
          title={`${nameOf(a)} − ${nameOf(b)} · ${m.indicators[ind]} ${n}일`}
          subtitle={`A: ${m.baskets.find((x) => x.key === a)?.tickers.join(", ")} · B: ${m.baskets.find((x) => x.key === b)?.tickers.join(", ")}`}
        >
          <div className="mb-3 grid gap-3 sm:grid-cols-4">
            <Kpi
              label="신호(결과 확정)"
              value={String(s.stats.signals)}
              sub={`적중 ${s.stats.hits}회`}
            />
            <Kpi
              label="hit ratio"
              value={pct(s.stats.hit_ratio)}
              sub={`${hold}일 뒤 +5% 이상`}
              tone={(s.stats.edge ?? 0) >= 0.05 ? "good" : "muted"}
            />
            <Kpi
              label="기준선"
              value={pct(s.stats.baseline)}
              sub="산 바스켓을 아무 날 샀을 때"
            />
            <Kpi
              label="평균 수익"
              value={sgn(s.stats.avg_ret)}
              sub={`${hold}일 보유`}
            />
          </div>
          <SpreadChart
            dates={s.dates}
            spread={s.spread}
            lo={s.lo}
            hi={s.hi}
            signals={s.signals}
            nameOf={nameOf}
          />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] text-[12px]">
              <thead className="text-[10.5px] text-ink-faint">
                <tr>
                  <th className="py-1 text-left">신호일</th>
                  <th className="text-left">괴리</th>
                  <th className="text-left">매수</th>
                  <th className="text-left">진입</th>
                  <th className="text-right">{hold}일 수익</th>
                  <th className="text-right">판정</th>
                </tr>
              </thead>
              <tbody>
                {s.signals.map((g) => (
                  <tr key={g.date} className="border-t border-hairline">
                    <td className="py-1 tabular-nums">{g.date}</td>
                    <td>
                      {g.side === "hi" ? "A 비쌈(상위 10%)" : "A 쌈(하위 10%)"}
                    </td>
                    <td className="font-bold text-ge-navy">
                      {nameOf(g.bought)}
                    </td>
                    <td className="tabular-nums text-ink-muted">
                      {g.entry ?? "다음 영업일"}
                    </td>
                    <td className="text-right tabular-nums">{sgn(g.ret)}</td>
                    <td
                      className={cn(
                        "text-right font-bold",
                        g.hit == null
                          ? "text-ink-faint"
                          : g.hit
                            ? "text-status-success"
                            : "text-status-failed",
                      )}
                    >
                      {g.hit == null ? "진행 중" : g.hit ? "적중" : "실패"}
                    </td>
                  </tr>
                ))}
                {s.signals.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-3 text-center text-ink-faint">
                      이 기간에 경계를 넘은 날이 없습니다.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </StubCard>
      )}

      {lb && (
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <StubCard
            title={`hit ratio 상위 30 · 보유 ${hold}일`}
            subtitle={`신호 ${lb.min_signals}회 이상만 · 누르면 위 차트로`}
          >
            <div className="mb-2 flex gap-1.5">
              {(
                [
                  ["all", "전체"],
                  ["same", "같은 묶음끼리"],
                  ["cross", "다른 묶음끼리"],
                ] as const
              ).map(([k, v]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setScope(k)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[11px] font-bold",
                    scope === k
                      ? "border-ge-point bg-ge-point text-white"
                      : "border-hairline text-ink-muted hover:bg-canvas-soft",
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-[12px]">
                <thead className="text-[10.5px] text-ink-faint">
                  <tr>
                    <th className="py-1 text-left">A − B</th>
                    <th className="text-left">지표</th>
                    <th className="text-right">신호</th>
                    <th className="text-right">hit</th>
                    <th className="text-right">기준선</th>
                    <th className="text-right">평균</th>
                  </tr>
                </thead>
                <tbody>
                  {lb.top.map((r: LabRow) => (
                    <tr
                      key={`${r.a}-${r.b}-${r.ind}-${r.n}`}
                      className="cursor-pointer border-t border-hairline hover:bg-canvas-soft"
                      onClick={() =>
                        set({ a: r.a, b: r.b, ind: r.ind, n: r.n })
                      }
                    >
                      <td className="py-1 font-semibold">
                        {nameOf(r.a)} − {nameOf(r.b)}
                      </td>
                      <td className="text-ink-muted">
                        {m.indicators[r.ind]} {r.n}일
                      </td>
                      <td className="text-right tabular-nums">{r.signals}</td>
                      <td className="text-right font-bold tabular-nums text-status-success">
                        {pct(r.hit_ratio)}
                      </td>
                      <td className="text-right tabular-nums text-ink-muted">
                        {pct(r.baseline)}
                      </td>
                      <td className="text-right tabular-nums">
                        {sgn(r.avg_ret)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </StubCard>
          <StubCard
            title="최근 3 영업일 새 신호"
            subtitle={`${m.as_of} 종가까지 · 과거 hit ratio 높은 순`}
          >
            <ul className="space-y-1.5 text-[12px]">
              {lb.live.map((x) => (
                <li
                  key={`${x.a}-${x.b}-${x.ind}-${x.n}`}
                  className="cursor-pointer rounded-lg px-2 py-1.5 hover:bg-canvas-soft"
                  onClick={() => set({ a: x.a, b: x.b, ind: x.ind, n: x.n })}
                >
                  <b className="text-ge-navy">{nameOf(x.bought)}</b> 매수 신호
                  <span className="text-ink-muted">
                    {" "}
                    — {nameOf(x.a)} − {nameOf(x.b)}, {m.indicators[x.ind]} {x.n}
                    일 · {x.date} · 과거 {pct(x.hit_ratio)} ({x.signals}회)
                  </span>
                </li>
              ))}
              {lb.live.length === 0 && (
                <li className="text-ink-faint">최근 새 신호가 없습니다.</li>
              )}
            </ul>
          </StubCard>
        </div>
      )}

      <div className="flex gap-2 rounded-xl border border-hairline bg-white px-4 py-3 text-[11px] font-medium leading-relaxed text-ink-muted">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
        <ul className="space-y-0.5">
          <li>
            · 바스켓 지표 = 편입 종목 지표의 평균. 수익률 = 종가_t ÷ 종가_(t−n)
            − 1, MA 변화율 = 이평_t ÷ 이평_(t−n) − 1.
          </li>
          <li>
            · 경계는 그날을 뺀 직전 120 영업일 괴리의 상·하위 10% 다(미래를 쓰지
            않음). 경계를 처음 넘은 날만 신호로 센다.
          </li>
          <li>
            · 신호 다음 영업일 종가에 사고, 보유 중 같은 쌍의 새 신호는
            무시한다. 가격은 야후 일봉(배당 미포함).
          </li>
          <li>
            · 분석 기간이 짧아 쌍마다 신호가 몇 개뿐이다. 상위 30 의 100% 는
            대부분 우연이다 — 전체 그림의 '차이'를 먼저 본다.
          </li>
        </ul>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone = "muted",
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "good" | "muted";
}) {
  return (
    <div className="rounded-lg bg-canvas-soft px-3 py-2.5">
      <p className="text-[10.5px] font-bold text-ink-faint">{label}</p>
      <p
        className={cn(
          "text-[20px] font-extrabold tabular-nums",
          tone === "good" ? "text-status-success" : "text-ink",
        )}
      >
        {value}
      </p>
      <p className="text-[10.5px] text-ink-muted">{sub}</p>
    </div>
  );
}

function BasketSelect({
  label,
  value,
  meta,
  onChange,
}: {
  label: string;
  value: string;
  meta: LabMeta;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex min-w-0 max-w-full items-center gap-1.5 text-[11px] font-bold text-ink-faint">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 max-w-[calc(100vw-5rem)] rounded-lg border border-hairline bg-white px-2 py-1.5 text-[12px] font-semibold text-ink sm:max-w-none"
      >
        {meta.baskets.map((b) => (
          <option key={b.key} value={b.key}>
            {b.name} ({b.tickers.join("·")})
          </option>
        ))}
      </select>
    </label>
  );
}

function Chips({
  label,
  items,
  value,
  onPick,
}: {
  label: string;
  items: string[][];
  value: string;
  onPick: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-10 shrink-0 text-[11px] font-bold text-ink-faint">
        {label}
      </span>
      {items.map(([k, v]) => (
        <button
          key={k}
          type="button"
          onClick={() => onPick(k)}
          className={cn(
            "rounded-full border px-2.5 py-1 text-[11px] font-bold transition-colors",
            value === k
              ? "border-ge-point bg-ge-point text-white"
              : "border-hairline text-ink-muted hover:bg-canvas-soft",
          )}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

/** ★2026-10-29 정리 회차 — '실전에 써도 되나'를 한 줄로. 숫자는 화면이 받은 방향 비교(두 기간 × 두 방향)에서 계산한다. */
function SpreadVerdict({
  rows,
  hold,
}: {
  rows: {
    period: string;
    mode: string;
    hit: number | null;
    baseline: number | null;
    signals: number;
  }[];
  hold: number;
}) {
  const edges = rows.map((r) =>
    r.hit != null && r.baseline != null ? r.hit - r.baseline : null,
  );
  // 쓸 수 있다 = 뒤처진 쪽 매수가 두 기간 모두 기준선보다 5%p 이상 높다.
  const usable = rows
    .filter((r) => r.mode === "reversion")
    .every((r) => r.hit != null && r.baseline != null && r.hit - r.baseline >= 0.05);
  const range = edges.filter((e): e is number => e != null);
  const lo = Math.min(...range) * 100;
  const hi = Math.max(...range) * 100;
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
          ? "괴리 신호를 매수 근거로 쓸 수 있다"
          : "괴리 신호만으로 매수하지 않는다"}
      </p>
      <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-[12px] leading-relaxed text-ink">
        <li>
          두 기간(분석·검증) × 두 방향(뒤처진 쪽·앞선 쪽)에서 hit ratio 와
          기준선의 차이는 {lo.toFixed(1)}%p ~ {hi.toFixed(1)}%p 다(보유 {hold}
          일, +5% 기준).
        </li>
        <li>
          같은 업종끼리 묶어도, 다른 업종끼리 묶어도 차이가 작다(아래 '전체
          그림').
        </li>
        <li>
          {usable
            ? "두 기간 모두 기준선보다 5%p 이상 높다."
            : "차이가 두 기간 모두 5%p 를 넘는 방향이 없다. 아래 상위 30 의 높은 hit ratio 는 표본이 적어 생긴 우연으로 본다."}
        </li>
      </ol>
    </section>
  );
}
