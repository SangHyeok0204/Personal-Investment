"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  BookOpen,
  Bot,
  CalendarDays,
  ChartNoAxesCombined,
  Database,
  Globe2,
  LayoutDashboard,
  LineChart,
  Moon,
  Search,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Items with `href` navigate; the rest are placeholders for pages not built yet.
const navGroups = [
  {
    title: "My",
    items: [
      { label: "메인 대시보드", icon: LayoutDashboard, href: "/" },
      { label: "포트폴리오 상세", icon: ChartNoAxesCombined, href: "/portfolio" },
      { label: "데이터 작업", icon: Database, href: "/data-operations" },
    ],
  },
  {
    title: "Realtime",
    items: [
      { label: "실시간 시장 분석", icon: LineChart },
      { label: "실시간 뉴스", icon: BookOpen },
    ],
  },
  {
    title: "???",
    items: [
      { label: "매크로", icon: Globe2 },
      { label: "종목 분석", icon: Search },
      { label: "주요 이벤트 분석", icon: CalendarDays },
    ],
  },
  {
    title: "Study",
    items: [
      { label: "AI / ML / DL", icon: Bot },
      { label: "CS", icon: Database },
      { label: "Math", icon: BarChart3 },
      { label: "Finance", icon: ChartNoAxesCombined },
      { label: "Others", icon: LayoutDashboard },
    ],
  },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-[216px] shrink-0 flex-col bg-[#071426] text-slate-200 shadow-[2px_0_24px_rgba(4,18,38,0.14)]">
      <div className="flex items-center gap-3 px-5 pb-5 pt-5">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-400 via-blue-600 to-indigo-700 shadow-lg shadow-blue-950/40">
          <ChartNoAxesCombined className="h-6 w-6 text-white" strokeWidth={1.7} />
        </div>
        <div>
          <div className="text-[17px] font-semibold tracking-tight text-white">Invest AI</div>
          <div className="text-[11px] font-medium tracking-wide text-slate-400">INTELLIGENCE</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto px-3 pb-5">
        {navGroups.map((group) => (
          <div key={group.title}>
            <div className="px-1 pb-1.5 text-sm font-semibold text-blue-400">{group.title}</div>
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const href = "href" in item ? item.href : undefined;
                const active = href != null && pathname === href;
                const rowClass = cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                  active
                    ? "bg-gradient-to-r from-blue-600/35 to-blue-500/15 font-medium text-blue-100 shadow-inner shadow-blue-300/5"
                    : "text-slate-300 hover:bg-white/[0.075] hover:text-white",
                );
                const inner = (
                  <>
                    <Icon className={cn("h-[18px] w-[18px] shrink-0", active ? "text-blue-400" : "text-slate-400")} strokeWidth={1.7} />
                    <span>{item.label}</span>
                  </>
                );

                return href ? (
                  <Link key={item.label} href={href} className={rowClass}>
                    {inner}
                  </Link>
                ) : (
                  <button key={item.label} type="button" className={rowClass}>
                    {inner}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="m-3 flex items-center rounded-lg border border-white/10 bg-white/[0.025] p-1.5">
        <button type="button" className="flex flex-1 items-center justify-center gap-2 rounded-md py-2 text-xs text-slate-300 hover:bg-white/[0.07]">
          <Moon className="h-4 w-4" /> 테마
        </button>
        <Link href="/settings" className="flex flex-1 items-center justify-center gap-2 rounded-md py-2 text-xs text-slate-300 hover:bg-white/[0.07]">
          <Settings className="h-4 w-4" /> 설정
        </Link>
      </div>
    </aside>
  );
}
