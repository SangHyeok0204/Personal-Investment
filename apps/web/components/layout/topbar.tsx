import type { ReactNode } from "react";
import { Bell, ChevronDown, CircleHelp, Menu, Search } from "lucide-react";

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
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-7">
      <div className="flex min-w-0 items-center gap-5">
        <Menu className="h-5 w-5 shrink-0 text-slate-500" />
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
