"use client";

import { useMemo } from "react";
import type { SdSource, SdSpy } from "@/lib/stock-discussion";
import { sourceStyle } from "./brand";

interface SpyGroup {
  author: string;
  source: SdSource;
  labels: string[];
  reason: string;
}

// (source, author) 로 그룹핑 — 한 작성자의 복수 라벨을 배열로(§3.1-⑦).
function groupSpies(spies: SdSpy[] | undefined): SpyGroup[] {
  const map = new Map<string, SpyGroup>();
  for (const s of spies ?? []) {
    const key = `${s.source}|${s.author}`;
    const g = map.get(key);
    if (g) {
      if (!g.labels.includes(s.label)) g.labels.push(s.label);
    } else {
      map.set(key, {
        author: s.author,
        source: s.source,
        labels: [s.label],
        reason: s.reason,
      });
    }
  }
  return Array.from(map.values());
}

export function SpyPanel({
  spies,
  onSpyClick,
}: {
  spies: SdSpy[] | undefined;
  onSpyClick: (author: string) => void;
}) {
  const groups = useMemo(() => groupSpies(spies), [spies]);

  return (
    <section className="rounded-xl border border-hairline bg-canvas p-4 shadow-card">
      <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-ink-muted">
        <span>스파이 작성자</span>
        {groups.length > 0 && (
          <span className="rounded-full bg-status-failed/10 px-1.5 text-[10px] text-status-failed">
            {groups.length}
          </span>
        )}
      </div>

      {groups.length === 0 ? (
        <p className="py-2 text-[11.5px] text-ink-faint">
          탐지된 스파이가 없습니다.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {groups.map((g) => (
            <button
              key={`${g.source}|${g.author}`}
              type="button"
              title={g.reason}
              onClick={() => onSpyClick(g.author)}
              className="flex flex-col gap-1 rounded-lg border border-status-failed/25 bg-status-failed/[0.04] px-2.5 py-2 text-left transition-colors hover:bg-status-failed/[0.09]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[12.5px] font-bold text-ink">
                  🚨 {g.author}
                </span>
                <span
                  className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  style={{
                    color: sourceStyle(g.source).color,
                    background: sourceStyle(g.source).bg,
                  }}
                >
                  {g.source}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {g.labels.map((l) => (
                  <span
                    key={l}
                    className="rounded bg-status-failed/12 px-1.5 py-0.5 text-[10px] font-semibold text-status-failed"
                  >
                    {l}
                  </span>
                ))}
              </div>
              <span className="line-clamp-2 text-[10.5px] leading-snug text-ink-faint">
                {g.reason}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
