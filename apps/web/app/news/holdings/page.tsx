"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import type { StackColumn } from "@/components/charts/stacked-bar-chart";
import { DayBarChart } from "@/components/charts/day-bar-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  Emphasized,
  ListButton,
  NotConnectedBanner,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getHoldingsNews, type News, type NewsArticle } from "@/lib/api";
import { cn } from "@/lib/utils";

// 보유 종목 뉴스 — 내 포지션에 걸린 일.
//
// ★키가 필요 없다(구글 뉴스 RSS). 검색어는 SEC 영문 법인명에서 등기 접미사를
//   걷어내 만든다 — 실측: `"CORNING INC /NY"` 14건 → `"CORNING"` 100건.
//
// ⚠️**ETF 는 넣지 않았다.** 실측 제목 언급 비율이 EETH 15% · TSL 33% · GLD 43%
//   였고, TSL 검색은 아예 다른 회사 기사를 물어 왔다.
//
// ⚠️한 기사가 여러 종목에 걸릴 수 있다(실측: CRWV/NBIS 비교 기사 2건).
//   두 줄로 늘어놓으면 화면이 고장 난 것처럼 보이고, 하나를 지우면 다른 종목의
//   뉴스가 사라진다 — 한 줄로 합치고 종목 칩을 여러 개 단다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 본문은 막대, 기사 목록은 막대·
//   요약 칸·종목 행을 눌러 여는 팝업. ⚠️단 **월별이 아니라 일별**이다 — 서버가
//   최근 7일 치만 준다(실측 85건, 09-19~09-25). 월로 묶으면 막대가 1개다.
//   ⚠️막대는 종목별로 쌓지 않는다 — 여러 종목에 걸린 기사가 두 번 세여 막대가
//   부푼다. 기사 수 그대로 세고, 종목 구분은 팝업의 칩으로 본다.

function hoursAgo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? (Date.now() - t) / 3_600_000 : null;
}

function whenLabel(iso: string | null): string {
  const h = hoursAgo(iso);
  // ⚠️시각을 모르면 "지금"으로 채우지 않는다 — 최신인 척하게 된다.
  if (h == null) return "시각 미상";
  if (h < 1) return "방금";
  if (h < 24) return `${Math.floor(h)}시간 전`;
  const d = Math.floor(h / 24);
  return d === 1 ? "어제" : `${d}일 전`;
}

export default function HoldingsNewsPage() {
  const { accountId, connected } = useAccount();
  const [notesOpen, setNotesOpen] = useState(false);
  // 막대·요약 칸·종목 행 → 그 범위의 기사 목록. null 이면 닫힘.
  const [scope, setScope] = useState<ListScope | null>(null);

  const news = useQuery({
    queryKey: ["holdingsNews", accountId],
    queryFn: () => getHoldingsNews(accountId),
    // 서버가 30분 캐시를 들고 있다. 화면에서 더 자주 물을 이유가 없다.
    staleTime: 15 * 60_000,
  });

  const data = news.data;
  const all = data?.articles ?? [];
  const rows = all.filter((a) => scope != null && matchScope(a, scope));
  const today = all.filter((a) => {
    const h = hoursAgo(a.published_at);
    return h != null && h <= 24;
  });
  const covered = (data?.tickers ?? []).filter((t) => t.covered);
  const sourceDown = !news.isLoading && (news.isError || data?.source_ok === false);
  const dayColumns = useMemo(() => dailyColumns(data?.articles ?? []), [data]);
  const undated = all.filter((a) => dayKey(a.published_at) == null).length;
  const ranked = [...covered].sort((a, b) => b.article_count - a.article_count);
  const topTicker = ranked[0];
  // ⚠️1등이 여럿이면 하나를 골라 "가장 많다"고 적지 않는다.
  const tiedTop = ranked.filter((t) => t.article_count === topTicker?.article_count).length;

  const emptyText = news.isLoading
    ? "불러오는 중…"
    : sourceDown
      ? "구글 뉴스에서 받지 못했습니다"
      : connected
        ? "이 구간에 기사가 없습니다"
        : "계좌를 연동하면 보유 종목 뉴스가 표시됩니다";

  return (
    <>
      <Topbar title="보유종목 뉴스" subtitle="내 포지션에 걸린 일" />
      <PageContainer fit>
        {!connected && !news.isLoading && <NotConnectedBanner what="보유 종목" />}
        {sourceDown && connected && (
          <SourceDownBanner
            source="구글 뉴스"
            detail="수집 실패"
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 24시간"
            value={data ? `${today.length}건` : null}
            hint={
              data ? `${data.window_days}일 내 전체 ${data.articles.length}건` : "새 기사"
            }
            actionHint="눌러서 목록 보기"
            onClick={() => setScope({ kind: "recent" })}
            loading={news.isLoading}
          />
          <StatTile
            label="가장 많이 나온 종목"
            value={
              data
                ? !topTicker || topTicker.article_count === 0
                  ? "—"
                  : tiedTop > 1
                    ? `${tiedTop}종목 동률`
                    : topTicker.ticker
                : null
            }
            hint={
              data
                ? `${topTicker?.article_count ?? 0}건 · 다룬 종목 ${
                    covered.filter((t) => t.article_count > 0).length
                  }/${data.covered_count}`
                : "기사가 있는 종목"
            }
            actionHint={tiedTop > 1 ? "눌러서 전체 목록 보기" : "눌러서 그 종목 기사 보기"}
            onClick={
              topTicker
                ? () =>
                    setScope(
                      tiedTop > 1
                        ? { kind: "all" }
                        : { kind: "ticker", ticker: topTicker.ticker },
                    )
                : undefined
            }
            loading={news.isLoading}
          />
          <StatTile
            label="관련 없어 제외"
            value={data ? `${data.filtered_total}건` : null}
            hint="제목에 종목이 없는 기사"
            actionHint="눌러서 기준 보기"
            onClick={() => setNotesOpen(true)}
            loading={news.isLoading}
          />
          <StatTile
            label="뉴스 대상 아님"
            value={data ? `${data.not_covered_count}종목` : null}
            hint="ETF — 이유는 눌러서"
            actionHint="눌러서 이유 보기"
            onClick={() => setNotesOpen(true)}
            loading={news.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="일별 기사"
            subtitle={`${all.length}건 · 막대를 누르면 그날 기사`}
            action={<ListButton onClick={() => setScope({ kind: "all" })} />}
            scrollBody
          >
            {news.isLoading || all.length === 0 ? (
              <CardEmpty text={emptyText} />
            ) : (
              <DayBarChart
                columns={dayColumns}
                height={420}
                selected={scope?.kind === "day" ? scope.day : null}
                onPick={(day) => setScope({ kind: "day", day })}
              />
            )}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              게시 시각(한국 시간) 기준 · 중복 종목 기사도 1건
              {undated > 0 && ` · 시각 미상 ${undated}건은 목록에만`}
            </p>
          </StubCard>

          <StubCard
            title="종목별"
            subtitle={
              data
                ? `대상 ${data.covered_count} · 제외 ${data.not_covered_count}`
                : "보유 종목"
            }
            scrollBody
          >
            {news.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : (data?.tickers.length ?? 0) === 0 ? (
              <CardEmpty text="보유 종목이 없습니다" />
            ) : (
              <Coverage
                data={data!}
                onPick={(t) => setScope({ kind: "ticker", ticker: t })}
                onExplain={() => setNotesOpen(true)}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={scope != null}
        onClose={() => setScope(null)}
        title={scope ? scopeTitle(scope, data) : ""}
        subtitle={`${rows.length}건 · 최근이 위 · 제목을 누르면 원문`}
        width={860}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["종목", "제목", "매체", "시점"]}
            align={["left", "left", "left", "right"]}
            empty={emptyText}
          >
            {rows.map((a) => (
              <tr
                key={a.url}
                className="border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  {/* ⚠️여러 종목에 걸린 기사는 칩을 여러 개 단다. */}
                  <span className="flex flex-wrap items-center gap-1">
                    {a.tickers.map((t) => (
                      <span
                        key={t}
                        className="shrink-0 rounded bg-ge-navy/10 px-1.5 py-0.5 text-[10px] font-extrabold text-ge-navy"
                      >
                        {t}
                      </span>
                    ))}
                  </span>
                </Cell>
                <Cell left>
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    // ⚠️고정 폭(520px)은 카드보다 넓어져 마지막 칸을 잘랐다
                    //   (실측 817px vs 카드 788px). 화면에 따라 줄어들게 둔다.
                    className="block max-w-[60vw] truncate font-semibold text-ink hover:text-ge-point hover:underline lg:max-w-[460px]"
                    title={a.title}
                  >
                    {a.title}
                  </a>
                </Cell>
                <Cell left tone="muted">
                  <span className="block max-w-[110px] truncate text-[11px]">
                    {a.publisher ?? "—"}
                  </span>
                </Cell>
                <Cell
                  tone={
                    (hoursAgo(a.published_at) ?? 999) <= 24 ? undefined : "muted"
                  }
                >
                  {whenLabel(a.published_at)}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면 읽는 법"
      >
        <ul className="space-y-2">
          {(data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                <Emphasized text={text} />
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function Coverage({
  data,
  onPick,
  onExplain,
}: {
  data: News;
  onPick: (t: string) => void;
  onExplain: () => void;
}) {
  const covered = data.tickers.filter((t) => t.covered);
  const notCovered = data.tickers.filter((t) => !t.covered);
  const failed = covered.filter((t) => !t.ok);

  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.ticker).join(", ")} 받지 못함 · 기사 없음과는 다름
        </p>
      )}

      <DataTable
        columns={["종목", "기사", "제외"]}
        align={["left", "right", "right"]}
        empty="표시할 종목이 없습니다"
      >
        {covered.map((t) => (
          <tr
            key={t.ticker}
            onClick={() => onPick(t.ticker)}
            className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
          >
            <Cell left strong>
              <span className="flex items-center gap-1.5">
                <span className="max-w-[110px] truncate">{t.name ?? t.ticker}</span>
                <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                  {t.ticker}
                </span>
              </span>
            </Cell>
            <Cell strong={t.article_count > 0} tone={t.article_count === 0 ? "muted" : undefined}>
              {t.article_count}
            </Cell>
            {/* 많이 걸러졌다면 그 종목은 검색어가 맞지 않는 것이다. */}
            <Cell tone="muted">{t.filtered_out}</Cell>
          </tr>
        ))}
      </DataTable>

      {notCovered.length > 0 && (
        <div className="rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
          <p className="mb-1 text-[11px] font-bold text-ge-navy">
            뉴스 대상 아님 ({notCovered.length})
          </p>
          <p className="mb-1.5 text-[11px] leading-snug text-ink-muted">
            ETF 검색 정확도 낮음 · <strong>기사 없음 아님</strong>
          </p>
          <div className="flex flex-wrap gap-1">
            {notCovered.map((t) => (
              <span
                key={t.ticker}
                title={t.name ?? undefined}
                className="rounded bg-canvas px-1.5 py-0.5 text-[10px] font-bold text-ink-faint"
              >
                {t.ticker}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={onExplain}
            className="mt-2 text-[11px] font-bold text-ge-point underline-offset-2 hover:underline"
          >
            왜 뺐나 →
          </button>
        </div>
      )}
    </div>
  );
}

type ListScope =
  | { kind: "all" }
  | { kind: "recent" }
  | { kind: "day"; day: string }
  | { kind: "ticker"; ticker: string };

function matchScope(a: NewsArticle, scope: ListScope): boolean {
  switch (scope.kind) {
    case "all":
      return true;
    case "recent": {
      const h = hoursAgo(a.published_at);
      return h != null && h <= 24;
    }
    case "day":
      return dayKey(a.published_at) === scope.day;
    case "ticker":
      return a.tickers.includes(scope.ticker);
  }
}

function scopeTitle(scope: ListScope, data: News | undefined): string {
  switch (scope.kind) {
    case "all":
      return `기사 전체 (최근 ${data?.window_days ?? "—"}일)`;
    case "recent":
      return "최근 24시간 기사";
    case "day":
      return `${scope.day} 기사`;
    case "ticker": {
      const t = data?.tickers.find((x) => x.ticker === scope.ticker);
      return `${t?.name ?? scope.ticker} (${scope.ticker}) 기사`;
    }
  }
}

/** 게시 시각 → 브라우저 현지(한국) 날짜. 시각 미상은 null — 오늘로 채우지 않는다. */
function dayKey(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? localDay(d) : null;
}

function localDay(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** 첫 기사 날부터 오늘까지 **빈 날도 0 막대로** 채운다 — 건너뛰면 조용한 날이 사라진다. */
function dailyColumns(articles: NewsArticle[]): StackColumn[] {
  const acc = new Map<string, number>();
  for (const a of articles) {
    const k = dayKey(a.published_at);
    if (k != null) acc.set(k, (acc.get(k) ?? 0) + 1);
  }
  const keys = [...acc.keys()].sort();
  if (keys.length === 0) return [];
  const days: string[] = [];
  const cur = new Date(`${keys[0]}T00:00:00`);
  const today = localDay(new Date());
  const end = keys[keys.length - 1] > today ? keys[keys.length - 1] : today;
  while (localDay(cur) <= end) {
    days.push(localDay(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return days.map((d) => {
    const n = acc.get(d) ?? 0;
    return {
      key: d,
      label: d,
      total: n,
      segments: n > 0 ? [{ key: "all", label: "기사", value: n }] : [],
    };
  });
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */

