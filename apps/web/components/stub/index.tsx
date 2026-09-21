"use client";

import type { ReactNode } from "react";
import { PlugZap } from "lucide-react";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 개조 중 자리잡기용 공통 조각(2026-09-21).
//
// 키움/토스 계좌 API 가 붙기 전까지 화면의 **모양과 정보 밀도**를 먼저 확정하려고
// 만들었다. 숫자는 전부 "—" 로 둔다 — 그럴듯한 더미 숫자를 넣으면 나중에 실데이터와
// 섞였을 때 어느 쪽이 진짜인지 구분이 안 된다.
//
// ★StatTile 은 이제 `value` 를 받는다(2026-09-21 2차). 실데이터가 붙은 화면은 값을
//   넘기고, 아직 안 붙은 화면은 안 넘겨서 "—" 로 둔다 — 한 컴포넌트로 두 상태를
//   같은 모양으로 그린다.
// ─────────────────────────────────────────────────────────────────────────────

/** 아직 계좌 API 가 없다는 사실을 화면 맨 위에 못박는 띠. */
export function NotConnectedBanner({
  what,
  message,
}: {
  what: string;
  /** 기본 문구 대신 쓸 설명(예: API 서버 자체가 안 떠 있는 경우). */
  message?: string;
}) {
  return (
    <div className="mb-5 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <PlugZap className="h-4 w-4 shrink-0 text-amber-600" />
      <p className="text-[13px] font-semibold text-amber-900">
        {message ??
          `${what} — 아직 연동 전입니다. 화면 골격만 잡혀 있고 모든 수치는 비어 있습니다.`}
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

/** 상단 요약 숫자 한 칸. `value` 가 없으면 "—". */
export function StatTile({
  label,
  value,
  hint,
  accent,
  loading,
}: {
  label: string;
  value?: string | null;
  hint?: string;
  /** "auto" 면 값의 부호를 보고 상승/하락 색을 고른다. */
  accent?: "up" | "down" | "neutral" | "auto";
  loading?: boolean;
}) {
  const shown = loading ? "…" : (value ?? "—");
  const resolved =
    accent === "auto"
      ? shown.startsWith("-")
        ? "down"
        : shown.startsWith("+")
          ? "up"
          : "neutral"
      : accent;

  return (
    <div className="rounded-2xl border border-hairline bg-canvas p-4 shadow-card">
      <div className="text-[11px] font-bold tracking-wide text-ink-muted">
        {label}
      </div>
      <div
        className={cn(
          "mt-1.5 text-[24px] font-extrabold tabular-nums leading-none",
          // 국내 관행: 상승/이익 = 빨강, 하락/손실 = 파랑.
          resolved === "up" && "text-bid",
          resolved === "down" && "text-ask",
          (resolved == null || resolved === "neutral") && "text-ge-navy",
        )}
      >
        {shown}
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
export function StubChart({
  height = 200,
  note = "데이터 연동 대기",
}: {
  height?: number;
  note?: string;
}) {
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
          {note}
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

/** 실데이터 표 — 같은 껍데기를 쓰되 행은 호출자가 그린다. */
export function DataTable({
  columns,
  children,
  empty,
  align,
}: {
  columns: string[];
  children: ReactNode;
  /** 행이 하나도 없을 때 표 자리에 띄울 문구. */
  empty?: string;
  /** 컬럼별 정렬 — 생략하면 첫 컬럼만 좌측, 나머지는 우측(숫자 표 기본형). */
  align?: ("left" | "right")[];
}) {
  const hasRows = Array.isArray(children)
    ? children.flat().filter(Boolean).length > 0
    : Boolean(children);

  return (
    <div className="overflow-x-auto rounded-xl border border-hairline">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-ge-th">
            {columns.map((c, i) => (
              <th
                key={c}
                className={cn(
                  "whitespace-nowrap px-3 py-2 text-[11px] font-extrabold text-ge-navy",
                  (align?.[i] ?? (i === 0 ? "left" : "right")) === "right" &&
                    "text-right",
                )}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hasRows ? (
            children
          ) : (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-10 text-center text-[12px] font-semibold text-ink-faint"
              >
                {empty ?? "표시할 내용이 없습니다"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** DataTable 의 셀 — 기본 우측 정렬(숫자), `left` 로 좌측. */
export function Cell({
  children,
  left,
  strong,
  tone,
  className,
}: {
  children: ReactNode;
  left?: boolean;
  strong?: boolean;
  tone?: "up" | "down" | "muted";
  className?: string;
}) {
  return (
    <td
      className={cn(
        "whitespace-nowrap px-3 py-2.5 text-[12px] tabular-nums",
        left ? "text-left" : "text-right",
        strong ? "font-extrabold text-ge-navy" : "font-semibold text-ink",
        tone === "up" && "text-bid",
        tone === "down" && "text-ask",
        tone === "muted" && "text-ink-faint",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** 문자열 금액의 부호로 상승/하락 색을 고른다. */
export function toneOf(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null || value === "") return undefined;
  if (value.startsWith("-")) return "down";
  if (/^-?0*(\.0*)?$/.test(value)) return undefined;
  return "up";
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
