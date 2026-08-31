"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getEpochChips,
  getEpochCompanies,
  getEpochDatacenters,
  type AiSeries,
  type EpochChips,
  type EpochCompanies,
  type EpochDatacenters,
} from "@/lib/api";
import { TimeSeriesChart } from "@/components/ai-key-data/timeseries-chart";
import { TabChips } from "@/components/ai-key-data/tab-chips";
import { cn } from "@/lib/utils";

// [AI Key Data] Epoch AI — 메인 페이지 1행 오른쪽 3칸.
//
// ★2026-08-28(2차) 사용자 지시로 `/ai-key-data/epoch` 하위 페이지를 없애고 **메인으로
//   편입**했다. 자리는 두 묶음을 탭으로 접어 만들었다(정책금리+채권 / 인플레+WTI).
//   그래서 이 카드는 더 이상 "세로로 쌓고 스크롤"이 아니라 **그리드 한 칸 높이에
//   갇힌다** — 패널 높이를 h-64 로 박아 두면 칸을 넘쳐 페이지가 스크롤된다.
//   패널은 h-full 로 칸을 나눠 갖고, 데이터센터 탭만 패널이 3개라 3열로 편다.
// AI 사용량(매일 갱신되는 채택 지표)과 Epoch(3년에 수십 행짜리 산업 구조 통계)은
// 성격이 달라 여전히 다른 카드다 — 탭으로 섞지 않는다.
//
// ★★2026-08-28 실제 백엔드로 검증(curl) — 3종 payload 가 서로 다 다른 모양이라
//   (§lib/api.ts 주석) 카드가 각각 작은 매퍼로 `AiSeries[]` 를 만든다:
//   · 기업 매출 — API 가 이미 [날짜,값] 쌍이라 바로 씀
//   · 기업 펀딩 — 이벤트 목록(rounds)이라 회사별로 묶어 점을 만든다(scatter)
//   · 칩 — `quarters` 공유축 + 설계사별 병렬 배열(flow/cum)이라 zip 해서 만든다
//   · 데이터센터 — 레코드 배열(buildout) 하나에 지표 3개가 같이 있어 풀어낸다
// usage·compute_spend 그룹은 백엔드에 없다(ws1 실측으로 1차 제외 확정 — 마스터
// 플랜 §4, ws2 설계 문서의 4그룹 표는 그 확정 전 초안).
// 라이선스는 `source.license`("CC BY 4.0")를 그대로 노출한다(임의로 짓지 않는다).

const POLL_MS = 1_800_000;
const PALETTE = ["#4a7ab5", "#e8871e", "#2aa876", "#7b5ea7"];

type Tab = "companies" | "chips" | "datacenters";
const TABS: { key: Tab; label: string }[] = [
  { key: "companies", label: "AI 기업" },
  { key: "chips", label: "칩 공급" },
  { key: "datacenters", label: "데이터센터" },
];

function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US");
}

// 그룹 하나 = 미니 패널(제목 + 범례 숫자 + 차트). note 는 group 이 아니라
// 카드 최상위(active.data.note)에 실리므로 여기선 series 빈 배열만 판단한다.
function Panel({
  title,
  series,
  emptyMsg,
}: {
  title: string;
  series: AiSeries[];
  emptyMsg?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const top = series.slice(0, 4);

  return (
    // h-full — 카드가 그리드 한 칸에 갇히므로 패널이 그 높이를 나눠 갖는다.
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-hairline/70">
      <div className="flex items-center gap-2 border-b border-hairline/70 px-2.5 py-1">
        <span className="text-[11.5px] font-bold text-ink">{title}</span>
      </div>
      {top.length > 0 ? (
        <div className="flex flex-wrap gap-x-2 gap-y-0 px-2.5 pt-1 text-[10.5px]">
          {top.map((s, i) => (
            <span key={s.key} className="flex items-baseline gap-1">
              <span
                className="inline-block h-1.5 w-1.5 shrink-0 rounded-sm"
                style={{ background: PALETTE[i % PALETTE.length] }}
              />
              <span className="text-ink-muted">{s.label}</span>
              <b className="font-bold tabular-nums text-ink">
                {s.last == null ? "—" : fmtCompact(s.last)}
              </b>
            </span>
          ))}
        </div>
      ) : null}
      <div ref={wrapRef} className="min-h-0 flex-1 px-1 pb-1 pt-0.5">
        {top.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4 text-center">
            <span className="text-[11px] font-semibold leading-relaxed text-ink-muted">
              {emptyMsg ?? "판독 대기 중 — 데이터가 들어오면 자동 표시됩니다."}
            </span>
          </div>
        ) : box.w > 0 && box.h > 0 ? (
          <TimeSeriesChart series={top} w={box.w} h={box.h} fmt={fmtCompact} colors={PALETTE} />
        ) : null}
      </div>
    </div>
  );
}

// ── 매퍼 — API 원본 모양 → AiSeries[] ────────────────────────────────────────

function mapRevenue(d: EpochCompanies | undefined): AiSeries[] {
  const g = d?.revenue;
  if (!g) return [];
  return [...g.series]
    .sort((a, b) => (b.stats.last ?? 0) - (a.stats.last ?? 0))
    .map((s) => ({
      key: s.key,
      label: s.name,
      kind: g.kind,
      last: s.stats.last,
      points: s.points,
    }));
}

// 펀딩은 시계열이 아니라 이벤트 목록(rounds) — 회사별로 묶어 [날짜, equity] 점을
// 만든다. equity 가 없는 라운드(부채만 있는 등)는 스킵 — 0으로 채우면 "무상 라운드"
// 처럼 보인다(§6.4 규칙 3 — 정직한 결측 처리).
function mapFunding(d: EpochCompanies | undefined): AiSeries[] {
  const g = d?.funding;
  if (!g) return [];
  const byCompany = new Map<string, [string, number][]>();
  for (const r of g.rounds) {
    if (r.equity == null) continue;
    const arr = byCompany.get(r.company) ?? [];
    arr.push([r.date, r.equity]);
    byCompany.set(r.company, arr);
  }
  return [...byCompany.entries()]
    .map(([company, points]) => {
      points.sort((a, b) => a[0].localeCompare(b[0]));
      const total = points.reduce((s, p) => s + p[1], 0);
      return { key: company, label: company, kind: g.kind, last: total, points };
    })
    .sort((a, b) => (b.last ?? 0) - (a.last ?? 0));
}

// 칩은 `quarters`(공유 x축) + 설계사별 병렬 배열 — zip 해서 [분기, 누적] 점을 만든다.
function mapChipsCumulative(d: EpochChips | undefined): AiSeries[] {
  if (!d) return [];
  return [...d.designers]
    .sort((a, b) => b.stats.cum_last - a.stats.cum_last)
    .map((des) => ({
      key: des.key,
      label: des.name,
      kind: "step" as const, // 분기 누적 — 다음 분기 공시 전까지 유지되는 계단
      last: des.stats.cum_last,
      points: d.quarters.map((q, i) => [q, des.cum[i] ?? null] as [string, number | null]),
    }));
}

function mapChipsFlow(d: EpochChips | undefined): AiSeries[] {
  if (!d) return [];
  return [...d.designers]
    .sort((a, b) => b.stats.flow_last - a.stats.flow_last)
    .map((des) => ({
      key: des.key,
      label: des.name,
      // API 의 kind:"bar" 는 이 레포 컨벤션에 없다 — 가장 가까운 시각 표현인
      // step 으로 대체한다(분기 신규분을 다음 분기까지 값으로 유지해 보여준다).
      kind: "step" as const,
      last: des.stats.flow_last,
      points: d.quarters.map((q, i) => [q, des.flow[i] ?? null] as [string, number | null]),
    }));
}

// 데이터센터는 buildout 레코드 배열 하나에 지표 3개가 같이 있다 — 지표별로 푼다.
function mapDcMetric(
  d: EpochDatacenters | undefined,
  key: "it_power_mw" | "h100e" | "capex_bn",
  label: string,
): AiSeries[] {
  if (!d) return [];
  const points = d.buildout.map((b) => [b.date, b[key]] as [string, number | null]);
  return [{ key, label, kind: "step", last: points.length ? points[points.length - 1][1] : null, points }];
}

export function EpochCard() {
  const [tab, setTab] = useState<Tab>("companies");

  const compQ = useQuery<EpochCompanies>({
    queryKey: ["epoch-companies"],
    queryFn: getEpochCompanies,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "companies",
  });
  const chipQ = useQuery<EpochChips>({
    queryKey: ["epoch-chips"],
    queryFn: getEpochChips,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "chips",
  });
  const dcQ = useQuery<EpochDatacenters>({
    queryKey: ["epoch-datacenters"],
    queryFn: getEpochDatacenters,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
    enabled: tab === "datacenters",
  });

  const active = tab === "companies" ? compQ : tab === "chips" ? chipQ : dcQ;

  return (
    <section className="lg:col-span-3 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas">
      {/* 제목 띠 강조색(ge-header) — 2026-08-28 사용자 지시로 페이지 카드가 전부 같은 색. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[13px] font-extrabold text-white">Epoch AI</h2>
        <TabChips tabs={TABS} value={tab} onChange={setTab} />
        <span className="ml-auto shrink-0 text-[10px] text-white/60">
          {active.data?.source?.license ?? "CC BY 4.0 — Epoch AI"}
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-1 p-1.5 pt-1">
        {active.isLoading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[12px] font-semibold text-ink-muted">
            불러오는 중…
          </div>
        ) : active.isError ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[12px] font-semibold text-rose-600">
            collector 에 못 닿았습니다.
          </div>
        ) : (
          <div
            className={cn(
              "grid min-h-0 flex-1 grid-cols-1 gap-1.5",
              // 데이터센터만 패널 3개 — 2열로 두면 셋째가 아래로 접혀 칸을 넘친다.
              tab === "datacenters" ? "md:grid-cols-3" : "md:grid-cols-2",
            )}
          >
            {tab === "companies" ? (
              <>
                <Panel title="매출(연환산)" series={mapRevenue(compQ.data)} />
                <Panel
                  title="펀딩 라운드(회사별 누적)"
                  series={mapFunding(compQ.data)}
                  emptyMsg={compQ.data?.funding?.note ?? undefined}
                />
              </>
            ) : tab === "chips" ? (
              <>
                <Panel title="H100e 누적(설계사별)" series={mapChipsCumulative(chipQ.data)} />
                <Panel title="분기 신규(설계사별)" series={mapChipsFlow(chipQ.data)} />
              </>
            ) : (
              <>
                <Panel
                  title={`전력(${dcQ.data?.units.power ?? "MW"})`}
                  series={mapDcMetric(dcQ.data, "it_power_mw", "IT 전력")}
                />
                <Panel
                  title={dcQ.data?.units.compute ?? "H100e"}
                  series={mapDcMetric(dcQ.data, "h100e", "H100e")}
                />
                <Panel
                  title={`Capex(${dcQ.data?.units.capex ?? "USD bn"})`}
                  series={mapDcMetric(dcQ.data, "capex_bn", "Capex")}
                />
              </>
            )}
          </div>
        )}
        {active.data?.note ? (
          <div className="shrink-0 truncate px-1 text-[10.5px] font-semibold text-amber-600">
            {active.data.note}
          </div>
        ) : null}
      </div>
    </section>
  );
}
