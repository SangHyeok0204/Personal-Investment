"use client";

/* [성과분석 보고서] TORUS/AI테크 하단 카드 (2026-08-03 개편).
 *
 * S: 의 `단일PORT_분석.bat` · `비교PORT_분석.bat` 이 만든 자체완결 HTML 을 그대로
 * iframe(srcDoc)으로 띄운다 — 회의 탭과 같은 방식. 계산·서식이 전부 S: 소관이라
 * 대시보드는 고르고 띄우기만 한다.
 *
 * 예전에는 월=위클리 / 화~금=데일리 스케줄을 가정해 오늘 만든 파일이 없으면 아무것도
 * 보여 주지 않았다. 지금은 운용역이 필요할 때 돌리는 주문형이라 **가장 최근 보고서를
 * 늘 띄우고**, 오늘 만든 것이 아니면 작성일 배지로 알린다. 낡은 값을 오늘 것으로
 * 오인하는 사고는 배지가 막는다. 과거분은 드롭다운으로 직접 고른다. */

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

const KIND_LABEL: Record<string, string> = {
  single: "단일",
  compare: "비교",
  legacy: "지난 보고서",
};

const SELECT_CLS =
  "appearance-none rounded-lg border border-hairline bg-white py-1.5 pl-3 pr-8 " +
  "text-[12px] font-semibold text-ink outline-none transition hover:bg-canvas-soft";

const dot = (s: string) => s.replace(/-/g, ".");
// 두 번째 드롭다운에서는 날짜가 이미 정해져 있으니 label 꼬리의 "· 2026.07.31 기준" 을
// 뗀다. 위클리·월간처럼 그 꼬리가 없는 label 은 그대로 둔다.
const stripAsOf = (label: string) =>
  label.replace(/\s*·\s*\d{4}\.\d{2}\.\d{2}\s*기준$/, "");

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
    // 고른 파일이 목록에서 사라졌으면(폴더 정리·갱신) 최신본으로 되돌아간다.
    if (picked) return d.items.find((x) => x.rel === picked) ?? d.current;
    return d.current;
  }, [d, picked]);

  // ── 고르기는 두 단계다: 기준일 → 그 날짜의 파일 ──
  // 한 목록에 전부 넣으면 날짜가 쌓일수록 끝없이 길어진다. 어느 날 것인지는 대개 먼저
  // 정해져 있으므로 날짜로 한 번 좁히고 그 안에서 고르게 한다. items 는 서버가
  // (기준일, 저장시각) 내림차순으로 주므로 Map 의 삽입 순서가 곧 최신순이다.
  const byDate = useMemo(() => {
    const m = new Map<string, PerfReportItem[]>();
    for (const it of d?.items ?? []) {
      const arr = m.get(it.asOf);
      if (arr) arr.push(it);
      else m.set(it.asOf, [it]);
    }
    return m;
  }, [d]);
  const dates = useMemo(() => [...byDate.keys()], [byDate]);
  const curDate = sel?.asOf ?? dates[0] ?? "";
  const sameDay = byDate.get(curDate) ?? [];
  // 날짜를 바꾸면 그 날의 최신 파일로 바로 넘어간다(빈 화면을 거치지 않게).
  const pickDate = (dt: string) => {
    const first = byDate.get(dt)?.[0];
    if (first) setPicked(first.rel);
  };

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
          성과분석 보고서
          {sel ? ` — ${KIND_LABEL[sel.kind] ?? sel.kind}` : ""}
          {sel?.scope ? ` · ${sel.scope}` : ""}
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
            <>
              {/* ① 기준일 */}
              <div className="relative">
                <select
                  value={curDate}
                  onChange={(e) => pickDate(e.target.value)}
                  title="기준일"
                  className={SELECT_CLS}
                >
                  {dates.map((dt) => (
                    <option key={dt} value={dt}>
                      {dot(dt)} 기준 ({byDate.get(dt)?.length ?? 0})
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
              </div>
              {/* ② 그 날짜의 보고서 */}
              <div className="relative">
                <select
                  value={sel?.rel ?? ""}
                  onChange={(e) => setPicked(e.target.value || null)}
                  title="보고서"
                  className={SELECT_CLS}
                >
                  {sameDay.map((it) => (
                    <option key={it.rel} value={it.rel}>
                      {stripAsOf(it.label)} · {it.savedAt.slice(5)} 저장
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
              </div>
            </>
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
      ) : !sel ? (
        <Notice
          head="아직 만들어진 보고서가 없습니다"
          body={
            "S: 성과분석 폴더의 분석 tools\\단일PORT_분석.bat 또는 " +
            "비교PORT_분석.bat 을 돌리면 여기에 바로 뜹니다. " +
            "기준일과 기간을 물어보고 몇 초 만에 끝납니다."
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
