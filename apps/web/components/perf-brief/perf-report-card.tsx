"use client";

/* [성과보고 HTML] TORUS/AI테크 하단 카드 (2026-07-30).
 *
 * S: 의 bat 이 만든 자체완결 HTML 을 그대로 iframe(srcDoc)으로 띄운다 — 회의 탭과 같은
 * 방식. 계산·서사·서식이 전부 S: 소관이라 대시보드는 고르고 띄우기만 한다.
 *
 * 최신성: HTML 은 안을 못 읽으므로 collector 가 파일명(=기준일)과 mtime(=작성일)으로
 * 판정한다. 오늘 만든 파일이 없으면 pending — **과거 보고서를 오늘 것처럼 자동으로
 * 띄우지 않는다**(어제 숫자를 오늘로 오인하는 사고 방지). 다만 드롭다운으로 과거분을
 * 직접 고르는 건 허용하고, 그때는 '오늘 아님' 배지를 띄운다. */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, RotateCw } from "lucide-react";
import {
  getPerfReportFile,
  getPerfReportList,
  type PerfReportItem,
} from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";

const KIND_LABEL: Record<PerfReportItem["kind"], string> = {
  daily: "데일리",
  weekly: "위클리",
};

function Notice({ head, body }: { head: string; body: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-canvas-soft px-5 py-6">
      <div className="text-[14px] font-bold text-ge-navy">{head}</div>
      <div className="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
        {body}
      </div>
    </div>
  );
}

export function PerfReportCard() {
  const list = useQuery({
    queryKey: ["perf-report"],
    queryFn: getPerfReportList,
    refetchInterval: 5 * 60 * 1000,
  });

  // 사용자가 드롭다운으로 고른 파일. null 이면 '오늘치'(current)를 따른다.
  const [picked, setPicked] = useState<string | null>(null);
  const d = list.data;
  const sel: PerfReportItem | null = useMemo(() => {
    if (!d) return null;
    if (picked) return d.items.find((x) => x.rel === picked) ?? null;
    return d.current;
  }, [d, picked]);

  const file = useQuery({
    queryKey: ["perf-report-file", sel?.rel],
    queryFn: () => getPerfReportFile(sel!.rel),
    enabled: sel != null,
  });

  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(720);

  // 내용 높이에 맞춰 iframe 을 늘린다 — 카드가 페이지 흐름에 그대로 얹히도록.
  // sandbox 에 allow-same-origin 이 있어야 contentDocument 를 읽을 수 있다(회의 탭 동일).
  useEffect(() => {
    setHeight(720);
  }, [sel?.rel]);
  const fit = () => {
    const doc = frameRef.current?.contentDocument;
    if (!doc) return;
    const h = Math.max(
      doc.documentElement?.scrollHeight ?? 0,
      doc.body?.scrollHeight ?? 0,
    );
    if (h > 0) setHeight(Math.min(Math.max(h + 24, 400), 12000));
  };

  const openInTab = () => {
    if (!file.data) return;
    const url = URL.createObjectURL(
      new Blob([file.data.html], { type: "text/html;charset=utf-8" }),
    );
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const stale = sel != null && d != null && sel.writtenOn !== d.today;

  return (
    <section className="rounded-2xl border border-hairline bg-white p-6 shadow-card">
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-[16px] font-extrabold text-ge-navy">
          오늘의 성과보고
          {sel ? ` — ${KIND_LABEL[sel.kind]}` : ""}
        </h2>

        {sel && (
          <span
            className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${
              stale
                ? "bg-amber-50 text-amber-700"
                : "bg-ge-blue-bg text-ge-point"
            }`}
          >
            {stale ? `${sel.writtenOn} 작성분` : "오늘 작성"}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {d && d.items.length > 0 && (
            <div className="relative">
              <select
                value={sel?.rel ?? ""}
                onChange={(e) => setPicked(e.target.value || null)}
                className="appearance-none rounded-lg border border-hairline bg-white py-1.5 pl-3 pr-8 text-[12px] font-semibold text-ink outline-none transition hover:bg-canvas-soft"
              >
                {!d.current && <option value="">— 오늘 보고서 없음 —</option>}
                {d.items.map((it) => (
                  <option key={it.rel} value={it.rel}>
                    {it.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
            </div>
          )}
          <button
            type="button"
            onClick={() => {
              list.refetch();
              file.refetch();
            }}
            title="S: 폴더를 다시 읽습니다"
            className="flex items-center gap-1.5 rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-canvas-soft"
          >
            <RotateCw
              className={`h-3.5 w-3.5 ${list.isFetching || file.isFetching ? "animate-spin" : ""}`}
            />
            갱신
          </button>
          {file.data && (
            <button
              type="button"
              onClick={openInTab}
              title="원본 HTML 을 새 탭에서 엽니다"
              className="flex items-center gap-1.5 rounded-lg border border-hairline px-2.5 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-canvas-soft"
            >
              <ExternalLink className="h-3.5 w-3.5" />새 탭
            </button>
          )}
        </div>
      </div>

      {list.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : list.isError ? (
        <ApiErrorBanner error={list.error} />
      ) : d?.status === "off" ? (
        <Notice
          head="오늘은 예정된 보고서가 없습니다"
          body="주말입니다. 월요일 위클리 / 화~금 데일리 순서로 올라옵니다."
        />
      ) : !sel ? (
        <Notice
          head="오늘 보고서가 아직 없습니다"
          body={
            `S: 폴더에서 bat 을 돌리면 여기에 바로 뜹니다.` +
            (d?.latest
              ? ` 마지막 보고서는 ${d.latest.label} (${d.latest.savedAt} 저장)입니다 — 위 드롭다운에서 열 수 있습니다.`
              : " 아직 생성된 보고서가 없습니다.")
          }
        />
      ) : file.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : file.isError ? (
        <ApiErrorBanner error={file.error} />
      ) : (
        <>
          {stale && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2 text-[12px] text-amber-800">
              오늘({d?.today}) 만들어진 보고서가 아닙니다 — {sel.savedAt} 저장분입니다.
            </div>
          )}
          <div className="overflow-hidden rounded-xl border border-hairline">
            <iframe
              key={sel.rel}
              ref={frameRef}
              title={sel.name}
              srcDoc={file.data?.html ?? ""}
              onLoad={fit}
              sandbox="allow-scripts allow-same-origin allow-popups"
              className="w-full border-0 bg-white"
              style={{ height }}
            />
          </div>
          <div className="mt-2 text-right text-[11px] text-ink-faint">
            {sel.name} · {sel.savedAt} 저장
          </div>
        </>
      )}
    </section>
  );
}
