"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Database, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/data-operations", label: "Data Operations", icon: Database },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-hairline bg-canvas-soft">
      <div className="px-5 py-5">
        <div className="text-[15px] font-semibold tracking-tight text-ink">
          Personal Investment
        </div>
        <div className="mt-0.5 text-xs text-ink-faint">Local platform</div>
      </div>

      <nav className="flex flex-col gap-0.5 px-3">
        {nav.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-black/[0.04] font-medium text-ink"
                  : "text-ink-secondary hover:bg-black/[0.03]",
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary" />
              )}
              <Icon
                className={cn("h-4 w-4 shrink-0", active ? "text-ink" : "text-ink-faint")}
                strokeWidth={1.75}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
