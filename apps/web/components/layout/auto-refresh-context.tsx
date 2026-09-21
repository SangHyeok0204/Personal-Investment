"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { runQuickSync } from "@/lib/api";

// 자동 갱신.
//
// ★2026-09-21 사용자 요청: "5초마다 데이터 불러오고 계좌 잔고도 업데이트,
//   노트북에 무리 가지 않는 선에서."
//
// 세 가지가 돈다:
//
//   ① 화면 갱신 (우리 API 읽기) — 5초. 로컬 Postgres 읽기라 가볍다.
//   ② 보유 종목 시세 (/portfolio/quotes) — 5초. 야후에서 받고 서버에 4초 캐시.
//      실측 17종목 0.60초.
//   ③ 증권사 잔고 동기화 (/sync/quick) — 5초. ★2026-09-22 사용자 요청으로
//      30초에서 내렸다. 실측 1.6초 / 키움 TR 4개 → 분당 48회, 듀티 사이클 32%.
//      5회 연속(간격 2.6초, 요청 주기보다 빠름) 호출에도 유량 에러가 없었다.
//
// ⚠️5초 주기에서는 **실패 시 백오프가 필수**다. 유량제한(1700~1702)이나 IP 차단에
//   걸린 상태로 5초마다 계속 때리면 차단이 풀리지 않고, 로그만 쌓인다.
//   실패하면 5→10→20→40→60초로 물러났다가 성공하면 즉시 원래 주기로 돌아온다.
//
// ⚠️전체 동기화(/sync, 체결·배당 포함 2분)는 **자동으로 돌리지 않는다.** 그 값들은
//   몇 초마다 바뀌지 않는다. 필요할 때 연동 팝업에서 수동으로 돌린다.
//
// 멈추는 조건(노트북 부담을 줄이는 핵심):
//   · 탭이 보이지 않으면 멈춘다(다른 창을 보는 동안 배터리를 쓰지 않는다).
//   · 장이 열려 있지 않으면 증권사 동기화를 건너뛴다(가격이 안 움직인다).
//   · 사용자가 끄면 둘 다 멈춘다. 선택은 이 브라우저에 기억된다.

const VIEW_REFRESH_MS = 5_000;
const BROKER_SYNC_MS = 5_000;
// 실패가 이어질 때 물러나는 한계. 60초를 넘기면 "멈춘 것"과 구분이 안 된다.
const MAX_BACKOFF_MS = 60_000;
const STORAGE_KEY = "pi:auto-refresh";

type AutoRefreshCtx = {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  /** 화면 갱신 주기(ms). 꺼져 있으면 false — react-query 가 폴링을 멈춘다. */
  viewInterval: number | false;
  syncing: boolean;
  lastSyncAt: Date | null;
  lastError: string | null;
  /** 연속 실패로 물러나 있는 중이면 다음 시도까지 남은 ms. 아니면 0. */
  backoffRemainingMs: number;
  syncNow: () => void;
};

const Ctx = createContext<AutoRefreshCtx | null>(null);

/** KRX/미국장 둘 다 닫혀 있으면 증권사를 부르지 않는다. */
function marketLikelyOpen(now: Date): boolean {
  const day = now.getDay();
  if (day === 0 || day === 6) return false;
  const mins = now.getHours() * 60 + now.getMinutes();
  const krx = mins >= 540 && mins < 930; // 09:00~15:30 KST
  // 미국 정규장은 KST 23:30~06:00(서머타임 22:30~05:00). 넉넉히 잡는다 —
  // 조금 더 도는 건 괜찮지만 장중에 안 도는 건 곤란하다.
  const us = mins >= 1350 || mins < 380;
  return krx || us;
}

export function AutoRefreshProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [enabled, setEnabledState] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState<Date | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  // 동기화가 겹치지 않게 한다 — 앞의 호출이 느리면 큐가 쌓인다.
  //   5초 주기 + 실측 1.6초라 평소엔 겹치지 않지만, 증권사가 느려지면 겹친다.
  const inFlight = useRef(false);
  // 연속 실패 시 다음 시도 시각. 성공하면 0 으로 되돌린다.
  const nextAllowedAt = useRef(0);
  const backoffMs = useRef(0);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved != null) setEnabledState(saved === "1");
    } catch {
      // 프라이빗 모드 등에서 접근이 막힐 수 있다 — 기본값으로 둔다.
    }
  }, []);

  const setEnabled = useCallback((value: boolean) => {
    setEnabledState(value);
    try {
      window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
    } catch {
      /* 저장 못 해도 이번 세션에는 적용된다 */
    }
  }, []);

  const syncNow = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSyncing(true);
    runQuickSync()
      .then(() => {
        setLastSyncAt(new Date());
        setLastError(null);
        // 성공하면 즉시 원래 주기로 복귀한다 — 한 번 실패했다고 계속 느리면 안 된다.
        backoffMs.current = 0;
        nextAllowedAt.current = 0;
        void queryClient.invalidateQueries();
      })
      .catch((err: unknown) => {
        setLastError(err instanceof Error ? err.message : "동기화 실패");
        // 5 → 10 → 20 → 40 → 60초. 유량제한·IP 차단을 5초마다 때리지 않기 위해서다.
        backoffMs.current = Math.min(
          backoffMs.current === 0 ? BROKER_SYNC_MS * 2 : backoffMs.current * 2,
          MAX_BACKOFF_MS,
        );
        nextAllowedAt.current = Date.now() + backoffMs.current;
      })
      .finally(() => {
        inFlight.current = false;
        setSyncing(false);
      });
  }, [queryClient]);

  // 증권사 잔고 동기화 타이머.
  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      if (!marketLikelyOpen(new Date())) return;
      // 백오프 중이면 건너뛴다. 타이머는 계속 돌되 호출만 막는다.
      if (Date.now() < nextAllowedAt.current) return;
      syncNow();
    };
    const id = window.setInterval(tick, BROKER_SYNC_MS);
    return () => window.clearInterval(id);
  }, [enabled, syncNow]);

  const value = useMemo<AutoRefreshCtx>(
    () => ({
      enabled,
      setEnabled,
      viewInterval: enabled ? VIEW_REFRESH_MS : false,
      syncing,
      lastSyncAt,
      lastError,
      backoffRemainingMs: Math.max(0, nextAllowedAt.current - Date.now()),
      syncNow,
    }),
    [enabled, setEnabled, syncing, lastSyncAt, lastError, syncNow],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAutoRefresh(): AutoRefreshCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useAutoRefresh 는 AutoRefreshProvider 안에서만 쓸 수 있다");
  }
  return ctx;
}

/** 화면 쿼리에 붙일 옵션 — 꺼져 있으면 폴링하지 않고, 숨은 탭에서도 멈춘다. */
export function useLiveQueryOptions() {
  const { viewInterval } = useAutoRefresh();
  return {
    refetchInterval: viewInterval,
    // 백그라운드 탭에서는 돌지 않는다 — 노트북 배터리를 쓰지 않기 위해서다.
    refetchIntervalInBackground: false,
  } as const;
}
