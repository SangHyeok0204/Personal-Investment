"use client";

import Link from "next/link";
import { ArrowRight, FileText, Presentation, Table2 } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useQuery } from "@tanstack/react-query";
import { useAccount } from "@/components/layout/account-context";
import {
  Cell,
  DataTable,
  Emphasized,
  StatRow,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getResearchLibrary } from "@/lib/api";

// 리서치 라이브러리 — 내가 이미 가진 자료를 한곳에서 찾는 자리.
//
// ★아직 파일을 읽지 않는다. 수집기가 지정 폴더(예: ~/Downloads/05_리서치)를 훑어
//   제목·종류·날짜·다루는 종목/산업을 뽑아 DB 에 넣으면 이 화면이 그걸 읽는다.
//   지금은 **어떤 서랍이 있는지**만 고정해 둔다 — 실제 폴더 구조를 그대로 옮겼다.

// 사용자 리서치 폴더(05_리서치)의 실제 구획. 수집기가 붙으면 건수가 채워진다.
const SHELVES = [
  { id: "stocks", label: "종목 리서치", desc: "종목 리스트 · 발표 자료", icon: Table2, href: "/research/stocks" },
  { id: "industry", label: "산업 리서치", desc: "반도체 · AI · ESS", icon: FileText, href: "/research/industry" },
  { id: "insight", label: "인사이트", desc: "시장 코멘터리 덱", icon: Presentation },
  { id: "fund", label: "공모펀드/ETF", desc: "사모재간접 · 액티브ETF", icon: FileText },
  { id: "macro", label: "매크로/MP 회의", desc: "시장 전망 · 하우스뷰", icon: FileText },
];

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-[12px] font-semibold text-ink-faint">
      {text}
    </div>
  );
}

/** 바이트를 사람이 읽는 크기로. 소수 한 자리면 충분하다. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)}${units[unit]}`;
}

export default function ResearchLibraryPage() {
  const { accountId } = useAccount();
  const library = useQuery({
    queryKey: ["research-library", accountId],
    queryFn: () => getResearchLibrary(accountId),
    staleTime: 60_000,
  });

  const docs = library.data?.documents ?? [];
  // '이번 달'은 **수정시각** 기준이다 — 파일을 언제 받았는지는 알 수 없다.
  const thisMonth = new Date().toISOString().slice(0, 7);
  const addedThisMonth = docs.filter((d) =>
    d.modified_at.startsWith(thisMonth),
  ).length;

  return (
    <>
      <Topbar
        title="리서치 라이브러리"
        subtitle="내가 가진 자료를 한곳에서"
        showAccountContext={false}
      />
      <PageContainer wide>
        <StatRow>
          <StatTile
            label="자료 수"
            value={library.data?.configured ? `${docs.length}` : undefined}
            hint={library.data?.configured ? "폴더에서 읽은 문서" : "폴더 미지정"}
            loading={library.isLoading}
          />
          <StatTile
            label="이번 달 추가"
            value={library.data?.configured ? `${addedThisMonth}` : undefined}
            hint="수정시각 기준"
            loading={library.isLoading}
          />
          <StatTile
            label="보유 종목 자료"
            value={
              library.data?.configured ? `${library.data.matched_count}` : undefined
            }
            hint="파일 이름에 내 종목이 있는 것"
            loading={library.isLoading}
          />
          <StatTile
            label="종목 표시 없음"
            value={
              library.data?.configured
                ? `${docs.length - library.data.matched_count}`
                : undefined
            }
            hint="이름만으로는 못 찾은 자료"
            loading={library.isLoading}
          />
        </StatRow>

        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {SHELVES.map((s) => {
            const Icon = s.icon;
            const inner = (
              <>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ge-blue-bg">
                  <Icon className="h-5 w-5 text-ge-point" strokeWidth={2} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-extrabold text-ge-navy">
                    {s.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] font-medium text-ink-faint">
                    {s.desc}
                  </span>
                </span>
                <span className="shrink-0 text-[12px] font-bold tabular-nums text-ink-faint">
                  —
                </span>
              </>
            );
            const cls =
              "flex items-center gap-3 rounded-2xl border border-hairline bg-canvas px-4 py-3.5 shadow-card transition-colors";
            return s.href ? (
              <Link key={s.id} href={s.href} className={`${cls} hover:bg-ge-blue-bg`}>
                {inner}
              </Link>
            ) : (
              <div key={s.id} className={`${cls} opacity-70`}>
                {inner}
              </div>
            );
          })}
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <StubCard
            title="최근 추가"
            subtitle={
              library.data?.configured
                ? `${docs.length}건 · 최근 수정순`
                : "읽지 않은 자료 먼저"
            }
            scrollBody
          >
            {library.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : !library.data?.configured ? (
              /* ⚠️"준비 중"만 적힌 화면은 영영 안 채워진다. **무엇을 하면
                 켜지는지**를 그 자리에 적는다. */
              <div className="flex h-40 flex-col justify-center gap-2 px-1">
                <p className="text-[12px] font-bold text-ge-navy">
                  자료 폴더를 아직 정하지 않았습니다
                </p>
                <p className="text-[11px] leading-relaxed text-ink-secondary">
                  {/* 서버 문구에도 `**강조**` 가 들어 있다 — 별표를 그대로 찍지 않는다. */}
                  <Emphasized text={library.data?.setup_hint ?? ""} />
                </p>
              </div>
            ) : library.data.problem ? (
              <div className="flex h-40 flex-col justify-center gap-1.5 px-1">
                <p className="text-[12px] font-bold text-ask">
                  {library.data.problem}
                </p>
                <p className="text-[11px] text-ink-faint">{library.data.root}</p>
              </div>
            ) : docs.length === 0 ? (
              <Empty text="그 폴더에 읽을 만한 자료가 없습니다" />
            ) : (
              <>
                {library.data.truncated && (
                  <p className="mb-2 rounded-lg bg-ask-soft px-2.5 py-1.5 text-[11px] font-semibold text-ask">
                    일부만 표시 · 전체 아님
                  </p>
                )}
                <DataTable
                  columns={["자료", "종목", "수정"]}
                  align={["left", "left", "right"]}
                >
                  {docs.slice(0, 40).map((d) => (
                    <tr key={d.relative_path} className="border-b border-hairline">
                      <Cell left strong>
                        <span className="block max-w-[320px] truncate">{d.name}</span>
                        <span className="block text-[10px] font-medium text-ink-faint">
                          {d.extension.toUpperCase()} · {formatBytes(d.size_bytes)}
                        </span>
                      </Cell>
                      <Cell left tone={d.tickers.length ? undefined : "muted"}>
                        {d.tickers.length ? d.tickers.join(", ") : "—"}
                      </Cell>
                      <Cell tone="muted">{d.modified_at.slice(0, 10)}</Cell>
                    </tr>
                  ))}
                </DataTable>
              </>
            )}
          </StubCard>
        </div>

        <div className="mt-4">
          <Link
            href="/research/industry"
            className="group inline-flex items-center gap-2 text-[13px] font-bold text-ge-point transition-colors hover:text-ge-navy"
          >
            반도체 · AI 산업 리서치로
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </PageContainer>
    </>
  );
}
