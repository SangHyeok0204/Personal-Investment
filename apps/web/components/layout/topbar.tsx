"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Bell,
  ChevronDown,
  CircleHelp,
  Menu,
  RefreshCw,
  Search,
  Wallet,
} from "lucide-react";
import { useSidebar } from "@/components/layout/sidebar-context";
import { ALL_ACCOUNTS, useAccount } from "@/components/layout/account-context";
import { useConnectDialog } from "@/components/brokerage/connect-context";
import {
  AUTO_REFRESH_LABEL,
  useAutoRefresh,
} from "@/components/layout/auto-refresh-context";
import Link from "next/link";
import { ackOpsAlert, getAlerts, runBrokerageSync } from "@/lib/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

/**
 * 모든 화면이 공유하는 상단 바. 껍데기(높이·구분선·전역 아이콘)는 공통이고
 * 제목/상태/액션은 각 페이지가 넣는다.
 *
 * ★2026-09-21 개조: 개인 계좌 기준 대시보드로 바꾸면서 상단 바에 **계좌 컨텍스트**를
 *   추가했다. 어느 화면을 보든 "지금 어느 계좌를, 장중에 보고 있는가"가 안 보이면
 *   숫자를 잘못 읽는다. 기존 페이지 19장은 props 를 안 고쳐도 그대로 동작한다
 *   (계좌 칩·장 상태·동기화 표시는 기본값으로 켜지고, 전부 아직 더미다).
 */

/** KRX 정규장(09:00~15:30) 기준 장 상태. 휴장일은 아직 반영하지 않는다. */
function useMarketSession() {
  const [state, setState] = useState<{ label: string; tone: string } | null>(
    null,
  );

  // ⚠️서버에서 계산하면 안 된다 — 서버/클라이언트 시각이 달라 hydration 이 깨진다.
  //   마운트 후에만 켜고, 그전엔 null 을 렌더한다.
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const day = now.getDay();
      const mins = now.getHours() * 60 + now.getMinutes();
      if (day === 0 || day === 6) {
        setState({ label: "휴장", tone: "bg-slate-300" });
      } else if (mins >= 540 && mins < 930) {
        setState({ label: "장중", tone: "bg-status-success" });
      } else if (mins >= 480 && mins < 540) {
        setState({ label: "장 시작 전", tone: "bg-amber-400" });
      } else {
        setState({ label: "장 마감", tone: "bg-slate-300" });
      }
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, []);

  return state;
}

export function Topbar({
  title,
  subtitle,
  status,
  actions,
  /** 계좌 칩·장 상태·동기화 표시를 숨기고 싶은 화면용(시장 전용 화면 등). */
  showAccountContext = true,
  /** 마지막 동기화 시각. 넘기지 않으면 선택된 계좌(또는 전체 중 최신)에서 읽는다. */
  syncedAt,
  onSync,
}: {
  title: string;
  subtitle?: string;
  status?: ReactNode;
  actions?: ReactNode;
  showAccountContext?: boolean;
  syncedAt?: Date | string | null;
  onSync?: () => void;
}) {
  const { collapsed, toggle } = useSidebar();
  const session = useMarketSession();
  const { accountId, setAccountId, accounts, connected, isError } = useAccount();
  const { open: openConnect } = useConnectDialog();
  const auto = useAutoRefresh();
  const queryClient = useQueryClient();
  // 상단 바 동기화 — 계좌가 이미 있으면 바로 돌리고, 없으면 연동 팝업을 연다.
  const sync = useMutation({
    mutationFn: runBrokerageSync,
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);

  // 클릭으로 여는 메뉴는 **바깥 클릭**으로 닫는다. onMouseLeave 로 닫으면 커서가
  // 잠깐만 벗어나도 사라져서 선택을 못 한다(2026-09-21 에 그렇게 만들었다가 고침).
  useEffect(() => {
    if (!accountOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!accountRef.current?.contains(e.target as Node)) setAccountOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAccountOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [accountOpen]);

  const selected = accounts.find((a) => a.id === accountId) ?? null;
  // 명시적으로 넘긴 값 > 선택 계좌의 동기화 시각 > 전체 계좌 중 가장 최근.
  const lastSynced =
    syncedAt ??
    selected?.last_synced_at ??
    accounts
      .map((a) => a.last_synced_at)
      .filter((v): v is string => v != null)
      .sort()
      .at(-1) ??
    null;
  // 라벨 우선순위: 고른 계좌 이름 → 전체 합산 → (계좌가 없으면) 미연동.
  const accountLabel = selected
    ? (selected.account_name ?? selected.account_number_masked ?? "계좌")
    : connected
      ? "전체 계좌"
      : isError
        ? "API 연결 안 됨"
        : "계좌 미연동";

  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-7">
      <div className="flex min-w-0 items-center gap-5">
        {/* 사이드바 접기/펼치기 — 접으면 본문이 212px 넓어진다(모든 페이지 공통). */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          aria-expanded={!collapsed}
          title={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          className="-m-1.5 shrink-0 rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          <Menu className="h-5 w-5 shrink-0" />
        </button>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold tracking-tight text-slate-900">
            {title}
          </div>
          {subtitle && (
            <div className="truncate text-[11px] text-slate-400">{subtitle}</div>
          )}
        </div>
        {status && <div className="min-w-0">{status}</div>}
      </div>

      <div className="flex shrink-0 items-center gap-4 text-slate-500">
        {actions}

        {showAccountContext && (
          <>
            {/* 장 상태 — 마운트 전에는 자리만 잡아 둔다(레이아웃 점프 방지). */}
            <span className="flex items-center gap-1.5 text-[12px] font-bold text-slate-600">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  session?.tone ?? "bg-slate-200",
                )}
              />
              {session?.label ?? "—"}
            </span>

            {/* 계좌 선택 — 아직 더미 목록이다. 키움 연동 후 실제 계좌로 교체한다. */}
            <div className="relative" ref={accountRef}>
              <button
                type="button"
                onClick={() => setAccountOpen((v) => !v)}
                aria-haspopup="listbox"
                aria-expanded={accountOpen}
                className="flex items-center gap-2 rounded-lg border border-hairline bg-white px-3 py-1.5 text-[12px] font-bold text-ge-navy transition-colors hover:bg-canvas-soft"
              >
                <Wallet
                  className={cn(
                    "h-3.5 w-3.5",
                    connected ? "text-ge-point" : "text-slate-300",
                  )}
                />
                <span className={cn(!connected && "text-ink-muted")}>
                  {accountLabel}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              </button>
              {accountOpen && (
                <div
                  role="listbox"
                  className="absolute right-0 top-full z-50 mt-1.5 min-w-[220px] rounded-xl bg-white p-1.5 shadow-[0_16px_36px_rgba(36,59,94,0.22)] ring-1 ring-hairline"
                >
                  {/* 계좌가 없으면 목록 대신 연동 경로를 안내한다 — 빈 목록은
                      "고를 게 없다"만 말하고 다음 행동을 알려주지 않는다. */}
                  {!connected ? (
                    <div className="px-3 py-3">
                      <p className="text-[12px] font-semibold text-ink-secondary">
                        {isError
                          ? "API 서버에 연결하지 못했습니다."
                          : "연동된 증권사 계좌가 없습니다."}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setAccountOpen(false);
                          openConnect();
                        }}
                        className="mt-2 inline-block rounded-lg border border-hairline bg-white px-3 py-1.5 text-[12px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg"
                      >
                        계좌 연동하기
                      </button>
                    </div>
                  ) : (
                    <>
                      <AccountOption
                        label="전체 계좌"
                        meta="합산"
                        active={accountId === ALL_ACCOUNTS}
                        onSelect={() => {
                          setAccountId(ALL_ACCOUNTS);
                          setAccountOpen(false);
                        }}
                      />
                      {accounts.map((a) => (
                        <AccountOption
                          key={a.id}
                          label={
                            a.account_name ?? a.account_number_masked ?? "계좌"
                          }
                          meta={a.broker_name}
                          active={a.id === accountId}
                          inactive={!a.is_active}
                          onSelect={() => {
                            setAccountId(a.id);
                            setAccountOpen(false);
                          }}
                        />
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>

            {/* 자동 갱신 스위치. 끄면 폴링과 증권사 동기화가 **둘 다** 멈춘다. */}
            <button
              type="button"
              onClick={() => auto.setEnabled(!auto.enabled)}
              aria-pressed={auto.enabled}
              title={
                auto.enabled
                  ? AUTO_REFRESH_LABEL
                  : "자동 갱신 꺼짐"
              }
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-bold transition-colors",
                auto.enabled
                  ? "border-status-success/30 bg-status-success/10 text-status-success"
                  : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  auto.enabled ? "animate-pulse bg-status-success" : "bg-slate-300",
                )}
              />
              {auto.enabled ? "자동" : "수동"}
            </button>

            {/* 동기화 — syncedAt 이 없으면 아직 계좌 API 가 안 붙은 상태다. */}
            <button
              type="button"
              onClick={() => {
                if (onSync) return onSync();
                if (!connected) return openConnect();
                // 가벼운 동기화(잔고·보유, ~1.6초). 이력까지 받는 전체 동기화는
                // 연동 팝업에서 돌린다 — 2분 걸려 버튼 한 번에 붙일 일이 아니다.
                auto.syncNow();
              }}
              disabled={auto.syncing || sync.isPending}
              title={
                !connected
                  ? "계좌를 연동하세요"
                  : auto.lastError
                    ? `잔고 동기화 실패: ${auto.lastError}`
                    : lastSynced
                    ? `마지막 동기화: ${new Date(lastSynced).toLocaleString("ko-KR")} — 눌러서 다시 동기화`
                    : "눌러서 동기화"
              }
              // ⚠️실패를 숨기지 않는다 — 마지막 성공 시각만 띄우면 몇 시간째 멈춘 잔고가 '최신'처럼 보인다
              //   (실측 2026-10-04: 키움 8050 IP 미등록으로 13:14 이후 멈춤).
              className={cn(
                "flex items-center gap-1.5 text-[12px] font-bold transition-colors disabled:cursor-default disabled:text-slate-300",
                auto.lastError && !auto.syncing
                  ? "text-rose-600 hover:text-rose-700"
                  : "text-slate-500 hover:text-slate-700",
              )}
            >
              <RefreshCw
                className={cn(
                  "h-4 w-4",
                  (auto.syncing || sync.isPending) && "animate-spin",
                )}
              />
              {auto.syncing || sync.isPending
                ? "동기화 중"
                : auto.lastError
                  ? "동기화 실패"
                  : auto.lastSyncAt
                  ? auto.lastSyncAt.toLocaleTimeString("ko-KR", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })
                  : lastSynced
                    ? new Date(lastSynced).toLocaleTimeString("ko-KR", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : connected
                      ? "미동기화"
                      : "연동하기"}
            </button>
          </>
        )}

        <Search className="h-5 w-5" />
        <AlertBell />
        <CircleHelp className="h-5 w-5" />
        <div className="flex items-center gap-1.5">
          <span className="h-8 w-8 rounded-full bg-slate-100" />
          <ChevronDown className="h-4 w-4" />
        </div>
      </div>
    </header>
  );
}

/**
 * 걸어 둔 알림 중 **지금 조건에 걸린 것**을 어느 화면에서든 알린다.
 *
 * ★왜 필요한가: 알림 규칙은 잘 돌고 있었는데(실측 4건 걸림) **알림 설정
 *   화면을 열어야만** 보였다. 종은 GE 템플릿에서 넘어온 **그림**이라
 *   눌러도 아무 일이 없었다. 조건이 걸려도 아무 데도 안 닿으면 그건
 *   알림이 아니라 그냥 목록이다.
 *
 * ⚠️텔레그램 전달은 아직 설정 전이라(`delivery_configured === false`)
 *   **이 종이 유일한 전달 경로**다. 그 사실을 툴팁에 적는다 — 종을 못 보면
 *   아무도 모른다는 뜻이니까.
 *
 * ⚠️조회 주기를 짧게 두지 않는다. 이 컴포넌트는 **모든 화면**에 있어서
 *   주기가 곧 전체 부하다. 알림 조건은 초 단위로 바뀌는 값이 아니다.
 *
 * ★덤으로 얻은 것: 알림 판정은 이 API 를 부를 때 일어나고 `triggered_since`
 *   를 DB 에 적는다. 예전에는 **알림 설정 화면을 연 순간에만** 돌아서 "언제부터
 *   걸렸나"가 실제보다 늦게 잡혔다. 이제 5분마다 돌므로 그만큼 촘촘해진다.
 *
 * ⚠️queryKey 를 알림 화면과 **같게** 둔다(`["alerts"]`). 다르게 두면 같은 화면에
 *   종의 숫자와 목록의 숫자가 따로 놀 수 있다.
 */
function AlertBell() {
  const queryClient = useQueryClient();
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: getAlerts,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    // 배지가 없다고 해서 "걸린 게 없다"는 뜻이 되면 안 된다 — 못 불러왔을
    // 때는 조용히 아무것도 안 그린다(아래 count == null).
    retry: 1,
  });
  // ★(O1) 서버 트립와이어는 '확인'을 누르면 종에서 빠진다(열린 채로 — 다시 알리지 않는다).
  const ack = useMutation({
    mutationFn: ackOpsAlert,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const ops = alerts.data?.ops ?? [];
  // 배지 = 조건에 걸린 규칙 + 열린 운영 알림.
  const count = alerts.data ? alerts.data.triggered_count + ops.length : null;
  const firing = (alerts.data?.rules ?? []).filter((r) => r.state === "TRIGGERED");
  const title =
    count == null
      ? "알림"
      : count === 0
        ? "걸린 알림이 없습니다"
        : [
            `${count}건이 걸렸습니다`,
            ...firing.map((r) => `· ${r.name ?? r.ticker ?? r.kind_label}: ${r.message}`),
            ...ops.map((o) => `· [운영] ${o.message}`),
            alerts.data?.delivery_configured
              ? ""
              : "전달 경로가 아직 없어 이 종이 유일한 알림입니다.",
          ]
            .filter(Boolean)
            .join("\n");

  return (
    <div className="group relative">
      <Link
        href="/settings/alerts"
        // 운영 알림이 있으면 아래 목록이 뜬다 — 네이티브 툴팁과 겹치지 않게 뺀다.
        title={ops.length > 0 ? undefined : title}
        aria-label={title}
        className="relative block text-ink-secondary transition-colors hover:text-ink"
      >
        <Bell className="h-5 w-5" />
        {count != null && count > 0 && (
          <span
            className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center
                       rounded-full bg-ask px-1 text-[10px] font-bold leading-none text-white"
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </Link>
      {ops.length > 0 && (
        <div
          className="invisible absolute right-0 top-full z-50 pt-2 opacity-0 transition-opacity
                     group-focus-within:visible group-focus-within:opacity-100
                     group-hover:visible group-hover:opacity-100"
        >
          <div className="w-[320px] rounded-xl bg-white p-1.5 shadow-[0_16px_36px_rgba(36,59,94,0.22)] ring-1 ring-hairline">
            <div className="px-3 pb-1 pt-2 text-[10px] font-bold text-ink-faint">
              운영 알림 · 서버가 5분마다 확인
            </div>
            {ops.map((o) => (
              <div
                key={o.key}
                className="flex items-start justify-between gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-ge-blue-bg"
              >
                <div className="min-w-0">
                  <div className="text-[12px] font-extrabold text-ge-navy">
                    {OPS_LABEL[o.kind] ?? o.kind}
                  </div>
                  <div className="break-words text-[11px] font-semibold text-ink-secondary">
                    {o.message}
                  </div>
                  <div className="text-[10px] text-ink-faint">
                    {new Date(o.first_seen).toLocaleString("ko-KR")}부터
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => ack.mutate(o.key)}
                  disabled={ack.isPending}
                  className="shrink-0 rounded-lg border border-hairline bg-white px-2 py-1 text-[11px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg disabled:text-ink-faint"
                >
                  확인
                </button>
              </div>
            ))}
            {firing.length > 0 && (
              <Link
                href="/settings/alerts"
                className="block rounded-lg px-3 py-2 text-[11px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg"
              >
                조건에 걸린 규칙 {firing.length}건 보기
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** 운영 알림 종류 → 화면 이름. */
const OPS_LABEL: Record<string, string> = {
  JOB_STUCK: "작업 멈춤",
  SOURCE_ERROR: "원천 계속 실패",
  LLM_CAP_80PCT: "LLM 하루 상한 80%",
  LLM_ESCALATION: "LLM 판단 요청",
};

/** 계좌 선택 목록의 한 줄. */
function AccountOption({
  label,
  meta,
  active,
  inactive,
  onSelect,
}: {
  label: string;
  meta: string;
  active: boolean;
  inactive?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-ge-blue-bg",
        active && "bg-ge-blue-bg",
      )}
    >
      <span
        className={cn(
          "truncate text-[13px] font-extrabold text-ge-navy",
          inactive && "text-ink-muted line-through",
        )}
      >
        {label}
      </span>
      <span className="shrink-0 text-[10px] font-semibold text-ink-faint">
        {meta}
      </span>
    </button>
  );
}
