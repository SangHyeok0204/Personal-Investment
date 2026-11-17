"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Maximize2, Minimize2 } from "lucide-react";
import { ExcelTable, type ExcelColumn } from "@/components/careers/excel-table";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { StubCard } from "@/components/stub";
import { getJobPostings, type JobPosting } from "@/lib/api-careers";
import { cn } from "@/lib/utils";

// 채용 공고 — finance-jobs 스킬이 크롤링한 금융권 신입/인턴 공고 중 지금 지원 가능한 것.
//
// ★2026-11-02 사용자 요청: 메뉴 [채용 공고], 엑셀처럼 열 머리를 눌러 정렬(오름→내림), 열은 대시보드 색으로.
//   ★2026-11-03 필터 드롭다운은 걷었다(사용자: "드롭다운 필요없어").
//   열: 회사 · 지원가능시기 · 근무시기 · 신입/인턴 · 직무 · 출처 · 링크 · 카테고리 · 근무지 (+ 마감 D-day).
//   원천은 storage/jobs/postings.json — 다시 수집은 scripts/crawl-jobs.sh(빈 칸 보완은 스킬 2단계).

const DAY = 86_400_000;

function dday(deadline: string, today: string): number | null {
  if (!deadline) return null;
  return Math.round((Date.parse(deadline) - Date.parse(today)) / DAY);
}

const KIND_STYLE: Record<string, string> = {
  인턴: "bg-brand-blue text-white",
  "신입·인턴": "bg-brand-blue-soft text-ink",
  신입: "bg-brand text-white",
};

// ★2026-11-03 사용자 요청: 신입/인턴 구분 — 표 위 탭. '신입·인턴' 공고는 인턴·신입 양쪽에 다 나온다.
const KIND_TABS = ["전체", "인턴", "신입", "직급 미표기"] as const;
type KindTab = (typeof KIND_TABS)[number];

function inKind(j: JobPosting, t: KindTab): boolean {
  if (t === "전체") return true;
  if (t === "직급 미표기")
    return !["인턴", "신입", "신입·인턴"].includes(j.kind);
  return j.kind === t || j.kind === "신입·인턴";
}

function columns(today: string): ExcelColumn<JobPosting>[] {
  return [
    {
      key: "company",
      label: "회사",
      tone: "brand",
      width: 118,
      value: (r) => r.company,
      className: "font-bold text-ink",
    },
    {
      key: "apply",
      label: "지원가능시기",
      tone: "blue",
      width: 92,
      value: (r) => r.apply_period,
    },
    {
      key: "deadline",
      label: "마감",
      tone: "blue",
      width: 92,
      value: (r) => (r.deadline ? r.deadline.slice(5).replace("-", "/") : ""),
      sortValue: (r) => r.deadline,
      render: (r) => {
        const d = dday(r.deadline, today);
        if (d == null) return <span className="text-ink-muted">—</span>;
        return (
          <span
            className={cn(
              "whitespace-nowrap",
              d <= 3 && "font-bold text-status-failed",
            )}
          >
            {r.deadline.slice(5).replace("-", "/")} (
            {d === 0 ? "D-day" : `D-${d}`})
          </span>
        );
      },
    },
    {
      key: "work",
      label: "근무시기",
      tone: "blue",
      width: 124,
      value: (r) => r.work_period,
    },
    {
      key: "kind",
      label: "신입/인턴",
      tone: "soft",
      width: 82,
      value: (r) => r.kind,
      render: (r) => (
        <span
          className={cn(
            "inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-bold",
            KIND_STYLE[r.kind] ?? "bg-canvas-soft text-ink-muted",
          )}
        >
          {r.kind || "—"}
        </span>
      ),
    },
    {
      key: "role",
      label: "직무",
      tone: "soft",
      width: 140,
      value: (r) => r.role,
    },
    {
      key: "category",
      label: "카테고리",
      tone: "soft",
      width: 80,
      value: (r) => r.category,
    },
    {
      key: "source",
      label: "출처",
      tone: "point",
      width: 84,
      value: (r) => r.source,
    },
    {
      key: "link",
      label: "링크",
      tone: "point",
      // 정렬은 공고명으로 — URL 순서는 의미가 없다.
      value: (r) => r.title,
      render: (r) => (
        <a
          href={r.url}
          target="_blank"
          rel="noopener noreferrer"
          title={r.title}
          className="flex items-start gap-1 text-brand-blue underline-offset-2 hover:underline"
        >
          <span className="line-clamp-2">{r.title}</span>
          <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
        </a>
      ),
    },
    {
      key: "location",
      label: "근무지",
      tone: "point",
      width: 110,
      value: (r) => r.location,
      render: (r) =>
        r.location ? (
          <span className="line-clamp-2" title={r.location}>
            {r.location}
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
  ];
}

export default function CareersPage() {
  const q = useQuery({
    queryKey: ["jobPostings"],
    queryFn: getJobPostings,
    staleTime: 10 * 60_000,
  });
  const [kind, setKind] = useState<KindTab>("전체");
  // ★2026-11-04 사용자 요청: 탭 옆 작은 확대 버튼 — 누르면 표를 화면 전체로 채운다(Esc 로 닫기).
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);
  const d = q.data;
  const soon = d?.jobs.filter((j) => {
    const n = dday(j.deadline, d.today);
    return n != null && n <= 3;
  }).length;
  const hidden = d ? Object.entries(d.hidden_by_category) : [];

  return (
    <>
      <Topbar
        title="채용 공고"
        subtitle="금융권 신입·인턴 — 지금 지원 가능한 공고"
        showAccountContext={false}
      />
      <PageContainer wide>
        {q.isLoading && (
          <p className="py-10 text-center text-[12px] text-ink-muted">
            공고를 불러오는 중…
          </p>
        )}
        {q.isError && (
          <p className="text-[12px] font-bold text-status-failed">
            {(q.error as Error).message}
          </p>
        )}
        {d && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-hairline bg-canvas px-4 py-2.5 text-[12px] text-ink-secondary shadow-card">
              <span>
                수집{" "}
                <b className="text-ink">
                  {d.generated_at?.replace("T", " ").slice(0, 16) ?? "—"}
                </b>
                {d.since && <> · {d.since} 이후 등록</>}
              </span>
              <span className="flex flex-wrap gap-x-2.5">
                {d.sources.map((s) => (
                  <a
                    key={s.key}
                    href={s.url || undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={cn(
                      "hover:underline",
                      s.error && "text-status-failed",
                    )}
                    title={s.error ?? undefined}
                  >
                    {s.name} {s.error ? "수집 실패" : `${s.count}건`}
                  </a>
                ))}
              </span>
              <span>
                지원 가능 <b className="text-ink">{d.jobs.length}건</b>
                {soon ? (
                  <>
                    {" "}
                    ·{" "}
                    <b className="text-status-failed">마감 3일 이내 {soon}건</b>
                  </>
                ) : null}
                {d.closed_dropped > 0 && (
                  <> · 마감 지남 {d.closed_dropped}건 제외</>
                )}
              </span>
              {hidden.length > 0 && (
                <span className="text-ink-muted">
                  관심 외 숨김:{" "}
                  {hidden.map(([k, n]) => `${k} ${n}`).join(" · ")}
                </span>
              )}
            </div>
            <div
              className={cn(
                full && "fixed inset-0 z-50 !mt-0 overflow-hidden bg-canvas-soft p-2",
              )}
            >
              <StubCard
                title="공고 목록"
                subtitle="열 머리를 누르면 오름차순 → 내림차순 정렬"
                action={
                  <div className="ml-auto flex gap-1">
                    {KIND_TABS.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setKind(t)}
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-[11px] font-bold transition-colors",
                          kind === t
                            ? "bg-white text-brand"
                            : "bg-white/15 text-white hover:bg-white/25",
                        )}
                      >
                        {t} {d.jobs.filter((j) => inKind(j, t)).length}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setFull((v) => !v)}
                      title={full ? "원래 크기로 (Esc)" : "화면 가득 보기"}
                      aria-label={full ? "원래 크기로" : "화면 가득 보기"}
                      className="ml-0.5 rounded-full bg-white/15 p-1 text-white transition-colors hover:bg-white/25"
                    >
                      {full ? (
                        <Minimize2 className="h-3 w-3" />
                      ) : (
                        <Maximize2 className="h-3 w-3" />
                      )}
                    </button>
                  </div>
                }
              >
                <div className="p-3">
                  <ExcelTable
                    rows={d.jobs.filter((j) => inKind(j, kind))}
                    columns={columns(d.today)}
                    rowKey={(r, i) => `${r.url}-${i}`}
                    maxHeight={full ? "calc(100vh - 92px)" : undefined}
                  />
                </div>
              </StubCard>
            </div>
          </div>
        )}
      </PageContainer>
    </>
  );
}
