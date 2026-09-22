"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  SourceDownBanner,
  StatTile,
  StubCard,
} from "@/components/stub";
import { getHoldingsNews, type News } from "@/lib/api";
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
  const [ticker, setTicker] = useState<string | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);

  const news = useQuery({
    queryKey: ["holdingsNews", accountId],
    queryFn: () => getHoldingsNews(accountId),
    // 서버가 30분 캐시를 들고 있다. 화면에서 더 자주 물을 이유가 없다.
    staleTime: 15 * 60_000,
  });

  const data = news.data;
  const rows = useMemo(
    () =>
      (data?.articles ?? []).filter(
        (a) => ticker == null || a.tickers.includes(ticker),
      ),
    [data, ticker],
  );
  const today = (data?.articles ?? []).filter((a) => {
    const h = hoursAgo(a.published_at);
    return h != null && h <= 24;
  });
  const covered = (data?.tickers ?? []).filter((t) => t.covered);
  const sourceDown = !news.isLoading && (news.isError || data?.source_ok === false);

  return (
    <>
      <Topbar title="보유종목 뉴스" subtitle="내 포지션에 걸린 일" />
      <PageContainer fit>
        {!connected && !news.isLoading && <NotConnectedBanner what="보유 종목" />}
        {sourceDown && connected && (
          <SourceDownBanner
            source="구글 뉴스"
            detail="받지 못했으므로 아래가 비어 있어도 '뉴스 없음'이 아닙니다."
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 24시간"
            value={data ? `${today.length}건` : null}
            hint={
              data ? `${data.window_days}일 내 전체 ${data.articles.length}건` : "새 기사"
            }
            loading={news.isLoading}
          />
          <StatTile
            label="다룬 종목"
            value={data ? `${covered.filter((t) => t.article_count > 0).length}종목` : null}
            hint={data ? `조회 대상 ${data.covered_count}종목` : "기사가 있는 종목"}
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
            title="기사"
            subtitle={`${rows.length}건 · 최근이 위 · 눌러서 원문`}
            scrollBody
            action={
              <div className="flex shrink-0 gap-1 overflow-x-auto">
                <Chip active={ticker == null} onClick={() => setTicker(null)}>
                  전체
                </Chip>
                {covered
                  .filter((t) => t.article_count > 0)
                  .map((t) => (
                    <Chip
                      key={t.ticker}
                      active={ticker === t.ticker}
                      onClick={() => setTicker(t.ticker)}
                    >
                      {t.ticker}
                    </Chip>
                  ))}
              </div>
            }
          >
            <DataTable
              columns={["종목", "제목", "매체", "시점"]}
              align={["left", "left", "left", "right"]}
              empty={
                news.isLoading
                  ? "불러오는 중…"
                  : sourceDown
                    ? "구글 뉴스에서 받지 못했습니다"
                    : connected
                      ? "이 구간에 기사가 없습니다"
                      : "계좌를 연동하면 보유 종목 뉴스가 표시됩니다"
              }
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
                      className="block max-w-[52vw] truncate font-semibold text-ink hover:text-ge-point hover:underline lg:max-w-[28vw]"
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
          </StubCard>

          <StubCard
            title="종목별"
            subtitle={
              data ? `대상 ${data.covered_count} · 제외 ${data.not_covered_count}` : "보유 종목"
            }
            scrollBody
          >
            {news.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.tickers.length ?? 0) === 0 ? (
              <Empty text="보유 종목이 없습니다" />
            ) : (
              <Coverage
                data={data!}
                selected={ticker}
                onSelect={setTicker}
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
        subtitle="무엇을 빼고 무엇을 남겼나"
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
  selected,
  onSelect,
  onExplain,
}: {
  data: News;
  selected: string | null;
  onSelect: (t: string | null) => void;
  onExplain: () => void;
}) {
  const covered = data.tickers.filter((t) => t.covered);
  const notCovered = data.tickers.filter((t) => !t.covered);
  const failed = covered.filter((t) => !t.ok);

  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.ticker).join(", ")} 은(는) 받지 못했습니다 — 기사가
          없는 것이 아닙니다.
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
            onClick={() => onSelect(selected === t.ticker ? null : t.ticker)}
            className={cn(
              "cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft",
              selected === t.ticker && "bg-canvas-soft",
            )}
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
            ETF 는 검색 정확도가 너무 낮습니다.{" "}
            <strong>기사가 없는 것이 아닙니다.</strong>
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
function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="text-ink">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
