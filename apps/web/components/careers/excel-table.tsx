"use client";

import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

// 엑셀처럼 보이는 표 — 열 머리를 누르면 정렬이 오름차순 → 내림차순 → 원래 순서로 돈다.
//
// ★2026-11-02 채용 공고 화면용으로 만들었다(사용자: "엑셀처럼, 컬럼은 색칠").
// ★2026-11-03 사용자 요청: 필터 드롭다운(값 체크박스·검색)은 걷었다 — "정렬은 알아서 오름/내림차순으로, 드롭다운 필요없어".

/** 열 머리 색 — 대시보드 팔레트(tailwind.config 의 brand 계열)만 쓴다. */
export type ColumnTone = "brand" | "blue" | "soft" | "point";

const HEAD_TONE: Record<ColumnTone, string> = {
  brand: "bg-brand text-white",
  blue: "bg-brand-blue text-white",
  soft: "bg-brand-blue-soft text-ink",
  point: "bg-brand-point text-white",
};
// 본문 열은 아주 옅게 — 머리 색이 어느 열 묶음인지 아래까지 이어 보이게.
const BODY_TONE: Record<ColumnTone, string> = {
  brand: "",
  blue: "bg-brand-blue-soft/20",
  soft: "bg-brand-blue-soft/10",
  point: "",
};

export interface ExcelColumn<T> {
  key: string;
  label: string;
  tone: ColumnTone;
  /** 셀 글자(render 가 없을 때)이자 정렬 값. */
  value: (row: T) => string;
  /** 정렬 키(없으면 value). 빈 값은 방향과 상관없이 맨 뒤. */
  sortValue?: (row: T) => string;
  render?: (row: T) => ReactNode;
  className?: string;
  /** px — 표는 table-fixed 라 이 폭을 지킨다. 없으면 남는 폭을 나눠 갖는다. */
  width?: number;
}

type Sort = { key: string; dir: 1 | -1 } | null;

export function ExcelTable<T>({
  rows,
  columns,
  rowKey,
  maxHeight = "calc(100vh - 260px)",
}: {
  rows: T[];
  columns: ExcelColumn<T>[];
  rowKey: (row: T, i: number) => string;
  maxHeight?: string;
}) {
  const [sort, setSort] = useState<Sort>(null);

  // 같은 열을 다시 누르면 오름 → 내림 → 해제.
  const toggle = (key: string) =>
    setSort((s) =>
      s?.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : null,
    );

  // 행이 수십~수백 개라 메모하지 않는다.
  const shown = (() => {
    if (!sort) return rows;
    const c = columns.find((x) => x.key === sort.key)!;
    const sv = (r: T) => (c.sortValue ?? c.value)(r);
    return [...rows].sort((a, b) => {
      const x = sv(a);
      const y = sv(b);
      if (!x || !y) return !x && !y ? 0 : !x ? 1 : -1;
      return x.localeCompare(y, "ko") * sort.dir;
    });
  })();

  return (
    <div className="overflow-auto border border-ink-faint/40" style={{ maxHeight }}>
      <table className="w-full min-w-[1080px] table-fixed border-collapse text-[12px]">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="w-10 border border-ink-faint/40 bg-canvas-soft px-1 py-1.5 text-center text-[11px] font-semibold text-ink-muted">
              #
            </th>
            {columns.map((c) => {
              const dir = sort?.key === c.key ? sort.dir : null;
              const Icon = dir === 1 ? ArrowUp : dir === -1 ? ArrowDown : ArrowUpDown;
              return (
                <th
                  key={c.key}
                  style={c.width ? { width: c.width } : undefined}
                  aria-sort={dir === 1 ? "ascending" : dir === -1 ? "descending" : "none"}
                  className={cn(
                    "border border-ink-faint/40 p-0 text-left font-bold",
                    HEAD_TONE[c.tone],
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggle(c.key)}
                    className="flex w-full items-center gap-1 px-2 py-1.5 text-left hover:brightness-95"
                  >
                    <span className="flex-1 whitespace-nowrap">{c.label}</span>
                    <Icon className={cn("h-3.5 w-3.5 shrink-0", !dir && "opacity-40")} />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={rowKey(r, i)} className="group">
              <td className="border border-ink-faint/30 bg-canvas-soft px-1 text-center text-[11px] text-ink-muted">
                {i + 1}
              </td>
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "border border-ink-faint/30 px-2 py-1 align-top text-ink-secondary group-hover:bg-brand-blue-soft/40",
                    BODY_TONE[c.tone],
                    c.className,
                  )}
                >
                  {c.render ? c.render(r) : c.value(r) || "—"}
                </td>
              ))}
            </tr>
          ))}
          {shown.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1} className="py-8 text-center text-ink-muted">
                공고가 없습니다.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
