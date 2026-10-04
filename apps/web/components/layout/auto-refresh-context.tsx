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
import { getFreshness, runHistorySync, runQuickSync } from "@/lib/api";

// 자동 갱신.
//
// ★2026-09-21 사용자 요청: "5초마다 데이터 불러오고 계좌 잔고도 업데이트,
//   노트북에 무리 가지 않는 선에서."
//
// 네 가지가 돈다:
//
//   ① 화면 갱신 (우리 API 읽기) — 5초. 로컬 Postgres 읽기라 가볍다.
//   ② 보유 종목 시세 (/portfolio/quotes) — 5초. 야후에서 받고 서버에 4초 캐시.
//      실측 17종목 0.60초.
//   ③ 증권사 잔고 동기화 (/sync/quick) — 5초. ★2026-09-22 사용자 요청으로
//      30초에서 내렸다. 실측 1.6초 / 키움 TR 4개 → 분당 48회, 듀티 사이클 32%.
//      5회 연속(간격 2.6초, 요청 주기보다 빠름) 호출에도 유량 에러가 없었다.
//   ④ 이력 동기화 (/sync) — 10분마다 **뒤처졌는지만** 묻고, 뒤처졌을 때만 돈다.
//      실행 자체는 2분 걸리므로 성공·실패 무관 1시간은 다시 시도하지 않는다.
//
// ⚠️5초 주기에서는 **실패 시 백오프가 필수**다. 유량제한(1700~1702)이나 IP 차단에
//   걸린 상태로 5초마다 계속 때리면 차단이 풀리지 않고, 로그만 쌓인다.
//   실패하면 5→10→20→40→60초로 물러났다가 성공하면 즉시 원래 주기로 돌아온다.
//
// ⚠️전체 동기화(/sync, 체결·배당 포함 2분)는 **주기로 돌리지 않는다.** 그 값들은
//   몇 초마다 바뀌지 않는다. 대신 10분마다 freshness 만 묻고(조회 한 번),
//   "마지막 동기화 이후 정규장이 닫힌 적이 있다"고 할 때만 실행한다. 한 번
//   시도하면 성공하든 실패하든 1시간은 쉰다. 수동 실행은 [수집 상태] 화면에 있다.
//   ★2026-09-23: 예전에는 정말로 수동뿐이었다. 자동 게이트가 생긴 뒤에도 이
//     주석이 "자동으로 돌리지 않는다"로 남아 있어, 화면이 아니라 **주석이**
//     사실과 다른 말을 하고 있었다.
//
// 멈추는 조건(노트북 부담을 줄이는 핵심):
//   · 탭이 보이지 않으면 멈춘다(다른 창을 보는 동안 배터리를 쓰지 않는다).
//   · 장이 열려 있지 않으면 증권사 동기화를 건너뛴다(가격이 안 움직인다).
//   · 사용자가 끄면 둘 다 멈춘다. 선택은 이 브라우저에 기억된다.

const VIEW_REFRESH_MS = 5_000;
const BROKER_SYNC_MS = 5_000;
// 장이 닫혀 있는 동안의 화면 갱신 주기.
// ★5초를 늦추는 게 아니다 — **바뀔 수 없는 값을 계속 묻지 않는 것**이다.
//   장 마감 후 시세는 다음 개장까지 16:00 ET 종가에 고정돼 있고(토스·야후 둘 다
//   시간외 체결을 주지 않는 것을 실측으로 확인했다), 증권사 동기화도 이미
//   장중에만 돈다. 그런데 시세 폴링만 24시간 5초로 돌고 있었다.
//   개장하면 자동으로 5초로 돌아온다.
const CLOSED_REFRESH_MS = 60_000;
// 실패가 이어질 때 물러나는 한계. 60초를 넘기면 "멈춘 것"과 구분이 안 된다.
const MAX_BACKOFF_MS = 60_000;

// 이력이 뒤처졌는지 확인하는 주기와, 한 번 시도한 뒤 다시 시도하기까지의 간격.
// ⚠️확인은 가볍지만(조회 한 번) 실제 동기화는 40초쯤 걸리고 TR 을 여러 번
//   부른다 — 확인은 자주, 시도는 드물게.
const HISTORY_CHECK_MS = 10 * 60_000;
const HISTORY_RETRY_MS = 60 * 60_000;

// ⚠️툴팁 문구를 손으로 적지 않는다. 사용자 요청으로 증권사 동기화를 30초 → 5초로
//   내렸을 때 **상단바 툴팁만 30초로 남아** 화면이 사실과 다른 말을 했다.
//   주기를 바꾸면 문구도 같이 바뀌도록 상수에서 만든다.
export const AUTO_REFRESH_LABEL =
  `자동 갱신 켜짐 — 화면 ${VIEW_REFRESH_MS / 1000}초, ` +
  `증권사 잔고 ${BROKER_SYNC_MS / 1000}초(장중·이 탭이 보일 때만). ` +
  `장 마감 중에는 ${CLOSED_REFRESH_MS / 1000}초로 늦춥니다. ` +
  `체결·배당 등 이력은 뒤처졌을 때만 ${HISTORY_RETRY_MS / 60000}분에 한 번 받아옵니다.`;
const STORAGE_KEY = "pi:auto-refresh";

type AutoRefreshCtx = {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  /** 화면 갱신 주기(ms). 꺼져 있으면 false — react-query 가 폴링을 멈춘다.
   *  장이 닫혀 있으면 느려진다(바뀔 수 없는 값을 묻지 않는다). */
  viewInterval: number | false;
  /** 지금 장이 열려 있다고 보는가. 화면이 "왜 안 움직이지"에 답할 수 있게 노출한다. */
  marketOpen: boolean;
  syncing: boolean;
  lastSyncAt: Date | null;
  lastError: string | null;
  /** 연속 실패로 물러나 있는 중이면 다음 시도까지 남은 ms. 아니면 0. */
  backoffRemainingMs: number;
  syncNow: () => void;
};

const Ctx = createContext<AutoRefreshCtx | null>(null);

/** 브라우저 로컬 시각을 특정 타임존의 (요일, 분) 으로 바꾼다.
 *
 * ⚠️`getHours()` 는 **사용자 PC 의 시간대**다. 시장 시간을 그걸로 따지면
 *   여행 중이거나 시간대를 바꿔 둔 PC 에서 통째로 틀린다.
 */
function inZone(now: Date, timeZone: string): { day: number; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(
    get("weekday"),
  );
  // 자정은 "24" 로 오는 구현이 있다.
  const hour = Number(get("hour")) % 24;
  return { day: weekday, minutes: hour * 60 + Number(get("minute")) };
}

/** KRX/미국장 둘 다 닫혀 있으면 증권사도, 시세도 부르지 않는다.
 *
 * ★각 시장의 **현지 시각**으로 따진다(2026-09-22 수정). 전에는 KST 분 범위를
 *   "넉넉히" 잡아 06:20 까지 개장으로 봤는데, 그 때문에 미국장이 ET 16:00 에
 *   닫힌 뒤로도 80분을 더 5초마다 시세를 물었다. 서버의 판정
 *   (`us_regular_session_open`, ET 기준)과도 어긋나 있었다 — 같은 질문에
 *   두 답이 나오면 어느 쪽을 믿어야 할지 알 수 없다.
 *
 * ★현지 시각으로 따지면 **서머타임이 저절로 맞는다.** 전에는 "서머타임 22:30"
 *   이라고 주석만 달고 고정 범위를 썼다.
 *
 * ⚠️공휴일은 보지 않는다. 휴장일에 몇 번 더 물어보는 건 값이 안 변할 뿐
 *   틀리지는 않는다 — 휴장일 달력을 들고 있을 만한 이득이 아니다.
 */
function marketLikelyOpen(now: Date): boolean {
  const us = inZone(now, "America/New_York");
  const kr = inZone(now, "Asia/Seoul");
  const weekday = (z: { day: number }) => z.day >= 1 && z.day <= 5;

  // 미국 정규장 09:30~16:00 ET. 앞뒤로 5분씩만 여유를 둔다.
  const usOpen =
    weekday(us) && us.minutes >= 9 * 60 + 25 && us.minutes < 16 * 60 + 5;
  // KRX 09:00~15:30 KST.
  const krOpen =
    weekday(kr) && kr.minutes >= 8 * 60 + 55 && kr.minutes < 15 * 60 + 35;
  return usOpen || krOpen;
}

export function AutoRefreshProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [enabled, setEnabledState] = useState(true);
  // ⚠️저장된 설정을 읽기 **전에는** 아무 동기화도 시작하지 않는다. 안 그러면 첫 렌더의 기본값(켜짐)으로
  //   이력 동기화가 한 번 나간다 — 꺼 둔 사용자도 페이지를 열 때마다 키움을 부른다(실측 2026-10-04).
  const [prefLoaded, setPrefLoaded] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState<Date | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  // 장 개폐는 분 단위로만 바뀐다. 1분마다 다시 보면 충분하고, 개장 직후
  // 늦어도 1분 안에 5초 주기로 돌아온다.
  const [marketOpen, setMarketOpen] = useState(() => marketLikelyOpen(new Date()));
  useEffect(() => {
    const id = window.setInterval(
      () => setMarketOpen(marketLikelyOpen(new Date())),
      60_000,
    );
    return () => window.clearInterval(id);
  }, []);

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
    setPrefLoaded(true);
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

  // ── 이력 동기화 (체결·배당·주문·일별성과) ────────────────────────────
  //
  // ★2026-09-22: 잔고는 5초마다 자동인데 **이력은 아무도 안 돌렸다.** 그래서
  //   체결 원장이 2일 밀린 걸 며칠 뒤에야 발견했고, 그동안 수수료/세금·편입비·
  //   매매일지가 옛 것을 보여 주고 있었다.
  //
  // ⚠️**시간으로 판정하지 않는다.** 주말에는 사흘이 지나도 받을 게 없고 장
  //   마감 직후에는 한 시간만 지나도 받을 게 있다. 서버가 '마지막 동기화 이후
  //   정규장이 닫혔는가'로 판정해 준 값을 그대로 쓴다.
  //
  // ⚠️한 번 돌리는 데 40초쯤 걸리고 증권사 TR 을 여러 번 부른다. 그래서
  //   ① 탭이 보일 때만 ② 자동 갱신이 켜져 있을 때만 ③ **한 시간에 한 번만**
  //   시도한다. 실패해도 조용히 넘어간다 — 화면(수집 상태)이 상태를 말한다.
  //
  // ⚠️증권사 배치 시간(KST 05~07시)에는 이력이 비어서 오므로 건드리지 않는다.
  const historyInFlight = useRef(false);
  const historyNextAt = useRef(0);

  useEffect(() => {
    if (!prefLoaded || !enabled) return;
    const tick = async () => {
      if (document.visibilityState !== "visible") return;
      if (historyInFlight.current) return;
      if (Date.now() < historyNextAt.current) return;

      const kst = inZone(new Date(), "Asia/Seoul");
      if (kst.minutes >= 5 * 60 && kst.minutes < 7 * 60) return;

      historyInFlight.current = true;
      // 성공하든 실패하든 한 시간은 다시 시도하지 않는다.
      historyNextAt.current = Date.now() + HISTORY_RETRY_MS;
      try {
        const fresh = await getFreshness();
        if (fresh.stale) {
          await runHistorySync();
          void queryClient.invalidateQueries();
        }
      } catch {
        /* 실패는 수집 상태 화면이 보여 준다 — 여기서 시끄럽게 하지 않는다 */
      } finally {
        historyInFlight.current = false;
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), HISTORY_CHECK_MS);
    return () => window.clearInterval(id);
  }, [prefLoaded, enabled, queryClient]);

  // 증권사 잔고 동기화 타이머.
  useEffect(() => {
    if (!prefLoaded || !enabled) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      if (!marketLikelyOpen(new Date())) return;
      // 백오프 중이면 건너뛴다. 타이머는 계속 돌되 호출만 막는다.
      if (Date.now() < nextAllowedAt.current) return;
      syncNow();
    };
    const id = window.setInterval(tick, BROKER_SYNC_MS);
    return () => window.clearInterval(id);
  }, [prefLoaded, enabled, syncNow]);

  const value = useMemo<AutoRefreshCtx>(
    () => ({
      enabled,
      setEnabled,
      viewInterval: enabled
        ? marketOpen
          ? VIEW_REFRESH_MS
          : CLOSED_REFRESH_MS
        : false,
      marketOpen,
      syncing,
      lastSyncAt,
      lastError,
      backoffRemainingMs: Math.max(0, nextAllowedAt.current - Date.now()),
      syncNow,
    }),
    [enabled, marketOpen, setEnabled, syncing, lastSyncAt, lastError, syncNow],
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
