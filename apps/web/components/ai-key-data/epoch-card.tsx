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
import { Panel } from "@/components/ai-key-data/panel";
import { cn } from "@/lib/utils";
import { POLL_MS } from "@/components/ai-key-data/poll";
import { useCardZoom, ZoomButton } from "@/components/ai-key-data/card-zoom";

// [AI Key Data] Epoch AI — 메인 페이지 1행 오른쪽 3칸.
//
// ★2026-08-28(2차) 사용자 지시로 `/ai-key-data/epoch` 하위 페이지를 없애고 **메인으로
//   편입**했다. 자리는 두 묶음을 탭으로 접어 만들었다(정책금리+채권 / 인플레+WTI).
//   그래서 이 카드는 더 이상 "세로로 쌓고 스크롤"이 아니라 **그리드 한 칸 높이에
//   갇힌다** — 패널 높이를 h-64 로 박아 두면 칸을 넘쳐 페이지가 스크롤된다.
//   패널은 h-full 로 칸을 나눠 갖고, 데이터센터 탭만 패널이 3개라 3열로 편다.
// ★★2026-08-31 사용자 지시로 **펀딩 라운드를 이 카드에서 떼어냈다.** 펀딩은 '돈이
//   들어오는 양'이라 [Demand] 분류이고, 이 카드에 남은 매출·칩·데이터센터는 '얼마를
//   벌고 무엇이 깔렸는가'라 [수익성] 분류다. 떼어낸 쪽은 `epoch-funding-card.tsx`.
//   ⚠️두 카드가 **같은 queryKey(`epoch-companies`)** 를 쓰므로 react-query 가 묶어
//     실제 fetch 는 여전히 1회다. 쪼갠 대가로 요청이 늘지 않는다.
//   패널 컴포넌트는 `panel.tsx` 로 빼서 둘이 공유한다.
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


type Tab = "companies" | "chips" | "datacenters";
const TABS: { key: Tab; label: string }[] = [
  { key: "companies", label: "AI 기업" },
  { key: "chips", label: "칩 공급" },
  { key: "datacenters", label: "데이터센터" },
];



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
  // ★★2026-08-31 사용자 지시 — **끝난 분기까지만 그린다.**
  //   진행 중 분기는 제조사 한 곳만 보고돼 있기 십상이다(2026Q3 실측: Nvidia 1.18M 뿐이고
  //   Google·AMD 는 0). 그대로 그리면 직전 분기 4.54M 대비 74% 급감으로 읽히는데, 줄어든 게
  //   아니라 아직 안 들어온 것이다. 경계는 서버가 준다(`last_complete_quarter`).
  //   ⚠️`mapChipsCumulative` 에는 적용하지 않는다 — 누적에서 자르면 부분 관측분이 통째로
  //     빠져 Nvidia 누적이 5% 과소계상된다(collector 쪽 주석의 실측 근거).
  const cut = d.last_complete_quarter;
  const n = cut ? d.quarters.filter((q) => q <= cut).length : d.quarters.length;
  const quarters = d.quarters.slice(0, n);
  return [...d.designers]
    .sort((a, b) => b.stats.flow_last - a.stats.flow_last)
    .map((des) => ({
      key: des.key,
      label: des.name,
      // API 의 kind:"bar" 는 이 레포 컨벤션에 없다 — 가장 가까운 시각 표현인
      // step 으로 대체한다(분기 신규분을 다음 분기까지 값으로 유지해 보여준다).
      kind: "step" as const,
      last: des.stats.flow_last,
      points: quarters.map((q, i) => [q, des.flow[i] ?? null] as [string, number | null]),
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
  const { zoomed, toggle, zoomCls } = useCardZoom();
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
    <section
      className={cn(
        zoomCls,
        "lg:col-span-3 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas",
      )}
    >
      {/* 제목 띠 강조색(ge-header) — 2026-08-28 사용자 지시로 페이지 카드가 전부 같은 색. */}
      <header className="flex items-center gap-2 rounded-t-xl bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">Epoch AI</h2>
        <TabChips tabs={TABS} value={tab} onChange={setTab} />
        <span className="ml-auto shrink-0 text-[12px] text-white/60">
          {active.data?.source?.license ?? "CC BY 4.0 — Epoch AI"}
        </span>
      <ZoomButton zoomed={zoomed} onToggle={toggle} />
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-1 p-1.5 pt-1">
        {active.isLoading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[13.5px] font-semibold text-ink-muted">
            불러오는 중…
          </div>
        ) : active.isError ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[13.5px] font-semibold text-rose-600">
            collector 에 못 닿았습니다.
          </div>
        ) : (
          <div
            className={cn(
              "grid min-h-0 flex-1 grid-cols-1 gap-1.5",
              // 데이터센터만 패널 3개 — 2열로 두면 셋째가 아래로 접혀 칸을 넘친다.
              // 데이터센터 3장 / 칩 2장 / 기업은 매출 한 장(펀딩이 빠져 1열).
              tab === "datacenters"
                ? "md:grid-cols-3"
                : tab === "chips"
                  ? "md:grid-cols-2"
                  : "md:grid-cols-1",
            )}
          >
            {tab === "companies" ? (
              // ★2026-08-31 펀딩 라운드는 여기서 빠졌다 — 사용자 지시로 [Demand] 분류의
              //   `EpochFundingCard` 로 이사했다(같은 queryKey 라 fetch 는 여전히 1회).
              <Panel title="매출(연환산)" series={mapRevenue(compQ.data)} />
            ) : tab === "chips" ? (
              <>
                <Panel title="H100e 누적(설계사별)" series={mapChipsCumulative(chipQ.data)} />
                <Panel
                  title={`분기 신규(설계사별) · ${chipQ.data?.last_complete_quarter ?? "-"} 까지`}
                  series={mapChipsFlow(chipQ.data)}
                />
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
          <div className="shrink-0 truncate px-1 text-[12px] font-semibold text-amber-600">
            {active.data.note}
          </div>
        ) : null}
      </div>
    </section>
  );
}
