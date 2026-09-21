"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

// 화면 가운데 팝업. 연동 팝업(ConnectDialog)과 같은 모양을 쓰되, 그쪽은 자체
// 상태가 많아 따로 두고 이건 내용만 받는 껍데기다.
//
// ⚠️Esc 와 바깥 클릭으로 닫힌다. 모달이 떠 있는 동안 본문 스크롤을 막는다 —
//   뒤가 같이 스크롤되면 "무엇을 보고 있는지"가 흐려진다.

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 720,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-ge-navy/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ maxWidth: width }}
        className="max-h-[88vh] w-full overflow-y-auto rounded-2xl bg-canvas shadow-[0_24px_60px_rgba(36,59,94,0.32)]"
      >
        <header className="sticky top-0 z-10 flex items-baseline gap-2 rounded-t-2xl bg-ge-header px-5 py-3.5">
          <h2 className="text-[14px] font-extrabold text-white">{title}</h2>
          {subtitle && (
            <span className="truncate text-[11px] font-medium text-white/60">
              {subtitle}
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="ml-auto shrink-0 rounded-lg p-1 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
