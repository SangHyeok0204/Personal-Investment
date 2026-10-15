"use client";

import { useMemo } from "react";
import { SeriesChart } from "@/components/charts/series-chart";
import { CardEmpty, StubCard } from "@/components/stub";
import { pct } from "./format";
import { useAnalytics } from "./queries";

// 5. 낙폭(Drawdown) 추이 — 옛 성과 분석 왼쪽 그래프의 '낙폭(참고 TWR)' 보기.
//
// ★2026-10-15 한 화면 통합: 옛 화면은 수익률/낙폭을 한 카드에서 토글했다. 수익률 쪽은
//   위 '수익률 추이' 섹션과 같은 그래프라 걷었고, 낙폭만 섹션으로 꺼냈다.
//   옛 /performance/risk 스텁(낙폭·집중도 골격만 있던 화면)도 여기로 보낸다.

export function DrawdownSection() {
  const analytics = useAnalytics();
  const data = analytics.data;
  const points = useMemo(
    () =>
      (data?.drawdown ?? []).map((d) => ({
        date: d.base_date,
        value: Number(d.drawdown) * 100,
      })),
    [data],
  );
  const worst = data?.risk.find((r) => r.label === "전체");

  return (
    <section id="drawdown" className="scroll-mt-28">
      <StubCard
        title="낙폭(Drawdown) 추이"
        subtitle={
          worst?.max_drawdown
            ? `참고: 시간가중(TWR) · 최대 ${pct(worst.max_drawdown)} (${worst.max_drawdown_trough_date})`
            : "참고: 시간가중(TWR)"
        }
      >
        {analytics.isLoading ? (
          <div className="h-[220px]">
            <CardEmpty text="불러오는 중…" />
          </div>
        ) : points.length === 0 ? (
          <div className="h-[220px]">
            <CardEmpty text="일별 수익률이 없습니다" />
          </div>
        ) : (
          <>
            {/* 낙폭은 항상 0 이하 — 0 을 축에 포함해야 '얼마나 빠졌는지'가 읽힌다. */}
            <SeriesChart
              points={points}
              height={220}
              includeZero
              valueFormat={(v) => `${v.toFixed(0)}%`}
              tooltipFormat={(p) => `${p.date} · ${p.value == null ? "—" : `${p.value.toFixed(2)}%`}`}
            />
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              고점 대비 하락률 · 입출금 제외
            </p>
          </>
        )}
      </StubCard>
    </section>
  );
}
