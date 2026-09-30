"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import type { StackColumn } from "@/components/charts/stacked-bar-chart";
import { DayBarChart } from "@/components/charts/day-bar-chart";
import { colorForKeys } from "@/components/charts/donut-chart";
import {
  CardEmpty,
  Cell,
  DataTable,
  Emphasized,
  HeaderChip,
  ListButton,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getMarketNews, type MarketNews, type TopicArticle } from "@/lib/api";
import { cn } from "@/lib/utils";

// 시장 뉴스 — 내가 **아직 안 산 쪽에서** 무슨 일이 있나.
//
// ★보유종목 뉴스와 같은 소스(구글 뉴스 RSS)지만 답하는 질문이 다르다.
//   거기는 "내 종목에 무슨 일이 있었나", 여기는 "판이 어떻게 돌아가는가"다.
//
// ★**한국어를 쓴다.** 종목 검색에서는 한국어가 무너졌지만(최저 32% HUT),
//   주제 검색은 97~100% 다(실측) — 주제어가 모호하지 않기 때문이다.
//   한국 매체가 국내 공급망(한미반도체·하이닉스)을 먼저 다루므로 오히려 유용하다.
//
// ⚠️제목에 걸린 보유 종목을 표시한다 — 보유종목 뉴스에서 이미 본 기사를
//   여기서 또 읽지 않도록.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 본문은 막대, 기사 목록은 막대·
//   요약 칸·주제 행을 눌러 여는 팝업. ⚠️단 **월별이 아니라 일별**이다 — 서버가
//   최근 3일 치만 준다(실측 58건, 09-22~09-25). 월로 묶으면 막대가 1개라 아무것도
//   보여 주지 못한다.

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

export default function MarketNewsPage() {
  const [lang, setLang] = useState<"ko" | "en">("ko");
  const [hideSeen, setHideSeen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  // 막대·요약 칸·주제 행 → 그 범위의 기사 목록. null 이면 닫힘.
  const [scope, setScope] = useState<ListScope | null>(null);

  const news = useQuery({
    queryKey: ["marketNews", lang],
    queryFn: () => getMarketNews(lang),
    staleTime: 15 * 60_000,
  });

  const data = news.data;
  const all = data?.articles ?? [];
  const rows = useMemo(() => {
    if (scope == null) return [];
    let list = (data?.articles ?? []).filter((a) => matchScope(a, scope));
    // 보유종목 뉴스에서 이미 봤을 기사를 숨긴다(지우지는 않는다).
    if (hideSeen && scope.kind !== "holdings") {
      list = list.filter((a) => a.holdings.length === 0);
    }
    return list;
  }, [data, scope, hideSeen]);

  const today = all.filter((a) => {
    const h = hoursAgo(a.published_at);
    return h != null && h <= 24;
  });
  const sourceDown = !news.isLoading && (news.isError || data?.source_ok === false);
  const topicColors = useMemo(
    () => colorForKeys((data?.topics ?? []).map((t) => t.key)),
    [data],
  );
  const dayColumns = useMemo(() => dailyColumns(data), [data]);
  const undated = all.filter((a) => dayKey(a.published_at) == null).length;
  const ranked = [...(data?.topics ?? [])].sort((a, b) => b.article_count - a.article_count);
  const topTopic = ranked[0];
  // ⚠️1등이 여럿이면 하나를 골라 "가장 많다"고 적지 않는다(실측: 5주제 모두 12건).
  const tiedTop = ranked.filter((t) => t.article_count === topTopic?.article_count).length;

  const emptyText = news.isLoading
    ? "불러오는 중…"
    : sourceDown
      ? "구글 뉴스에서 받지 못했습니다"
      : hideSeen
        ? "내 종목이 안 걸린 기사가 없습니다"
        : "이 구간에 기사가 없습니다";

  return (
    <>
      <Topbar
        title="시장 뉴스"
        showAccountContext={false}
      />
      <PageContainer fit>
        {sourceDown && (
          <SourceDownBanner
            source="구글 뉴스"
            detail="수집 실패"
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 24시간"
            value={data ? `${today.length}건` : null}
            hint={data ? `${data.window_days}일 내 전체 ${data.articles.length}건` : "새 기사"}
            actionHint="눌러서 목록 보기"
            onClick={() => setScope({ kind: "recent" })}
            loading={news.isLoading}
          />
          <StatTile
            label="가장 많은 주제"
            value={
              data
                ? !topTopic || topTopic.article_count === 0
                  ? "—"
                  : tiedTop > 1
                    ? `${tiedTop}개 동률`
                    : topTopic.label
                : null
            }
            hint={
              data && topTopic
                ? tiedTop > 1
                  ? `주제마다 ${topTopic.article_count}건 · 주제 ${data.topics.length}개 중`
                  : `${topTopic.article_count}건 · 주제 ${data.topics.length}개 중`
                : "반도체 · AI · 전력 · 금리 · 크립토"
            }
            actionHint={tiedTop > 1 ? "눌러서 전체 목록 보기" : "눌러서 그 주제 기사 보기"}
            onClick={
              topTopic
                ? () =>
                    setScope(
                      tiedTop > 1 ? { kind: "all" } : { kind: "topic", topic: topTopic.key },
                    )
                : undefined
            }
            loading={news.isLoading}
          />
          <StatTile
            label="내 종목이 걸린 기사"
            value={data ? `${data.holdings_hit_count}건` : null}
            hint="보유종목 뉴스에서 이미 봤을 수 있음"
            actionHint="눌러서 목록 보기"
            onClick={() => setScope({ kind: "holdings" })}
            loading={news.isLoading}
          />
          <StatTile
            label="주제와 무관해 제외"
            value={data ? `${data.filtered_total}건` : null}
            hint="제목에 주제어가 없는 기사"
            actionHint="눌러서 기준 보기"
            onClick={() => setNotesOpen(true)}
            loading={news.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="일별 기사"
            subtitle={`${all.length}건 · 막대를 누르면 그날 기사`}
            scrollBody
            action={
              <div className="flex shrink-0 items-center gap-1">
                <HeaderChip active={lang === "ko"} onClick={() => setLang("ko")}>
                  한
                </HeaderChip>
                <HeaderChip active={lang === "en"} onClick={() => setLang("en")}>
                  EN
                </HeaderChip>
                <span className="mx-1 h-3.5 w-px shrink-0 bg-white/25" />
                <ListButton onClick={() => setScope({ kind: "all" })} />
              </div>
            }
          >
            {news.isLoading || all.length === 0 ? (
              <CardEmpty
                text={
                  news.isLoading
                    ? "불러오는 중…"
                    : sourceDown
                      ? "구글 뉴스에서 받지 못했습니다"
                      : "이 구간에 기사가 없습니다"
                }
              />
            ) : (
              <DayBarChart
                columns={dayColumns}
                colors={topicColors}
                height={420}
                selected={scope?.kind === "day" ? scope.day : null}
                onPick={(day) => setScope({ kind: "day", day })}
              />
            )}
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">
              {(data?.topics ?? []).map((t) => (
                <span key={t.key} className="mr-2 inline-flex items-center gap-1">
                  <span style={{ color: topicColors[t.key] }} className="font-bold">
                    ■
                  </span>
                  {t.label}
                </span>
              ))}
              · 게시 시각(한국 시간) 기준
              {undated > 0 && ` · 시각 미상 ${undated}건은 목록에만`}
            </p>
          </StubCard>

          <StubCard
            title="주제별"
            subtitle={`${lang === "ko" ? "한국어" : "영어"} 검색 · 행을 누르면 그 주제 기사`}
            scrollBody
          >
            {news.isLoading ? (
              <CardEmpty text="불러오는 중…" />
            ) : data == null ? (
              <CardEmpty text="표시할 주제가 없습니다" />
            ) : (
              <Topics
                data={data}
                onPick={(topic) => setScope({ kind: "topic", topic })}
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
        {scope?.kind !== "holdings" && (
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setHideSeen((v) => !v)}
              aria-pressed={hideSeen}
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors",
                hideSeen
                  ? "bg-ge-header text-white"
                  : "bg-canvas-soft text-ink-secondary hover:bg-ge-blue-bg",
              )}
            >
              {hideSeen ? "내 종목 기사 다시 보기" : "내 종목 기사 숨기기"}
            </button>
            <button
              type="button"
              onClick={() => setNotesOpen(true)}
              className="text-[11px] font-bold text-ge-point underline-offset-2 hover:underline"
            >
              판정 기준 →
            </button>
          </div>
        )}
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["주제", "제목", "매체", "시점"]}
            align={["left", "left", "left", "right"]}
            empty={emptyText}
          >
            {rows.map((a) => (
              <tr
                key={a.url}
                className="border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  <span className="flex flex-wrap items-center gap-1">
                    <span className="shrink-0 rounded bg-ge-navy/10 px-1.5 py-0.5 text-[10px] font-extrabold text-ge-navy">
                      {a.topic_label}
                    </span>
                    {/* ⚠️보유종목 뉴스에서 이미 봤을 기사임을 표시한다. */}
                    {a.holdings.map((h) => (
                      <span
                        key={h}
                        title="보유 종목입니다 — 보유종목 뉴스에서 이미 보셨을 수 있습니다."
                        className="shrink-0 cursor-help rounded bg-ge-point/12 px-1 py-0.5 text-[9px] font-extrabold text-ge-point"
                      >
                        {h}
                      </span>
                    ))}
                  </span>
                </Cell>
                <Cell left>
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block max-w-[60vw] truncate font-semibold text-ink hover:text-ge-point hover:underline lg:max-w-[440px]"
                    title={a.title}
                  >
                    {a.title}
                  </a>
                </Cell>
                <Cell left tone="muted">
                  <span className="block max-w-[100px] truncate text-[11px]">
                    {a.publisher ?? "—"}
                  </span>
                </Cell>
                <Cell tone={(hoursAgo(a.published_at) ?? 999) <= 24 ? undefined : "muted"}>
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

type ListScope =
  | { kind: "all" }
  | { kind: "recent" }
  | { kind: "holdings" }
  | { kind: "day"; day: string }
  | { kind: "topic"; topic: string };

function matchScope(a: TopicArticle, scope: ListScope): boolean {
  switch (scope.kind) {
    case "all":
      return true;
    case "recent": {
      const h = hoursAgo(a.published_at);
      return h != null && h <= 24;
    }
    case "holdings":
      return a.holdings.length > 0;
    case "day":
      return dayKey(a.published_at) === scope.day;
    case "topic":
      return a.topic === scope.topic;
  }
}

function scopeTitle(scope: ListScope, data: MarketNews | undefined): string {
  switch (scope.kind) {
    case "all":
      return `기사 전체 (최근 ${data?.window_days ?? "—"}일)`;
    case "recent":
      return "최근 24시간 기사";
    case "holdings":
      return "내 종목이 걸린 기사";
    case "day":
      return `${scope.day} 기사`;
    case "topic": {
      const t = data?.topics.find((x) => x.key === scope.topic);
      return `${t?.label ?? scope.topic} 기사`;
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
function dailyColumns(data: MarketNews | undefined): StackColumn[] {
  if (!data) return [];
  const acc = new Map<string, Map<string, number>>();
  for (const a of data.articles) {
    const k = dayKey(a.published_at);
    if (k == null) continue;
    const e = acc.get(k) ?? new Map<string, number>();
    e.set(a.topic, (e.get(a.topic) ?? 0) + 1);
    acc.set(k, e);
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
  const labels = new Map(data.topics.map((t) => [t.key, t.label]));
  return days.map((d) => {
    const e = acc.get(d) ?? new Map<string, number>();
    return {
      key: d,
      label: d,
      total: [...e.values()].reduce((sum, v) => sum + v, 0),
      segments: data.topics
        .map((t) => ({ key: t.key, label: labels.get(t.key) ?? t.key, value: e.get(t.key) ?? 0 }))
        .filter((x) => x.value > 0),
    };
  });
}

function Topics({
  data,
  onPick,
  onExplain,
}: {
  data: MarketNews;
  onPick: (t: string) => void;
  onExplain: () => void;
}) {
  const failed = data.topics.filter((t) => !t.ok);
  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.label).join(", ")} 받지 못함 · 기사 없음과는 다름
        </p>
      )}

      <DataTable
        columns={["주제", "기사", "제외"]}
        align={["left", "right", "right"]}
        empty="표시할 주제가 없습니다"
      >
        {data.topics.map((t) => (
          <tr
            key={t.key}
            onClick={() => onPick(t.key)}
            className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
          >
            <Cell left strong>
              <span className="block truncate">{t.label}</span>
              <span className="block max-w-[150px] truncate text-[10px] font-medium text-ink-faint">
                {t.query}
              </span>
            </Cell>
            <Cell strong={t.article_count > 0} tone={t.article_count === 0 ? "muted" : undefined}>
              {t.article_count}
            </Cell>
            <Cell tone="muted">{t.filtered_out}</Cell>
          </tr>
        ))}
      </DataTable>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        제목에 보유 종목이 걸린 기사 {data.holdings_hit_count}건{" "}
        <button
          type="button"
          onClick={onExplain}
          className="font-bold text-ge-point underline-offset-2 hover:underline"
        >
          판정 기준 →
        </button>
      </p>
    </div>
  );
}

