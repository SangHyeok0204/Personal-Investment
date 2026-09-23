"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  Emphasized,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getMarketNews, type MarketNews } from "@/lib/api";
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
  const [topic, setTopic] = useState<string | null>(null);
  const [hideSeen, setHideSeen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);

  const news = useQuery({
    queryKey: ["marketNews", lang],
    queryFn: () => getMarketNews(lang),
    staleTime: 15 * 60_000,
  });

  const data = news.data;
  const rows = useMemo(() => {
    let list = data?.articles ?? [];
    if (topic != null) list = list.filter((a) => a.topic === topic);
    // 보유종목 뉴스에서 이미 봤을 기사를 숨긴다(지우지는 않는다).
    if (hideSeen) list = list.filter((a) => a.holdings.length === 0);
    return list;
  }, [data, topic, hideSeen]);

  const today = (data?.articles ?? []).filter((a) => {
    const h = hoursAgo(a.published_at);
    return h != null && h <= 24;
  });
  const sourceDown = !news.isLoading && (news.isError || data?.source_ok === false);

  return (
    <>
      <Topbar
        title="시장 뉴스"
        subtitle="내가 아직 안 산 쪽에서 무슨 일이 있나"
        showAccountContext={false}
      />
      <PageContainer fit>
        {sourceDown && (
          <SourceDownBanner
            source="구글 뉴스"
            detail="받지 못했으므로 아래가 비어 있어도 '뉴스 없음'이 아닙니다."
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 24시간"
            value={data ? `${today.length}건` : null}
            hint={data ? `${data.window_days}일 내 전체 ${data.articles.length}건` : "새 기사"}
            loading={news.isLoading}
          />
          <StatTile
            label="주제"
            value={data ? `${data.topics.length}개` : null}
            hint="반도체 · AI · 전력 · 금리 · 크립토"
            loading={news.isLoading}
          />
          <StatTile
            label="내 종목이 걸린 기사"
            value={data ? `${data.holdings_hit_count}건` : null}
            hint="보유종목 뉴스에서 이미 봤을 수 있음"
            actionHint="눌러서 기준 보기"
            onClick={() => setNotesOpen(true)}
            loading={news.isLoading}
          />
          <StatTile
            label="주제와 무관해 제외"
            value={data ? `${data.filtered_total}건` : null}
            hint="제목에 주제어가 없는 기사"
            loading={news.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="기사"
            subtitle={`${rows.length}건 · 최근이 위 · 눌러서 원문`}
            scrollBody
            action={
              <div className="flex shrink-0 items-center gap-1">
                <Chip active={topic == null} onClick={() => setTopic(null)}>
                  전체
                </Chip>
                {(data?.topics ?? []).map((t) => (
                  <Chip
                    key={t.key}
                    active={topic === t.key}
                    onClick={() => setTopic(t.key)}
                  >
                    {t.label}
                  </Chip>
                ))}
                <span className="mx-1 h-3.5 w-px shrink-0 bg-white/25" />
                <Chip active={lang === "ko"} onClick={() => setLang("ko")}>
                  한
                </Chip>
                <Chip active={lang === "en"} onClick={() => setLang("en")}>
                  EN
                </Chip>
              </div>
            }
          >
            <DataTable
              columns={["주제", "제목", "매체", "시점"]}
              align={["left", "left", "left", "right"]}
              empty={
                news.isLoading
                  ? "불러오는 중…"
                  : sourceDown
                    ? "구글 뉴스에서 받지 못했습니다"
                    : hideSeen
                      ? "내 종목이 안 걸린 기사가 없습니다"
                      : "이 구간에 기사가 없습니다"
              }
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
                      className="block max-w-[52vw] truncate font-semibold text-ink hover:text-ge-point hover:underline lg:max-w-[26vw]"
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
          </StubCard>

          <StubCard title="주제별" subtitle={`${lang === "ko" ? "한국어" : "영어"} 검색`} scrollBody>
            {news.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : data == null ? (
              <Empty text="표시할 주제가 없습니다" />
            ) : (
              <Topics
                data={data}
                selected={topic}
                onSelect={setTopic}
                hideSeen={hideSeen}
                onToggleSeen={() => setHideSeen((v) => !v)}
                onExplain={() => setNotesOpen(true)}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면 읽는 법"
        subtitle="보유종목 뉴스와 무엇이 다른가"
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

function Topics({
  data,
  selected,
  onSelect,
  hideSeen,
  onToggleSeen,
  onExplain,
}: {
  data: MarketNews;
  selected: string | null;
  onSelect: (t: string | null) => void;
  hideSeen: boolean;
  onToggleSeen: () => void;
  onExplain: () => void;
}) {
  const failed = data.topics.filter((t) => !t.ok);
  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.label).join(", ") } 은(는) 받지 못했습니다 — 기사가
          없는 것이 아닙니다.
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
            onClick={() => onSelect(selected === t.key ? null : t.key)}
            className={cn(
              "cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft",
              selected === t.key && "bg-canvas-soft",
            )}
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

      <button
        type="button"
        onClick={onToggleSeen}
        className={cn(
          "w-full rounded-lg border px-3 py-2 text-[11px] font-bold transition-colors",
          hideSeen
            ? "border-ge-navy bg-ge-navy text-white"
            : "border-hairline bg-canvas text-ink-secondary hover:bg-canvas-soft",
        )}
      >
        {hideSeen ? "내 종목 기사 다시 보기" : `내 종목 기사 숨기기 (${data.holdings_hit_count})`}
      </button>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        보유종목 뉴스에서 이미 본 기사를 여기서 또 읽지 않도록 표시합니다.{" "}
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

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full px-2 py-1 text-[10px] font-bold transition-colors",
        active ? "bg-white text-ge-navy" : "bg-white/15 text-white hover:bg-white/25",
      )}
    >
      {children}
    </button>
  );
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
