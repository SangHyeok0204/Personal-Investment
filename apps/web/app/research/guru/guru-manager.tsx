"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cell, DataTable } from "@/components/stub";
import { addGuru, getGuruRoster, searchGuru, setGuruActive, type GuruRosterItem, type GuruSearchHit } from "@/lib/api";
import { cn } from "@/lib/utils";

// 거장 관리 (계획 A7) — 운용사 이름으로 EDGAR 검색(13F 제출자만) → 추가 → SEC 에서 2013Q2 부터 백필.
// 비활성화하면 과거 데이터는 남고 분석(거장 수 · 정족수 · 변동)에서만 빠진다.

const STATUS: Record<GuruRosterItem["backfill_status"], { label: string; tone: string }> = {
  pending: { label: "백필 대기", tone: "bg-ge-point/15 text-ge-point" },
  running: { label: "백필 중…", tone: "bg-ge-point/15 text-ge-point" },
  done: { label: "완료", tone: "bg-ink-faint/15 text-ink-muted" },
  failed: { label: "실패", tone: "bg-ask/15 text-ask" },
  skip: { label: "건너뜀", tone: "bg-ink-faint/15 text-ink-muted" },
};

export function GuruManager() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});

  const roster = useQuery({
    queryKey: ["guruRoster"],
    queryFn: getGuruRoster,
    // 백필이 도는 동안만 5초마다 — 끝나면 멈춘다
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => r.backfill_status === "pending" || r.backfill_status === "running")
        ? 5_000
        : false,
  });
  const search = useQuery({
    queryKey: ["guruSearch", submitted],
    queryFn: () => searchGuru(submitted!),
    enabled: submitted != null,
    staleTime: 60_000,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["guruRoster"] });
    qc.invalidateQueries({ queryKey: ["guruSearch"] });
    qc.invalidateQueries({ queryKey: ["guruOverview"] });
  };
  const add = useMutation({
    mutationFn: (h: GuruSearchHit) =>
      addGuru({ cik: h.cik, filer_name: h.name, guru_name: names[h.cik]?.trim() || undefined }),
    onSuccess: refresh,
  });
  const toggle = useMutation({
    mutationFn: (r: GuruRosterItem) => setGuruActive(r.cik, !r.active),
    onSuccess: refresh,
  });

  const gurus = (roster.data?.items ?? []).filter((r) => r.kind === "guru");
  const nActive = gurus.filter((r) => r.active).length;

  return (
    <div className="space-y-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim().length >= 2) setSubmitted(q.trim());
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="운용사 이름으로 검색 (예: greenlight, pershing)"
          className="min-w-0 flex-1 rounded-lg border border-hairline bg-canvas px-3 py-2 text-[13px] outline-none focus:border-ge-point"
        />
        <button
          type="submit"
          className="shrink-0 rounded-lg bg-ge-header px-4 py-2 text-[12px] font-bold text-white disabled:opacity-50"
          disabled={q.trim().length < 2 || search.isFetching}
        >
          {search.isFetching ? "검색 중…" : "SEC 검색"}
        </button>
      </form>

      {submitted && (
        <div>
          {search.isError ? (
            <p className="text-[12px] font-semibold text-ask">{(search.error as Error).message}</p>
          ) : search.data && search.data.items.length === 0 ? (
            <p className="text-[12px] text-ink-faint">
              &quot;{submitted}&quot; 로 13F 를 낸 운용사가 없습니다. 운용사(법인) 이름으로 찾아 보세요.
            </p>
          ) : (
            <DataTable columns={["운용사 (SEC)", "CIK", "화면에 쓸 이름", ""]} align={["left", "left", "left", "right"]}>
              {(search.data?.items ?? []).map((h) => (
                <tr key={h.cik} className="border-b border-hairline">
                  <Cell left strong>
                    {h.name}
                  </Cell>
                  <Cell left tone="muted">
                    {h.cik}
                  </Cell>
                  <Cell left>
                    <input
                      value={names[h.cik] ?? ""}
                      onChange={(e) => setNames({ ...names, [h.cik]: e.target.value })}
                      placeholder="예: David Einhorn"
                      disabled={h.in_roster && h.kind === "guru" && !!h.active}
                      className="w-40 rounded border border-hairline px-2 py-1 text-[12px]"
                    />
                  </Cell>
                  <Cell>
                    {h.in_roster && h.kind === "guru" && h.active ? (
                      <span className="text-[11px] text-ink-faint">이미 명단</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => add.mutate(h)}
                        disabled={add.isPending}
                        className="rounded bg-ge-point px-2.5 py-1 text-[11px] font-bold text-white disabled:opacity-50"
                      >
                        {h.in_roster ? "다시 켜기" : "추가"}
                      </button>
                    )}
                  </Cell>
                </tr>
              ))}
            </DataTable>
          )}
          {add.isError && <p className="mt-1 text-[12px] font-semibold text-ask">{(add.error as Error).message}</p>}
        </div>
      )}

      <div>
        <p className="mb-1 text-[11px] font-bold text-ink-muted">
          명단 · 켜짐 {nActive}명
        </p>
        <DataTable
          columns={["거장", "운용사", "13F 분기", "마지막", "백필", "분석에 포함"]}
          align={["left", "left", "right", "right", "left", "right"]}
        >
          {gurus.map((r) => (
            <tr key={r.cik} className={cn("border-b border-hairline", !r.active && "opacity-55")}>
              <Cell left strong>
                {r.guru_name ?? r.firm}
              </Cell>
              <Cell left tone="muted">
                {r.firm}
              </Cell>
              <Cell>{r.n_periods}</Cell>
              <Cell>{r.last_period?.slice(0, 7) ?? "—"}</Cell>
              <Cell left>
                <span
                  title={r.note ?? undefined}
                  className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", STATUS[r.backfill_status].tone)}
                >
                  {STATUS[r.backfill_status].label}
                </span>
                {r.backfill_status === "failed" && r.note && (
                  <span className="ml-1 text-[10px] text-ask">{r.note.slice(0, 40)}</span>
                )}
              </Cell>
              <Cell>
                <button
                  type="button"
                  onClick={() => toggle.mutate(r)}
                  disabled={toggle.isPending}
                  className={cn(
                    "rounded px-2 py-0.5 text-[11px] font-bold",
                    r.active ? "bg-ge-header text-white" : "border border-hairline text-ink-muted",
                  )}
                >
                  {r.active ? "켜짐" : "꺼짐"}
                </button>
              </Cell>
            </tr>
          ))}
        </DataTable>
      </div>
    </div>
  );
}
