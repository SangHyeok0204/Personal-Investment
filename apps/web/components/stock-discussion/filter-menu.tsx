"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// nav-menu 형 드롭다운 셸 — 버튼(라벨 + 현재선택 요약 + ▾) + 팝오버 패널.
// 바깥 클릭/Esc 로 닫힘. 패널은 컨테이너 ref 안에 있어 내부 클릭은 안 닫힌다.
export function FilterMenu({
  label,
  summary,
  active,
  accentColor,
  panelClassName,
  children,
}: {
  label: string;
  summary: string;
  active: boolean;
  accentColor?: string;
  panelClassName?: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold transition-colors",
          active
            ? "border-ge-point bg-ge-blue-bg text-ge-navy"
            : "border-hairline bg-canvas-soft text-ink-muted hover:bg-ge-blue-bg/50",
        )}
      >
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">
          {label}
        </span>
        <span
          className="max-w-[9rem] truncate"
          style={active && accentColor ? { color: accentColor } : undefined}
        >
          {summary}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2.2}
        />
      </button>

      {open && (
        <div
          className={cn(
            "absolute left-0 top-full z-30 mt-1.5 flex max-h-[min(60vh,26rem)] min-w-[13rem] flex-col overflow-y-auto rounded-xl border border-hairline bg-canvas p-1.5 shadow-lg",
            panelClassName,
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

// 드롭다운 옵션 한 줄 — 라벨(+보조텍스트) 좌측, 카운트 등 우측.
export function MenuOption({
  label,
  sub,
  active,
  accentColor,
  right,
  onClick,
}: {
  label: string;
  sub?: string;
  active: boolean;
  accentColor?: string;
  right?: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors",
        active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
      )}
    >
      <div className="min-w-0 flex-1">
        <div
          className={cn(
            "truncate text-[12.5px]",
            active ? "font-bold" : "font-semibold",
          )}
          style={accentColor ? { color: accentColor } : undefined}
        >
          {label}
        </div>
        {sub && (
          <div className="truncate text-[10.5px] tabular-nums text-ink-faint">
            {sub}
          </div>
        )}
      </div>
      {right != null && <div className="flex shrink-0 items-center gap-1.5">{right}</div>}
    </button>
  );
}
