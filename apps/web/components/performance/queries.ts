"use client";

import { useQuery } from "@tanstack/react-query";
import { useAccount } from "@/components/layout/account-context";
import { useLiveQueryOptions } from "@/components/layout/auto-refresh-context";
import {
  getAccountReturn,
  getBenchmark,
  getPerformance,
  getPerformanceAnalytics,
} from "@/lib/api";

// 성과 분석 화면의 공용 조회.
//
// ★2026-10-15 한 화면 통합: 여러 섹션이 같은 데이터를 본다(예: 내 계좌 수익률은 요약 타일 ·
//   수익률 추이 · 기간 리포트가 같이 쓴다). react-query 는 **queryKey 가 같으면 한 번만**
//   부른다 — 그래서 키와 옵션을 여기 한 곳에서 정한다. 섹션마다 옵션을 따로 적으면
//   같은 키에 갱신 주기가 섞인다.
//   키는 옛 화면 그대로다(다른 화면의 캐시와도 겹친다).
//
// ⚠️옛 화면들의 옵션이 서로 달랐다 — 수익률 추이·기간 리포트는 staleTime 60초,
//   성과 분석은 자동 갱신(live). 같은 키를 한 화면에서 같이 쓰므로 하나로 맞춘다:
//   일별 시계열(/performance)·벤치마크는 옛 staleTime 을, 계좌 수익률·성과분석은
//   옛 성과 분석 화면처럼 live 를 따른다(장중 첫 칸이 live 로 움직인다).

/** 일별 성과(예탁자산 · 주가 손익 · 다리 분해). 늘 시작일부터 받는다. */
export function usePerformanceSeries() {
  const { accountId } = useAccount();
  // ★2026-10-05 늘 시작일부터 받는다(서버가 INVESTMENT_START 아래로 내려가지 않는다).
  //   기간 칩은 화면에서 선 그래프만 자른다.
  return useQuery({
    queryKey: ["performance", accountId, "since-start"],
    queryFn: () => getPerformance(accountId, 3650),
    staleTime: 60_000,
  });
}

/** 내 계좌 수익률(정본) — 시작일 이후 손익 ÷ 투입 원금. */
export function useAccountReturn() {
  const { accountId } = useAccount();
  // ⚠️5초 실시간 갱신을 걸지 않는다(옛 수익률 추이·기간 리포트와 같이 60초 캐시). 이 API 는 10년치 손익
  //   분해를 다시 계산해 무겁고, 요약 타일의 다른 칸(주가 손익·환율 등)은 실시간이 아니라 섞이면 서로 어긋난다.
  return useQuery({
    queryKey: ["account-return", accountId],
    queryFn: () => getAccountReturn(accountId),
    staleTime: 60_000,
  });
}

/** 벤치마크(S&P 500) — 시작일 이후 누적 · 기간별 · 월별 시계열. */
export function useBenchmark() {
  const { accountId } = useAccount();
  return useQuery({
    queryKey: ["benchmark", accountId],
    queryFn: () => getBenchmark(accountId),
    staleTime: 10 * 60_000,
  });
}

/** 성과분석 — 참고 TWR 기간 · 위험지표 · 월별 · 낙폭 · 종목 기여도. */
export function useAnalytics() {
  const { accountId } = useAccount();
  const live = useLiveQueryOptions();
  return useQuery({
    queryKey: ["performance-analytics", accountId],
    queryFn: () => getPerformanceAnalytics(accountId),
    ...live,
  });
}
