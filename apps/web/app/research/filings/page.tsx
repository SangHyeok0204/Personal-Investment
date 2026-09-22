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
import { getFilings, type Filings } from "@/lib/api";
import { cn } from "@/lib/utils";

// 공시 — 보유 종목이 SEC 에 무엇을 신고했나.
//
// ★키가 필요 없다. SEC 는 연락처가 담긴 User-Agent 만 요구한다.
//
// ★**내부자 서식을 나열하지 않는다.** 실측(NVDA 최근 1001건): Form 4 가 556건,
//   Form 144 가 247건으로 803건이 임원 서류다. 읽을 만한 건 8-K 62 · 10-Q 19 ·
//   10-K 6 뿐이다. 그대로 쏟으면 중요한 공시가 묻히므로 건수로만 낸다.
//
// ⚠️ETF 는 SEC 개별 공시 대상이 **아니다**(신탁 단위로 낸다). 보유 17종목 중
//   6개가 여기 해당한다 — "공시 없음"으로 적으면 거짓말이 된다.
//   ⚠️단, 전부 그런 건 아니다 — GLD(금 SPDR)는 상품신탁이라 10-K 를 낸다.
//     ETF 라고 하드코딩하지 않고 SEC 에 CIK 가 있는지로만 판단한다.

const CATEGORY_TONE: Record<string, string> = {
  "실적·정기": "bg-ge-navy/10 text-ge-navy",
  수시: "bg-ge-point/12 text-ge-point",
  지분: "bg-bid-soft text-bid",
  기타: "bg-canvas-soft text-ink-faint",
};

function daysAgo(iso: string): number {
  const then = new Date(`${iso}T00:00:00`);
  return Math.floor((Date.now() - then.getTime()) / 86_400_000);
}

function whenLabel(iso: string): string {
  const d = daysAgo(iso);
  if (d <= 0) return "오늘";
  if (d === 1) return "어제";
  if (d < 7) return `${d}일 전`;
  return iso.slice(5);
}

export default function FilingsPage() {
  const { accountId, connected } = useAccount();
  const [category, setCategory] = useState<string | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);

  const filings = useQuery({
    queryKey: ["filings", accountId],
    queryFn: () => getFilings(accountId),
    // SEC 는 보유 종목 수만큼 두드려야 한다. 서버도 1시간 캐시를 들고 있다.
    staleTime: 30 * 60_000,
  });

  const data = filings.data;
  const rows = useMemo(
    () =>
      (data?.filings ?? []).filter(
        (f) => category == null || f.category === category,
      ),
    [data, category],
  );

  const recent30 = (data?.filings ?? []).filter((f) => daysAgo(f.filed_date) <= 30);
  const sourceDown = !filings.isLoading && (filings.isError || data?.source_ok === false);
  const notCovered = (data?.tickers ?? []).filter((t) => t.cik == null);

  return (
    <>
      <Topbar title="공시" subtitle="보유 종목이 SEC 에 무엇을 신고했나" />
      <PageContainer fit>
        {!connected && !filings.isLoading && <NotConnectedBanner what="보유 종목" />}
        {sourceDown && connected && (
          <SourceDownBanner
            source="SEC EDGAR"
            detail="미국 공시 원천입니다. 받지 못했으므로 아래가 비어 있어도 '공시 없음'이 아닙니다."
          />
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="최근 30일 공시"
            value={data ? `${recent30.length}건` : null}
            hint={
              data
                ? `${data.window_days}일 내 전체 ${data.filings.length}건`
                : "내부자 서식 제외"
            }
            loading={filings.isLoading}
          />
          <StatTile
            label="실적·정기"
            value={
              data
                ? `${data.filings.filter((f) => f.category === "실적·정기").length}건`
                : null
            }
            hint="10-K · 10-Q · 20-F"
            loading={filings.isLoading}
          />
          <StatTile
            label="수시보고"
            value={
              data ? `${data.filings.filter((f) => f.category === "수시").length}건` : null
            }
            hint="8-K · 증권신고 · 주총"
            loading={filings.isLoading}
          />
          <StatTile
            label="내부자 서식"
            value={data ? `${data.insider_total}건` : null}
            hint={
              data
                ? `최근 ${data.insider_window_days}일 · 그중 30일 내 ${data.insider_recent_total}건`
                : "3 · 4 · 5 · 144"
            }
            actionHint="눌러서 왜 안 보여주는지"
            onClick={() => setNotesOpen(true)}
            loading={filings.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="공시"
            subtitle={`${rows.length}건 · 최근이 위 · 눌러서 SEC 원문`}
            scrollBody
            action={
              <div className="flex shrink-0 gap-1">
                <Chip active={category == null} onClick={() => setCategory(null)}>
                  전체
                </Chip>
                {(data?.categories ?? []).map((c) => (
                  <Chip
                    key={c}
                    active={category === c}
                    onClick={() => setCategory(c)}
                  >
                    {c}
                  </Chip>
                ))}
              </div>
            }
          >
            <DataTable
              columns={["종목", "공시", "내용", "제출일"]}
              align={["left", "left", "left", "right"]}
              empty={
                filings.isLoading
                  ? "불러오는 중…"
                  : sourceDown
                    ? "SEC 에서 받지 못했습니다"
                    : connected
                      ? "이 구간에 공시가 없습니다"
                      : "계좌를 연동하면 보유 종목 공시가 표시됩니다"
              }
            >
              {rows.map((f) => (
                <tr
                  key={`${f.ticker}-${f.url}`}
                  className="border-b border-hairline transition-colors hover:bg-canvas-soft"
                >
                  <Cell left strong>
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[110px] truncate">
                        {f.company ?? f.ticker}
                      </span>
                      <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                        {f.ticker}
                      </span>
                    </span>
                  </Cell>
                  <Cell left>
                    <span className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold",
                          CATEGORY_TONE[f.category] ?? CATEGORY_TONE["기타"],
                        )}
                      >
                        {f.form}
                      </span>
                      <span className="truncate text-[11px] font-semibold text-ink-secondary">
                        {f.form_label}
                      </span>
                    </span>
                  </Cell>
                  <Cell left tone="muted">
                    {/* 8-K 는 항목 코드가 곧 내용이다. 없으면 비워 둔다 —
                        "내용 없음"이라고 적으면 틀린 말이 된다. */}
                    <span className="block max-w-[260px] truncate text-[11px]">
                      {f.item_labels.length > 0 ? f.item_labels.join(" · ") : "—"}
                    </span>
                  </Cell>
                  <Cell>
                    <a
                      href={f.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-ge-point underline-offset-2 hover:underline"
                    >
                      {whenLabel(f.filed_date)} ↗
                    </a>
                  </Cell>
                </tr>
              ))}
            </DataTable>
          </StubCard>

          <StubCard
            title="종목별"
            subtitle={
              data
                ? `조회 ${data.covered_count} · 대상 아님 ${data.not_covered_count}`
                : "보유 종목"
            }
            scrollBody
          >
            {filings.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.tickers.length ?? 0) === 0 ? (
              <Empty text="보유 종목이 없습니다" />
            ) : (
              <Coverage data={data!} onExplain={() => setNotesOpen(true)} />
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
        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>내부자 서식을 나열하지 않았습니다.</strong> 엔비디아의 최근 공시
            1,001건 중 <strong>803건이 Form 4·144</strong>(임원 주식 거래
            서류)였습니다. 실제로 읽을 만한 건 8-K 62건 · 10-Q 19건 · 10-K 6건
            뿐입니다. 그대로 쏟으면 중요한 공시가 서류 더미에 묻히므로 건수로만
            보여 줍니다{data ? ` (최근 ${data.insider_window_days}일 ${data.insider_total}건)` : ""}.
          </li>
          <li>
            <strong>대신 &quot;몰렸나&quot;는 봅니다.</strong> 고르게 났다면 최근
            1/3 구간(30일)에 33% 쯤 들어옵니다 — 그보다 한참 높으면 무슨 일이
            있었다는 뜻입니다(락업 해제·베스팅·정기 매도 계획 개시 등).
            종목별 표의 <strong>최근 30일</strong> 칸이 그 몫이고, 60% 를 넘으면
            진하게 적습니다.
          </li>
          <li>
            <strong>다만 방향은 모릅니다.</strong> 서식 4 는 매수·매도·부여를 모두
            담는데 SEC <strong>제출 목록에는 그 구분도, 누가 냈는지도 없습니다</strong>
            — 그건 서식 원문을 건마다 받아야 나옵니다. 그래서 이 화면은 &quot;내부자가
            팔고 있다&quot;고 말하지 않습니다. 궁금하면 그 종목의 SEC 페이지를 직접
            여세요.
          </li>
          <li>
            <strong>ETF 는 &quot;공시 없음&quot;이 아닙니다.</strong> 개별 기업 공시
            대상이 아니라 신탁 단위로 냅니다. 다만 전부 그런 건 아니라{" "}
            <strong>ETF 라고 하드코딩하지 않고</strong> SEC 에 CIK 가 있는지로만
            판단합니다 — 실제로 GLD(금 SPDR)는 상품신탁이라 10-K 를 냅니다.
          </li>
          <li>
            <strong>8-K 의 항목 코드를 한국어로 옮겼습니다.</strong>
            &quot;8-K 2.02&quot;는 아무 뜻도 전달하지 못합니다 — &quot;실적
            발표&quot;여야 읽힙니다. 모르는 코드는 지어내지 않고 숫자 그대로 둡니다.
          </li>
          <li>
            <strong>중요도를 우리가 매기지 않았습니다.</strong> 어떤 8-K 가 중요한지는
            내용을 읽어야 알 수 있고, 우리는 그걸 모릅니다. 서식의 성격으로만
            나눕니다.
          </li>
          <li>
            <strong>SEC 는 연락처가 담긴 User-Agent 를 요구합니다.</strong>{" "}
            {data?.user_agent_is_default ? (
              <>
                지금은 앱 이름만으로 요청하고 있습니다 —{" "}
                <strong>회원님 이메일을 말없이 보내지 않습니다.</strong> 정식으로
                요청하려면 <code className="rounded bg-canvas-soft px-1">.env</code> 의{" "}
                <code className="rounded bg-canvas-soft px-1">SEC_USER_AGENT</code> 에
                본인 연락처를 넣으세요.
              </>
            ) : (
              <>
                <code className="rounded bg-canvas-soft px-1">SEC_USER_AGENT</code> 가
                설정돼 있습니다.
              </>
            )}
          </li>
        </ul>
      </Modal>
    </>
  );
}

function Coverage({ data, onExplain }: { data: Filings; onExplain: () => void }) {
  const covered = data.tickers.filter((t) => t.cik != null);
  const notCovered = data.tickers.filter((t) => t.cik == null);
  const failed = data.tickers.filter((t) => !t.ok);

  return (
    <div className="space-y-3">
      {failed.length > 0 && (
        <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold leading-snug text-ask">
          {failed.map((t) => t.ticker).join(", ")} 은(는) 받지 못했습니다 —
          공시가 없는 것이 아닙니다.
        </p>
      )}

      <DataTable
        columns={["종목", "공시", "내부자", "최근 30일"]}
        align={["left", "right", "right"]}
        empty="표시할 종목이 없습니다"
      >
        {covered.map((t) => (
          <tr key={t.ticker} className="border-b border-hairline">
            <Cell left strong>
              <span className="flex items-center gap-1.5">
                <span className="max-w-[110px] truncate">{t.name ?? t.ticker}</span>
                <span className="shrink-0 text-[10px] font-bold text-ink-faint">
                  {t.ticker}
                </span>
              </span>
            </Cell>
            <Cell strong={t.filing_count > 0} tone={t.filing_count === 0 ? "muted" : undefined}>
              {t.filing_count}
              {t.truncated && <span className="ml-0.5 text-ask">+</span>}
            </Cell>
            <Cell tone="muted">{t.insider_count}</Cell>
            {/* ⚠️**몰림만 보여 준다.** 고르게 났다면 최근 1/3 구간에 33% 쯤
                들어온다 — 그보다 한참 높으면 무슨 일이 있었다는 뜻이다(락업
                해제·베스팅 등). 방향은 모른다: 서식 4 는 매수·매도·부여를
                모두 담고, SEC 제출 목록에는 그 구분이 없다. */}
            <Cell
              tone={
                t.insider_count >= 10 &&
                t.insider_recent_count / t.insider_count >= 0.6
                  ? undefined
                  : "muted"
              }
              strong={
                t.insider_count >= 10 &&
                t.insider_recent_count / t.insider_count >= 0.6
              }
            >
              {t.insider_count
                ? `${t.insider_recent_count} (${Math.round(
                    (t.insider_recent_count / t.insider_count) * 100,
                  )}%)`
                : "—"}
            </Cell>
          </tr>
        ))}
      </DataTable>

      {notCovered.length > 0 && (
        <div className="rounded-xl border border-hairline bg-canvas-soft px-3 py-2.5">
          <p className="mb-1 text-[11px] font-bold text-ge-navy">
            SEC 개별 공시 대상 아님 ({notCovered.length})
          </p>
          <p className="mb-1.5 text-[11px] leading-snug text-ink-muted">
            신탁 단위로 공시합니다. <strong>공시가 없는 것이 아닙니다.</strong>
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
            왜 이렇게 나누나 →
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
        "rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors",
        active ? "bg-white text-ge-navy" : "bg-white/15 text-white hover:bg-white/25",
      )}
    >
      {children}
    </button>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
