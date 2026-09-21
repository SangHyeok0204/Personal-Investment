"use client";

import type { ReactNode } from "react";
import { PlugZap } from "lucide-react";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 개조 중 자리잡기용 공통 조각(2026-09-21).
//
// 키움/토스 계좌 API 가 붙기 전까지 화면의 **모양과 정보 밀도**를 먼저 확정하려고
// 만들었다. 숫자는 전부 "—" 로 둔다 — 그럴듯한 더미 숫자를 넣으면 나중에 실데이터와
// 섞였을 때 어느 쪽이 진짜인지 구분이 안 된다. 한 번 데이터가 붙는 카드는 이 조각을
// 버리고 실제 컴포넌트로 교체하면 된다.
// ─────────────────────────────────────────────────────────────────────────────

/** 아직 계좌 API 가 없다는 사실을 화면 맨 위에 못박는 띠. */
export function NotConnectedBanner({ what }: { what: string }) {
  return (
    <div className="mb-5 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <PlugZap className="h-4 w-4 shrink-0 text-amber-600" />
      <p className="text-[13px] font-semibold text-amber-900">
        {what} — 아직 연동 전입니다. 화면 골격만 잡혀 있고 모든 수치는 비어 있습니다.
      </p>
      <a
        href="/settings/connections"
        className="ml-auto shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-[12px] font-bold text-amber-800 transition-colors hover:bg-amber-100"
      >
        계좌 연동하기
      </a>
    </div>
  );
}

/** 상단 요약 숫자 한 칸. */
export function StatTile({
  label,
  hint,
  accent,
}: {
  label: string;
  hint?: string;
  accent?: "up" | "down" | "neutral";
}) {
  return (
    <div className="rounded-2xl border border-hairline bg-canvas p-4 shadow-card">
      <div className="text-[11px] font-bold tracking-wide text-ink-muted">
        {label}
      </div>
      <div
        className={cn(
          "mt-1.5 text-[24px] font-extrabold tabular-nums leading-none",
          accent === "up" && "text-bid",
          accent === "down" && "text-ask",
          (accent == null || accent === "neutral") && "text-ge-navy",
        )}
      >
        —
      </div>
      {hint && (
        <div className="mt-1.5 text-[11px] font-medium text-ink-faint">{hint}</div>
      )}
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return (
    <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{children}</div>
  );
}

/** 제목 띠(ge-header) 달린 카드 — 대시보드 카드의 기본형. */
export function StubCard({
  title,
  subtitle,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card",
        className,
      )}
    >
      <header className="flex items-baseline gap-2 bg-ge-header px-4 py-2.5">
        <h2 className="text-[13px] font-extrabold tracking-tight text-white">
          {title}
        </h2>
        {subtitle && (
          <span className="truncate text-[11px] font-medium text-white/60">
            {subtitle}
          </span>
        )}
      </header>
      <div className="flex-1 p-4">{children}</div>
    </section>
  );
}

/** 차트가 들어올 자리 — 축만 그려 두어 어떤 그림이 올지 읽히게 한다. */
export function StubChart({ height = 200 }: { height?: number }) {
  return (
    <div
      style={{ height }}
      className="relative w-full rounded-xl border border-dashed border-ge-line-soft bg-canvas-soft/60"
    >
      <div className="absolute inset-x-3 inset-y-3 flex flex-col justify-between">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-px w-full bg-ge-line-soft/70" />
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="rounded-full bg-white/80 px-3 py-1 text-[11px] font-bold text-ink-faint">
          데이터 연동 대기
        </span>
      </div>
    </div>
  );
}

/** 표가 들어올 자리 — 컬럼 이름은 확정해 두고 행만 비운다. */
export function StubTable({
  columns,
  rows = 5,
}: {
  columns: string[];
  rows?: number;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-hairline">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-ge-th">
            {columns.map((c) => (
              <th
                key={c}
                className="whitespace-nowrap px-3 py-2 text-[11px] font-extrabold text-ge-navy"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r} className="border-t border-hairline">
              {columns.map((c) => (
                <td
                  key={c}
                  className="px-3 py-2.5 text-[12px] font-semibold tabular-nums text-ink-faint"
                >
                  —
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 앞으로 이 화면에 무엇이 들어올지 적어 두는 목록. 설계 메모가 화면에 남는다. */
export function PlannedList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2.5">
          <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
          <span className="text-[13px] font-semibold leading-snug text-ink-secondary">
            {t}
          </span>
        </li>
      ))}
    </ul>
  );
}
