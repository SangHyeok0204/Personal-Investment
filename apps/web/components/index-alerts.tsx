"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getIndexAlerts,
  getIndexWindow,
  type IndexAlertItem,
  type IndexWindowEntry,
} from "@/lib/api";

/* ── 지수 급등락 하루 알림 (서버측) ──────────────────────────────────────
   ★ 2026-07-27: 브라우저별 발화·누적(localStorage)을 폐기하고 **collector 서버가**
   INDEX_MONITOR 전일 이력을 스캔해 계산·보관하는 하루 로그(/index-alerts)를 그대로
   받는다. 이러면 어느 컴퓨터가 언제 켜져 있었든 모든 클라이언트가 **동일한 목록**을
   보고, 늦게 접속해도 오늘 발화분 전체가 소급 표시된다. 판정 로직(08:55~16:00,
   60분 변동폭 ≥2%p 크로싱 + 09:05 갭)은 collector.index_window.build_index_alerts 참조.
   표시는 useIndexAlerts()를 쓰는 쪽(iNAV AlertBar 3번째 줄)이 담당(지수별 최신 1건). */

export type IndexAlert = IndexAlertItem;

export function useIndexAlerts(): { alerts: IndexAlert[] } {
  const { data } = useQuery({
    queryKey: ["indexAlerts"],
    queryFn: getIndexAlerts,
    refetchInterval: 20_000,
    retry: false,
  });
  return { alerts: data?.alerts ?? [] };
}

/* ── 지수 실시간 등락률 ────────────────────────────────────────────────────
   ★ 2026-08-14: 급등락은 '있을 때만' 뜨는 값이라 평소엔 줄이 비어 있었다. 상시
   보이는 실시간 등락률(전일 종가 대비)을 같은 소스에서 가져와 앞자리에 세운다.
   /index-window 의 latest_pct 가 그 값 — 급등락 판정(spread_pct)과 같은 틱을
   보므로 두 값이 어긋나지 않는다. CHECK 적재가 분단위라 20초 폴링이면 충분하다. */
export type IndexLive = IndexWindowEntry;

export function useIndexLive(): { indices: IndexLive[] } {
  const { data } = useQuery({
    queryKey: ["indexWindow"],
    queryFn: getIndexWindow,
    refetchInterval: 20_000,
    retry: false,
  });
  return { indices: data?.indices ?? [] };
}
