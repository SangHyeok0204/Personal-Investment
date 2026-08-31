"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getStockDetail,
  saveStockAxis,
  type StockDetail,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// [5대 축 편집 팝업] — 차트 스크리닝 헤더의 [5대 축 편집] 버튼이 연다.
// (2026-08-24 사용자 지시: 우하단 칸은 실시간 뉴스에 내주고 축 편집은 팝업으로.)
//
// 축은 운용역이 **수기로** 관리하는 입력이고, 저장하면 S: 의
// input\raw\stock_axis\{이름}_axis.json 이 그대로 고쳐진다(원본이 곧 저장소 —
// 별도 DB 를 두면 어느 쪽이 정본인지 흐려진다). 크롤링 뉴스를 이 축에 매핑하는
// AI 파이프라인이 이 파일을 읽으므로, 여기 적는 문구가 곧 그 분류의 기준이 된다.

export function AxisEditorModal({
  name,
  symbol,
  onClose,
}: {
  name: string;
  symbol: string | null;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["stock-detail", name],
    queryFn: () => getStockDetail(name),
    // 수기 파일이라 폴링이 필요 없다 — 팝업을 열 때·저장 후 무효화로만 읽는다.
    staleTime: 5 * 60_000,
  });

  return (
    // 배경 클릭 = 닫기. 카드 안 클릭은 stopPropagation 으로 살린다.
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-[440px] flex-col rounded-xl border border-hairline bg-canvas shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-2 border-b border-hairline px-4 py-2.5">
          <h2 className="shrink-0 text-[13px] font-extrabold text-ink">종목 상세 · 5대 축</h2>
          <span className="min-w-0 truncate text-[11px] text-ink-muted">
            {name}
            <span className="ml-1 tabular-nums text-slate-400">{symbol}</span>
          </span>
          <button
            onClick={onClose}
            aria-label="닫기"
            className="ml-auto rounded px-1.5 text-[13px] text-ink-muted hover:bg-canvas-soft"
          >
            ✕
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
          {isLoading ? (
            <p className="text-[11px] text-ink-muted">불러오는 중…</p>
          ) : isError || !data ? (
            <p className="text-[11px] text-rose-600">
              종목 파일이 없습니다 — stock_info/stock_axis 는 수기 입력 폴더라 아직 안
              채워졌을 수 있습니다.
            </p>
          ) : (
            // ★key={name} — 종목이 바뀌면 편집 상태를 통째로 버리고 새로 만든다.
            //   effect 로 동기화하면 "편집 중에 갱신이 값을 되돌리는" 류의 버그가 생긴다.
            <Editor key={name} detail={data} />
          )}
        </div>
      </div>
    </div>
  );
}

function Editor({ detail }: { detail: StockDetail }) {
  const qc = useQueryClient();
  const [axes, setAxes] = useState<string[]>(detail.axes);
  const [newsAxis, setNewsAxis] = useState<boolean>(detail.news_axis);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      saveStockAxis({
        name: detail.name,
        symbol: detail.symbol,
        news_axis: newsAxis,
        axes,
      }),
    onSuccess: () => {
      setSavedAt(new Date().toTimeString().slice(0, 5));
      qc.invalidateQueries({ queryKey: ["stock-detail", detail.name] });
    },
  });

  const dirty =
    newsAxis !== detail.news_axis ||
    axes.some((a, i) => a !== (detail.axes[i] ?? ""));

  const sec = detail.sector;
  return (
    <div className="flex flex-col gap-3">
      {/* 메타 — stock_info 소유(읽기 전용). 섹터는 L1›L2›L3 만 보이고 전체는 툴팁. */}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
        <dt className="text-ink-muted">섹터</dt>
        <dd
          className="truncate font-semibold text-ink"
          title={sec ? ["L1", "L2", "L3", "L4", "L5"].map((k) => sec[k]).join(" › ") : undefined}
        >
          {sec ? [sec.L1, sec.L2, sec.L3].filter(Boolean).join(" › ") : "−"}
        </dd>
        <dt className="text-ink-muted">국가 · 통화</dt>
        <dd className="font-semibold text-ink">
          {detail.country ?? "−"} · {detail.currency ?? "−"}
        </dd>
      </dl>

      {/* 5대 축 — stock_axis 소유(편집 가능) */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-ink">판단 5대 축</span>
          <label className="ml-auto flex cursor-pointer items-center gap-1 text-[10.5px] text-ink-muted">
            <input
              type="checkbox"
              checked={newsAxis}
              onChange={(e) => setNewsAxis(e.target.checked)}
              disabled={!detail.has_axis_file}
            />
            뉴스-축 매핑 대상
          </label>
        </div>
        {axes.map((a, i) => (
          <input
            key={i}
            value={a}
            placeholder={`축 ${i + 1}`}
            disabled={!detail.has_axis_file}
            onChange={(e) =>
              setAxes((cur) => cur.map((v, j) => (j === i ? e.target.value : v)))
            }
            className={cn(
              "rounded-md border border-hairline bg-canvas px-2 py-1 text-[11.5px] text-ink",
              "placeholder:text-slate-300 focus:border-ge-point focus:outline-none",
              "disabled:bg-canvas-soft disabled:text-slate-400",
            )}
          />
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => save.mutate()}
          disabled={!detail.has_axis_file || !dirty || save.isPending}
          className={cn(
            "rounded-lg px-3 py-1 text-[11.5px] font-bold transition-colors",
            dirty && !save.isPending
              ? "bg-ge-navy text-white hover:opacity-90"
              : "bg-canvas-soft text-slate-400",
          )}
        >
          {save.isPending ? "저장 중…" : "저장"}
        </button>
        {!detail.has_axis_file ? (
          <span className="text-[10.5px] text-amber-600">
            축 파일이 아직 없습니다 — 생성은 수기 입력 폴더 소관
          </span>
        ) : save.isError ? (
          <span className="text-[10.5px] text-rose-600">
            저장 실패 — {(save.error as Error)?.message ?? "알 수 없는 오류"}
          </span>
        ) : savedAt && !dirty ? (
          <span className="text-[10.5px] text-emerald-600">{savedAt} 저장됨</span>
        ) : dirty ? (
          <span className="text-[10.5px] text-ink-muted">저장 안 된 변경이 있습니다</span>
        ) : null}
      </div>
    </div>
  );
}
