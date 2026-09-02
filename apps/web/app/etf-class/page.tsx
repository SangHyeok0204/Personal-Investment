"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  getEtfClass,
  type EtfAxisKey,
  type EtfRow,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { BreakdownCard } from "@/components/etf-class/breakdown-card";
import { FlowCard } from "@/components/etf-class/flow-card";

/* [국내상장 ETF] 분류별 개인 순매수.
 *
 * 무엇을 보는 화면인가: **장 끝나고, 개인 자금이 어느 분류로 몰렸나.**
 * daily_analysis 가 Slack 으로 쏘던 상·하위 10개 발췌를 전수(861종목) · 4계층 분류로 편 것이다.
 * 원천은 운용역이 매일 굽는 워크북 한 장(`국내상장ETF 모니터링.xlsm` value 시트)이고,
 * 분류도 그 시트가 이미 갖고 있다 — 회의에서 쓰는 말과 화면의 말이 갈리면 안 되기 때문이다.
 *
 * ★★2026-09-01 사용자 지시로 카드 여섯 장을 **두 장으로 줄였다**.
 *   · 분류 랭킹 + 자금↔성과 산점도  →  [분류별 개인 순매수] 한 장(좌 목록 + 우 묶음 막대)
 *   · 구간 분해 + 상세 ETF 목록      →  [구간별 개인 순매수 유입] 한 장(두 칸, 스크롤 분리)
 *   · 시점별 추이                    →  제거(collector 적재는 그대로 — 아래 참조)
 *   기간·수익률가중 토글에 이어 **분류 축·금액/강도 토글까지 걷어냈다** — 컨트롤이 없다.
 *   요약 밴드(전체 순매수 · 몰린/빠진 분류 3개씩)도 뺐다 — 바로 아래 목록의 위·아래 끝이
 *   같은 것을 이미 말하고 있어서 화면 위쪽만 차지했다.
 *
 * ★HISTORICAL 은 아래 카드의 구간 분해가 맡는다. 워크북은 매일 덮어써서 과거가 없지만,
 *   1주·1개월·3개월·6개월 **누적**을 같이 주므로 누적끼리 빼면 겹치지 않는 4구간이 나온다.
 * ★collector 는 화면에서 뺀 뒤에도 매일 스냅샷을 sqlite 에 쌓는다. 지금 안 쌓으면 그
 *   날짜는 영영 복구할 수 없어서다(워크북이 덮어쓰기다). 다시 그릴 일이 생기면
 *   `/api/v1/etf-class/history` 에 클라이언트만 붙이면 된다.
 */

const REFETCH = 600_000; // 10분 — 하루 한 번 갱신되는 워크북이라 더 자주 볼 이유가 없다

// ETF → 분류 키 조인. ★규칙을 여기에 두지 않는다 — 서버가 **실제로 넣은 묶음의 키**를
//   `gkeys` 로 실어 보내고 화면은 자리(AXES 순서)만 안다. 프런트가 규칙을 한 벌 더 가지면
//   표기 접기(`Top10`/`TOP10`) 같은 게 들어올 때 갈리고, 갈리면 상세 표가 비어 오진된다.
const AXIS_ORDER: EtfAxisKey[] = ["gubun", "big", "mid", "small", "country"];

function etfGroupKey(e: EtfRow, axis: EtfAxisKey): string {
  return e.gkeys?.[AXIS_ORDER.indexOf(axis)] ?? "";
}

export default function EtfClassPage() {
  // ★2026-09-01 사용자 지시로 분류 축·기준 토글을 걷어냈다. 축은 **중분류** 고정 —
  //   88개로 회의에서 쓰는 단위이고, 구분(2개)은 너무 굵고 소분류(206개)는 너무 잘다.
  //   다른 축이나 '강도(시총 대비)' 로 볼 일이 생기면 서버 payload 에 다 실려 있으니
  //   여기서 axis 를 바꾸거나 토글을 되살리면 된다(groups 는 5축을 전부 담고 온다).
  const axis: EtfAxisKey = "mid";
  const [picked, setPicked] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["etf-class"],
    queryFn: getEtfClass,
    refetchInterval: REFETCH,
  });

  const rows = data?.groups?.[axis] ?? [];

  // 고른 분류가 지금 축에 없으면(축을 바꾼 직후) 어제 유입 1위로 떨어진다.
  const selected = useMemo(() => {
    if (picked && rows.some((r) => r.key === picked)) return picked;
    const top = [...rows].sort(
      (a, b) => (b.net_cum.d ?? 0) - (a.net_cum.d ?? 0),
    )[0];
    return top?.key ?? null;
  }, [picked, rows]);

  const selectedRow = rows.find((r) => r.key === selected) ?? null;
  const detailEtfs = useMemo(
    () =>
      selected
        ? (data?.etfs ?? []).filter((e) => etfGroupKey(e, axis) === selected)
        : [],
    [data, axis, selected],
  );

  return (
    <>
      <Topbar
        title="국내상장 ETF"
        subtitle={
          data?.asof
            ? `분류별 개인 순매수 · 기준일 ${data.asof} · ${data.etfs.length}종목`
            : "분류별 개인 순매수"
        }
        status={
          data?.source_modified ? (
            <span className="text-[11.5px] font-semibold text-ink-faint">
              워크북 {data.source_modified}
            </span>
          ) : undefined
        }
      />

      <div className="min-h-screen bg-canvas-soft px-5 py-4">
        {error && (
          <div className="mb-3">
            <ApiErrorBanner error={error} />
          </div>
        )}
        {data?.note && (
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <p className="text-[12.5px] font-semibold text-amber-900">{data.note}</p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-[470px]" />
            <Skeleton className="h-[470px]" />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="h-[470px]">
              <FlowCard
                rows={rows}
                periods={data?.periods ?? []}
                allEtfs={data?.etfs ?? []}
                selected={selected}
                onSelect={setPicked}
                asof={data?.asof ?? null}
              />
            </div>
            <div className="h-[470px]">
              <BreakdownCard
                rows={rows}
                intervals={data?.intervals ?? []}
                selected={selected}
                onSelect={setPicked}
                selectedRow={selectedRow}
                etfs={detailEtfs}
              />
            </div>

            {/* ★숫자의 뜻을 화면에 적어 둔다 — 회의에서 "이 순매수가 뭐냐"가 나오면
                그 자리에서 답이 되어야 한다. */}
            <p className="px-1 pb-2 text-[11px] leading-relaxed text-ink-faint">
              원천은 워크북 <b>국내상장ETF 모니터링.xlsm</b> 의 value 시트다. 순매수는{" "}
              <b>개인</b> 투자자 순매수(억원)이고, 기간 값은 그 창의 일별 합계다. 위 카드의
              막대는 <b>거래일당 평균</b>(총액 ÷ 창 안의 거래일 수, 주말 제외·공휴일 미반영)
              이고 총액은 막대에 마우스를 올리면 나온다. 아래 표의 4구간은 서로 겹치지 않게
              누적끼리 뺀 값이라 합이 6개월 유입액과 같다. 레버리지·인버스 ETF 도 분류에
              그대로 들어 있다.
              {data?.masked_returns ? (
                <>
                  {" "}
                  창이 시작될 때 아직 상장되지 않았거나 시세가 멈춘 종목의 기간 수익률{" "}
                  <b>{data.masked_returns}건</b>은 워크북이 0% 로 주는데, 그대로 쓰면
                  &ldquo;그 기간 0% 였다&rdquo;가 되므로 평균에서 <b>제외</b>했다.
                </>
              ) : null}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
