"use client";

import { useQuery } from "@tanstack/react-query";
import { getIndexAlerts, type IndexAlertItem } from "@/lib/api";

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
