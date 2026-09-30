"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ApiErrorBanner } from "@/components/states";
import { Cell, DataTable, StatRow, StatTile } from "@/components/stub";
import {
  getCoverage,
  type CoverageCell,
  type CoverageKind,
} from "@/lib/api-coverage";
import { cn } from "@/lib/utils";

// 데이터 보유 현황판(계획 S8 · §6, §12-8 레인 C) — 4개 리서치 화면 맨 위에 공통으로 얹는다.
//
// ⚠️`GET /api/v1/research/coverage/{kind}` 는 아직 `main.py` 에 안 붙어 있다(레인 C·
//   리드가 나중에 통합). 그동안은 이 패널이 늘 에러 배너를 보여준다 — 고장이 아니다.
// ⚠️예측 화면이 아니다. "무슨 데이터가 몇 건 있고 언제 받았나"만 본다.

const KIND_LABEL: Record<CoverageKind, string> = {
  stocks: "종목 단위 리서치",
  guru: "거장 13F",
  earnings: "어닝 콜 / 이슈",
  filings: "종목 공시",
};

function freshnessLabel(iso: string | null): string {
  if (!iso) return "받은 적 없음";
  const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (hours < 1) return "방금";
  if (hours < 24) return `${Math.round(hours)}시간 전`;
  return `${Math.round(hours / 24)}일 전`;
}

function CellValue({ value }: { value: CoverageCell }) {
  if (value == null) return <span className="text-ink-faint">—</span>;
  if (typeof value === "boolean") {
    return <span className={value ? "text-bid" : "text-ink-faint"}>{value ? "✓" : "·"}</span>;
  }
  return <>{value}</>;
}

export function CoveragePanel({
  kind,
  defaultOpen = true,
}: {
  kind: CoverageKind;
  /** 기본으로 펼쳐 둘지. 화면의 주 콘텐츠면 true(예: /research/stocks). */
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const q = useQuery({
    queryKey: ["coverage", kind],
    queryFn: () => getCoverage(kind),
    staleTime: 10 * 60_000,
    retry: false,
  });

  return (
    <section className="mb-4 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 bg-ge-header px-4 py-2 text-left"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-white/70" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-white/70" />
        )}
        <span className="shrink-0 text-[13px] font-extrabold tracking-tight text-white">
          보유 데이터 현황
        </span>
        <span className="truncate text-[11px] font-medium text-white/60">
          {KIND_LABEL[kind]} · 무슨 데이터가 얼마나 있나 · 예측 아님
        </span>
        {q.data && (
          <span className="ml-auto shrink-0 text-[10px] font-semibold text-white/50">
            {new Date(q.data.generated_at).toLocaleTimeString("ko-KR")} 기준
          </span>
        )}
      </button>

      {open && (
        <div className="p-3.5">
          {q.isError ? (
            <ApiErrorBanner error={q.error} />
          ) : q.isLoading || !q.data ? (
            <p className="py-6 text-center text-[12px] font-semibold text-ink-faint">불러오는 중…</p>
          ) : (
            <div className="space-y-3">
              <StatRow>
                {q.data.kpis.map((k) => (
                  <StatTile key={k.label} label={k.label} value={k.value} hint={k.hint ?? undefined} />
                ))}
              </StatRow>

              {q.data.sources.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {q.data.sources.map((s) => (
                    <span
                      key={s.source}
                      title={s.last_error_kind ? `최근 실패: ${s.last_error_kind}` : undefined}
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-bold",
                        s.stale ? "bg-status-failed/10 text-status-failed" : "bg-ge-th text-ink-secondary",
                      )}
                    >
                      {s.source} · {freshnessLabel(s.last_ok_at)}
                    </span>
                  ))}
                </div>
              )}

              {q.data.anomalies.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {q.data.anomalies.map((a) => (
                    <span
                      key={a}
                      className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-800"
                    >
                      이상치 · {a}
                    </span>
                  ))}
                </div>
              )}

              {q.data.table.rows.length > 0 && (
                <DataTable
                  columns={["", ...q.data.table.columns]}
                  align={["left", ...q.data.table.columns.map(() => "right" as const)]}
                >
                  {q.data.table.rows.map((row) => (
                    <tr key={row.key} className="border-b border-hairline">
                      <Cell left strong>
                        {row.link ? (
                          <a href={row.link} className="hover:underline">
                            {row.label}
                          </a>
                        ) : (
                          row.label
                        )}
                      </Cell>
                      {row.cells.map((v, i) => (
                        <Cell key={i}>
                          <CellValue value={v} />
                        </Cell>
                      ))}
                    </tr>
                  ))}
                </DataTable>
              )}

              {q.data.notes.length > 0 && (
                <ul className="space-y-0.5">
                  {q.data.notes.map((n) => (
                    <li key={n} className="text-[11px] text-ink-faint">
                      · {n}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
