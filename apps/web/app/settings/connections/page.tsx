"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Database, HardDrive, Landmark, Radio } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList } from "@/components/stub";
import {
  getJobSources,
  getPortfolioConnections,
  getPriceSources,
  type PortfolioConnection,
  type PriceSourceStatus,
  type SourceStatus,
} from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { useConnectDialog } from "@/components/brokerage/connect-context";
import { KIWOOM_CARD, SOURCE_GROUPS, type SourceCard, type StoreKind } from "@/components/connections/source-catalog";
import { cn } from "@/lib/utils";

// 연동 · 데이터 소스 화면.
//
// ★2026-09-21 정정(사용자): **토스는 계좌가 아니다.** 키움 계좌의 보유 종목에 대해
//   실시간 가격을 받아오는 **시세 소스**다. 계좌(무엇을 얼마나 들고 있나)와
//   시세(그게 지금 얼마인가)는 다른 관심사라 카드 묶음도 나눈다.
// ★2026-09-21: 키 입력은 팝업(ConnectDialog). 키는 브라우저 → 서버로 한 번만 흐르고,
//   서버는 검증 성공 후에만 .env(0600)에 저장하며 어떤 응답에도 키를 싣지 않는다.
// ★2026-10-28 사용자 요청: 소스마다 카드 — 형태 · 받는 데이터 · 최근 확인 · 출처 · 저장 여부.
//   목록과 사실은 `components/connections/source-catalog.ts`, 상태는 `source_status`(/jobs/sources).

type Health =
  | { state: "ok"; at: string }
  | { state: "error"; at: string; kind: string | null; message: string | null; lastOk: string | null; key: string }
  | { state: "paused"; at: string }
  | { state: "unknown" }
  | { state: "untracked" }
  | { state: "fetch_error" };

/** 키 하나의 판정 — 실패가 성공보다 늦으면 오류. 'stopped'(사람이 STOP 으로 멈춤)는 고장이 아니다(ops_alerts 와 같은 기준). */
function keyHealth(r: SourceStatus): Health {
  const ok = r.last_ok_at;
  const err = r.last_error_at;
  if (err && (!ok || err > ok)) {
    if (r.last_error_kind === "stopped") return { state: "paused", at: err };
    return { state: "error", at: err, kind: r.last_error_kind, message: r.last_error_message, lastOk: ok, key: r.source };
  }
  return ok ? { state: "ok", at: ok } : { state: "unknown" };
}

const RANK: Record<Health["state"], number> = { fetch_error: 5, error: 4, paused: 3, ok: 2, unknown: 1, untracked: 0 };

/** 카드의 상태 = 키마다 판정한 것 중 **가장 나쁜** 것.
 *  ⚠️키를 합쳐 '가장 최근 성공 vs 가장 최근 실패'로 보면, 매시간 성공하는 Form 4 가
 *    12시간마다 실패하는 13D/G 를 가려 SEC 카드가 늘 '정상'으로 뜬다. */
function healthOf(keys: string[], rows: SourceStatus[] | undefined, failed: boolean): Health {
  if (keys.length === 0) return { state: "untracked" };
  if (failed) return { state: "fetch_error" };
  const each = (rows ?? []).filter((r) => keys.includes(r.source)).map(keyHealth);
  if (each.length === 0) return { state: "unknown" };
  const worst = each.reduce((a, b) => (RANK[b.state] > RANK[a.state] ? b : a));
  if (worst.state !== "ok") return worst;
  // 모두 정상 — 가장 최근 확인 시각을 보인다.
  return each.reduce((a, b) => (b.state === "ok" && a.state === "ok" && b.at > a.at ? b : a));
}

const ERROR_KIND: Record<string, string> = {
  "403": "차단(403)",
  "429": "요청 제한",
  timeout: "시간 초과",
  timeout_wallclock: "시간 초과",
  config: "설정 필요",
};

function HealthChip({ health, loading }: { health: Health; loading: boolean }) {
  if (health.state === "untracked") return <Pill tone="muted">상태 미기록</Pill>;
  if (loading) return <Pill tone="muted">확인 중…</Pill>;
  switch (health.state) {
    case "ok":
      return <Pill tone="ok">정상</Pill>;
    case "error":
      return <Pill tone="bad">{health.kind ? (ERROR_KIND[health.kind] ?? "오류") : "오류"}</Pill>;
    case "paused":
      return <Pill tone="muted">정지됨</Pill>;
    case "unknown":
      return <Pill tone="muted">기록 없음</Pill>;
    case "fetch_error":
      return <Pill tone="muted">상태 조회 실패</Pill>;
  }
}

function Pill({ tone, children }: { tone: "ok" | "bad" | "muted" | "info"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-extrabold",
        tone === "ok" && "bg-status-success/10 text-status-success",
        tone === "bad" && "bg-status-failed/10 text-status-failed",
        tone === "muted" && "bg-slate-100 text-ink-muted",
        tone === "info" && "bg-ge-blue-bg text-ge-point",
      )}
    >
      {children}
    </span>
  );
}

const STORE_LABEL: Record<StoreKind, string> = { db: "DB 저장", cache: "캐시만", none: "저장 안 함" };

function StoreBadge({ kind }: { kind: StoreKind }) {
  const Icon = kind === "db" ? Database : HardDrive;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold",
        kind === "db" ? "bg-ge-blue-bg text-ge-point" : "bg-canvas-soft text-ink-muted",
      )}
    >
      <Icon className="h-3 w-3" />
      {STORE_LABEL[kind]}
    </span>
  );
}

/** 토스·야후·키움 잔고 — 시세 경로가 지금 이 소스를 쓰는지(순위)와 실패.
 *  ★2026-10-05: IP 가 바뀌어 토스 토큰이 막혀도 '연동됨 · 지금 사용'이 떴다 — 경로가 겪은 실패를 먼저 보인다. */
function priceRoute(s: PriceSourceStatus | undefined): { text: string; bad: boolean; help: string | null } | null {
  if (!s) return null;
  if (s.configured && (s.state === "ip_blocked" || s.state === "error")) {
    const blocked = s.state === "ip_blocked";
    return {
      text: blocked ? "IP 미허용 · 야후로 대체 중" : "오류 · 야후로 대체 중",
      bad: true,
      help: blocked ? "토스 WTS 설정→Open API 에서 현재 공인 IP 를 허용목록에 등록" : (s.message ?? null),
    };
  }
  if (!s.configured) return { text: "키 미등록", bad: false, help: null };
  return { text: s.rank === 1 ? "지금 시세에 사용" : s.rank != null ? "예비 시세" : "폴백 시세", bad: false, help: null };
}

function LastCheck({ health, okLabel }: { health: Health; okLabel?: string }) {
  switch (health.state) {
    case "untracked":
      return <span className="text-ink-faint">요청 때 직접 호출 · 성공/실패 기록 없음</span>;
    case "unknown":
      return <span className="text-ink-faint">아직 기록 없음</span>;
    case "fetch_error":
      return <span className="text-ink-faint">상태를 불러오지 못함</span>;
    case "paused":
      return <span title={formatDateTime(health.at)}>수동 정지 {formatRelativeTime(health.at)}</span>;
    case "ok":
      return (
        <span title={formatDateTime(health.at)}>
          {okLabel ?? "최근 확인"} <b className="text-ink">{formatRelativeTime(health.at)}</b>
        </span>
      );
    case "error":
      return (
        <span title={health.message ?? undefined}>
          <b className="text-status-failed">실패 {formatRelativeTime(health.at)}</b>
          <span className="text-ink-faint"> · {health.key}</span>
          {health.lastOk && <span className="text-ink-faint"> · 마지막 성공 {formatRelativeTime(health.lastOk)}</span>}
        </span>
      );
  }
}

function SourceCardView({
  card,
  health,
  loading,
  price,
  children,
}: {
  card: SourceCard;
  health: Health;
  loading: boolean;
  price?: PriceSourceStatus;
  children?: ReactNode;
}) {
  const route = priceRoute(price);
  return (
    <article className="flex min-w-0 flex-col rounded-xl border border-hairline bg-white px-4 py-3">
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13.5px] font-extrabold leading-tight text-ge-navy">{card.name}</h3>
          <p className="mt-0.5 text-[10.5px] font-semibold text-ink-faint">{card.origin}</p>
        </div>
        <HealthChip health={health} loading={loading} />
      </header>

      <dl className="mt-2.5 grid grid-cols-[3.2rem_minmax(0,1fr)] break-words gap-x-2 gap-y-1 text-[11px] leading-snug">
        <dt className="font-bold text-ink-faint">형태</dt>
        <dd className="font-semibold text-ink-muted">{card.form}</dd>
        <dt className="font-bold text-ink-faint">데이터</dt>
        <dd className="font-semibold text-ink">{card.data}</dd>
        <dt className="font-bold text-ink-faint">주기</dt>
        <dd className="font-medium text-ink-muted">{card.cadence}</dd>
        <dt className="font-bold text-ink-faint">저장</dt>
        <dd className="flex flex-wrap items-center gap-1.5 font-medium text-ink-muted">
          <StoreBadge kind={card.store} />
          <span>{card.storeDetail}</span>
        </dd>
      </dl>

      {card.caveat && <p className="mt-2 text-[10.5px] font-medium leading-snug text-amber-700">⚠ {card.caveat}</p>}
      {children}

      {/* 카드 높이가 달라도 '최근 확인' 줄을 바닥에 맞춘다 */}
      <div className="min-h-2.5 flex-1" />
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-2 text-[10.5px] font-medium text-ink-muted">
        <LastCheck health={health} okLabel={card.okLabel} />
        {route && <Pill tone={route.bad ? "bad" : "info"}>{route.text}</Pill>}
      </footer>
      {route?.help && <p className="mt-1.5 text-[10.5px] font-semibold text-status-failed">{route.help}</p>}
      {health.state === "error" && health.message && (
        <p className="mt-1.5 line-clamp-2 text-[10.5px] font-medium text-status-failed" title={health.message}>
          {health.message}
        </p>
      )}
    </article>
  );
}

export default function ConnectionsPage() {
  const { open: openConnect } = useConnectDialog();
  // ★2026-10-04: 시세 소스 배지가 '미등록'으로 박혀 있었다 — 서버가 본 실제 상태를 쓴다.
  const priceSources = useQuery({ queryKey: ["priceSources"], queryFn: getPriceSources, staleTime: 60_000 });
  const connections = useQuery({ queryKey: ["portfolioConnections"], queryFn: getPortfolioConnections, staleTime: 30_000 });
  const sources = useQuery({ queryKey: ["jobSources"], queryFn: getJobSources, staleTime: 60_000 });

  const rows = sources.data?.items;
  const allCards = [KIWOOM_CARD, ...SOURCE_GROUPS.flatMap((g) => g.cards)];
  const healths = allCards.map((c) => healthOf(c.statusKeys, rows, sources.isError));
  const count = (s: Health["state"]) => healths.filter((h) => h.state === s).length;
  const accounts = connections.data ?? [];
  const price = (id?: string) => (id ? priceSources.data?.sources.find((p) => p.id === id) : undefined);

  return (
    <>
      <Topbar title="계좌 · 데이터 소스" subtitle="어디서 무엇을 받아 어디에 두나" showAccountContext={false} />
      <PageContainer wide>
        {/* 한 줄 요약 — 소스가 조용히 죽어 있으면 화면의 숫자가 낡는다. */}
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[12px] font-bold text-ink-muted">
          <Radio className="h-4 w-4 text-ge-point" />
          <span className="text-ge-navy">소스 {allCards.length}곳</span>
          {sources.isError ? (
            <Pill tone="bad">상태를 불러오지 못함</Pill>
          ) : (
            <>
              <Pill tone="ok">정상 {count("ok")}</Pill>
              {count("error") > 0 && <Pill tone="bad">오류 {count("error")}</Pill>}
              {count("paused") > 0 && <Pill tone="muted">정지 {count("paused")}</Pill>}
              <Pill tone="muted">미기록 {count("untracked") + count("unknown")}</Pill>
            </>
          )}
        </div>

        <Section title="계좌" hint="무엇을 얼마나 들고 있나">
          <SourceCardView
            card={KIWOOM_CARD}
            health={healths[0]}
            loading={sources.isLoading}
            price={price(KIWOOM_CARD.priceSourceId)}
          >
            <div className="mt-2.5 space-y-1.5">
              {accounts.map((c) => (
                <AccountLine key={c.id} connection={c} />
              ))}
              {connections.isLoading && <p className="text-[11px] font-semibold text-ink-faint">계좌 불러오는 중…</p>}
              {!connections.isLoading && accounts.length === 0 && (
                <p className="text-[11px] font-semibold text-ink-faint">
                  {connections.isError ? "API 서버에 연결하지 못했습니다." : "아직 등록된 계좌 없음"}
                </p>
              )}
              <button
                type="button"
                onClick={openConnect}
                className="w-full rounded-lg bg-ge-point px-3 py-2 text-[12px] font-extrabold text-white transition-colors hover:bg-ge-point/90"
              >
                API 키 등록 · 동기화
              </button>
              <details className="text-[11px]">
                <summary className="cursor-pointer font-bold text-ink-muted">연동 순서</summary>
                <div className="mt-1.5">
                  <PlannedList
                    items={[
                      "키움 OpenAPI 신청 → appkey / secretkey 발급",
                      "⚠️서버 공인 IP 를 허용목록에 등록 — 안 하면 키가 맞아도 8050 으로 거부된다",
                      "서버 .env 에 키 저장 (브라우저로 내려보내지 않는다)",
                      "동기화 1회 실행 → 계좌·잔고·보유종목이 DB 에 적재된다",
                      "대시보드는 DB만 읽는다 — 증권사 API 를 화면이 직접 때리지 않는다",
                    ]}
                  />
                </div>
              </details>
            </div>
          </SourceCardView>
        </Section>

        {SOURCE_GROUPS.map((g) => (
          <Section key={g.id} title={g.title} hint={g.hint}>
            {g.cards.map((card) => (
              <SourceCardView
                key={card.id}
                card={card}
                health={healths[allCards.indexOf(card)]}
                loading={sources.isLoading}
                price={price(card.priceSourceId)}
              />
            ))}
          </Section>
        ))}
      </PageContainer>
    </>
  );
}

function Section({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h2 className="mb-2 flex items-baseline gap-2 text-[13px] font-extrabold text-ge-navy">
        {title}
        <span className="text-[11px] font-semibold text-ink-faint">{hint}</span>
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{children}</div>
    </section>
  );
}

/** 키움 카드 안의 계좌 한 줄 — 이름 · 환경 · 마지막 동기화 · 상태. 오류는 접지 않는다. */
function AccountLine({ connection: c }: { connection: PortfolioConnection }) {
  const tone = c.status === "CONNECTED" ? "ok" : c.status === "ERROR" ? "bad" : "muted";
  const label = c.status === "CONNECTED" ? "연동됨" : c.status === "ERROR" ? "오류" : "설정됨";
  return (
    <div className="rounded-lg bg-canvas-soft px-2.5 py-1.5">
      <div className="flex items-center gap-2 text-[11px]">
        <Landmark className="h-3.5 w-3.5 shrink-0 text-ge-point" />
        <span className="min-w-0 flex-1 truncate font-bold text-ge-navy">
          {c.broker_name} {c.connection_name}{" "}
          <span className="font-semibold text-ink-faint">· {c.environment}</span>
        </span>
        <Pill tone={tone}>{label}</Pill>
      </div>
      <p className="mt-0.5 pl-5 text-[10.5px] font-medium text-ink-faint">마지막 동기화 {formatDateTime(c.last_synced_at)}</p>
      {c.last_error && (
        <p className="mt-1 flex items-start gap-1 pl-5 text-[10.5px] font-semibold leading-snug text-status-failed">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {c.last_error}
        </p>
      )}
    </div>
  );
}
