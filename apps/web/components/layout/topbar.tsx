"use client";

import type { ReactNode } from "react";
import { Bell, ChevronDown, CircleHelp, Menu, Search } from "lucide-react";
import { useSidebar } from "@/components/layout/sidebar-context";

/**
 * Per-page top bar (portfolio-detail-spec §1). The shell (height, border, global
 * icons) is shared; each page supplies its own title/status/actions.
 */
export function Topbar({
  title,
  subtitle,
  status,
  actions,
}: {
  title: string;
  subtitle?: string;
  status?: ReactNode;
  actions?: ReactNode;
}) {
  const { collapsed, toggle } = useSidebar();

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

      <div className="flex shrink-0 items-center gap-5 text-slate-500">
        {actions}
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
