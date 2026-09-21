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

// 키움 API 가 붙기 전까지 쓰는 더미. 실제로는 /api/accounts 에서 받아온다.
const PLACEHOLDER_ACCOUNTS = [
  { id: "all", label: "전체 계좌", broker: "합산" },
  { id: "kiwoom-main", label: "키움 주계좌", broker: "키움증권" },
  { id: "kiwoom-isa", label: "ISA", broker: "키움증권" },
  { id: "toss", label: "토스 계좌", broker: "토스증권" },
  { id: "pension", label: "연금저축", broker: "미연동" },
];

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
  /** 마지막 동기화 시각 — 실데이터가 붙기 전에는 넘기지 않으면 "미연동"으로 뜬다. */
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
  const [accountId, setAccountId] = useState("all");
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

  const account =
    PLACEHOLDER_ACCOUNTS.find((a) => a.id === accountId) ??
    PLACEHOLDER_ACCOUNTS[0];

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
                <Wallet className="h-3.5 w-3.5 text-ge-point" />
                {account.label}
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              </button>
              {accountOpen && (
                <div
                  role="listbox"
                  className="absolute right-0 top-full z-50 mt-1.5 min-w-[196px] rounded-xl bg-white p-1.5 shadow-[0_16px_36px_rgba(36,59,94,0.22)] ring-1 ring-hairline"
                >
                  {PLACEHOLDER_ACCOUNTS.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      role="option"
                      aria-selected={a.id === accountId}
                      onClick={() => {
                        setAccountId(a.id);
                        setAccountOpen(false);
                      }}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-ge-blue-bg",
                        a.id === accountId && "bg-ge-blue-bg",
                      )}
                    >
                      <span className="text-[13px] font-extrabold text-ge-navy">
                        {a.label}
                      </span>
                      <span className="text-[10px] font-semibold text-ink-faint">
                        {a.broker}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* 동기화 — syncedAt 이 없으면 아직 계좌 API 가 안 붙은 상태다. */}
            <button
              type="button"
              onClick={onSync}
              disabled={!onSync}
              title={
                syncedAt
                  ? `마지막 동기화: ${new Date(syncedAt).toLocaleString("ko-KR")}`
                  : "계좌 API 미연동"
              }
              className="flex items-center gap-1.5 text-[12px] font-bold text-slate-500 transition-colors hover:text-slate-700 disabled:cursor-default disabled:text-slate-300"
            >
              <RefreshCw className="h-4 w-4" />
              {syncedAt
                ? new Date(syncedAt).toLocaleTimeString("ko-KR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "미연동"}
            </button>
          </>
        )}

        <Search className="h-5 w-5" />
        <Bell className="h-5 w-5" />
        <CircleHelp className="h-5 w-5" />
        <div className="flex items-center gap-1.5">
          <span className="h-8 w-8 rounded-full bg-slate-100" />
          <ChevronDown className="h-4 w-4" />
        </div>
      </div>
    </header>
  );
}
