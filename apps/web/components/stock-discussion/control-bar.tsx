"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw, Search, Wifi, WifiOff } from "lucide-react";
import type {
  SdEtf,
  SdHealthChannel,
  SdSource,
  SdStats,
} from "@/lib/stock-discussion";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SOURCE_STYLE, issuerColor } from "./brand";
import { FilterMenu, MenuOption } from "./filter-menu";

// 감성 필터 제거(D). ETF 선택은 etfCode 우선, 없으면 발행사/분류로 좁힘(서버 해석은 page).
export interface FilterState {
  issuer: string | null;
  category: string | null;
  etfCode: string | null;
  source: SdSource | null;
}

const STALE_THRESHOLD_S = 180; // SD_PUSH_INTERVAL_HINT(60) × SD_STALE_FACTOR(3), D11
const CHANNEL_LAG_S = 30 * 60; // 수집 지연 주의 임계(30분)

function ageSeconds(iso: string | null | undefined, nowMs: number): number {
  if (!iso) return Infinity;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return Infinity;
  return (nowMs - t) / 1000;
}

// 수집 채널 점: 오류>0 → 실패색, last_ok 없음 → 대기색, 그 외 정상색(§3.1-①).
function channelTone(c: SdHealthChannel | undefined): { dot: string; text: string } {
  if (!c || c.last_ok == null) return { dot: "bg-ink-faint", text: "대기" };
  if (c.consecutive_errors > 0) return { dot: "bg-status-failed", text: "오류" };
  return { dot: "bg-status-success", text: "정상" };
}

interface ControlBarProps {
  stats: SdStats | undefined;
  etfs: SdEtf[];
  filter: FilterState;
  onIssuer: (v: string | null) => void;
  onCategory: (v: string | null) => void;
  onEtf: (v: string | null) => void;
  onSource: (v: SdSource | null) => void;
  newCount: number;
  onResetNew: () => void;
  onRefresh: () => void;
  isFetching: boolean;
  searchInput: string;
  onSearchInput: (v: string) => void;
}

export function ControlBar({
  stats,
  etfs,
  filter,
  onIssuer,
  onCategory,
  onEtf,
  onSource,
  newCount,
  onResetNew,
  onRefresh,
  isFetching,
  searchInput,
  onSearchInput,
}: ControlBarProps) {
  // 1s 클록 — 시계 표시 + staleness 재계산(폴링 사이 last_ingest_at 은 고정).
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const lastIngest = stats?.last_ingest_at ?? null;
  const fresh = ageSeconds(lastIngest, nowMs) <= STALE_THRESHOLD_S;

  // push 는 신선하나 채널 last_ok 가 오래됐으면 "수집 지연"(에러 아님, §6-3).
  const naverLag = ageSeconds(stats?.health.naver.last_ok, nowMs);
  const tossLag = ageSeconds(stats?.health.toss.last_ok, nowMs);
  const collectDelayed =
    fresh && Math.min(naverLag, tossLag) > CHANNEL_LAG_S && stats != null;

  const clock = new Date(nowMs).toLocaleTimeString("ko-KR", { hour12: false });

  // overflow 는 자르지 않는다 — 드롭다운 패널이 박스 밖으로 펼쳐져야 함(D).
  return (
    <div className="mb-4 rounded-2xl border border-hairline bg-canvas shadow-card">
      <div className="h-2 rounded-t-2xl bg-ge-point" />
      <div className="flex flex-col gap-3 p-4">
        {/* 상단: 시계·최근갱신·연결점 + 새로고침 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              suppressHydrationWarning
              className="text-[26px] font-extrabold leading-none tracking-tight tabular-nums text-ge-navy"
            >
              {clock}
            </span>
            <span className="text-[11.5px] text-ink-muted">
              최근 갱신 {formatRelativeTime(lastIngest)}
            </span>
            <ConnectionDot fresh={fresh} hasData={stats != null} />
          </div>
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-canvas-soft px-3 py-1.5 text-[12px] font-semibold text-ink-muted transition-colors hover:bg-ge-blue-bg hover:text-ge-point"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", isFetching && "animate-spin")}
              strokeWidth={2.2}
            />
            새로고침
          </button>
        </div>

        {/* 수집 상태 + 필터(발행사·분류·ETF) + 소스 — 한 줄에 통합 */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-hairline pt-3">
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-bold uppercase tracking-wide text-ink-muted">
              수집
            </span>
            <ChannelDot name="네이버" channel={stats?.health.naver} />
            <ChannelDot name="토스증권" channel={stats?.health.toss} />
          </div>

          <span className="hidden h-5 w-px bg-hairline sm:block" />

          <div className="flex flex-wrap items-center gap-2">
            <IssuerMenu etfs={etfs} filter={filter} onIssuer={onIssuer} />
            <CategoryMenu etfs={etfs} filter={filter} onCategory={onCategory} />
            <EtfMenu etfs={etfs} stats={stats} filter={filter} onEtf={onEtf} />
            <SourceSegment source={filter.source} onSource={onSource} />
          </div>
        </div>

        {/* 카운트 밴드 */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onResetNew}
            disabled={newCount === 0}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-bold transition-colors",
              newCount > 0
                ? "bg-ge-point text-white hover:bg-ge-navy"
                : "cursor-default bg-canvas-soft text-ink-faint",
            )}
          >
            신규 {newCount}
          </button>
          <CountPill label="오늘" value={stats?.today} />
          <CountPill label="총" value={stats?.total} />
        </div>

        {/* 검색 (디바운스는 부모에서 300ms) */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchInput(e.target.value)}
            placeholder="제목·본문·작성자 검색 (DB 전체)"
            className="w-full rounded-lg border border-hairline bg-canvas-soft py-2 pl-9 pr-3 text-[13px] text-ink outline-none transition-colors focus:border-ge-point focus:bg-canvas"
          />
        </div>

        {/* staleness 배너 (데이터는 아래 계속 렌더) */}
        {stats != null && !fresh && (
          <div className="flex items-start gap-2 rounded-lg border border-status-failed/30 bg-status-failed/[0.06] px-3 py-2 text-[12px] text-status-failed">
            <WifiOff className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>
              수집 서버에 연결되지 않았습니다 · 마지막 동기화{" "}
              {formatRelativeTime(lastIngest)} (직전 동기화 데이터 표시 중)
            </span>
          </div>
        )}
        {collectDelayed && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/[0.08] px-3 py-2 text-[12px] text-amber-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>수집 지연 · 동기화는 최신이나 크롤 채널 응답이 지연되고 있습니다</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 수집 상태 점 ──
function ChannelDot({
  name,
  channel,
}: {
  name: string;
  channel: SdHealthChannel | undefined;
}) {
  const tone = channelTone(channel);
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={channel?.last_ok ? formatRelativeTime(channel.last_ok) : tone.text}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", tone.dot)} />
      <span className="text-[12.5px] font-semibold text-ink">{name}</span>
      <span className="text-[11px] text-ink-faint">{tone.text}</span>
    </span>
  );
}

// ── 발행사 드롭다운 ──
function IssuerMenu({
  etfs,
  filter,
  onIssuer,
}: {
  etfs: SdEtf[];
  filter: FilterState;
  onIssuer: (v: string | null) => void;
}) {
  const issuers = useMemo(
    () => Array.from(new Set(etfs.map((e) => e.issuer).filter(Boolean))).sort(),
    [etfs],
  );
  return (
    <FilterMenu
      label="발행사"
      summary={filter.issuer ?? "전체"}
      active={filter.issuer != null}
      accentColor={filter.issuer ? issuerColor(filter.issuer) : undefined}
    >
      {(close) => (
        <>
          <MenuOption
            label="전체"
            active={filter.issuer == null}
            onClick={() => {
              onIssuer(null);
              close();
            }}
          />
          {issuers.map((iss) => (
            <MenuOption
              key={iss}
              label={iss}
              accentColor={issuerColor(iss)}
              active={filter.issuer === iss}
              onClick={() => {
                onIssuer(filter.issuer === iss ? null : iss);
                close();
              }}
            />
          ))}
        </>
      )}
    </FilterMenu>
  );
}

// ── 분류 드롭다운 ──
function CategoryMenu({
  etfs,
  filter,
  onCategory,
}: {
  etfs: SdEtf[];
  filter: FilterState;
  onCategory: (v: string | null) => void;
}) {
  const categories = useMemo(
    () => Array.from(new Set(etfs.map((e) => e.category).filter(Boolean))).sort(),
    [etfs],
  );
  if (categories.length === 0) return null;
  return (
    <FilterMenu
      label="분류"
      summary={filter.category ?? "전체"}
      active={filter.category != null}
    >
      {(close) => (
        <>
          <MenuOption
            label="전체"
            active={filter.category == null}
            onClick={() => {
              onCategory(null);
              close();
            }}
          />
          {categories.map((cat) => (
            <MenuOption
              key={cat}
              label={cat}
              active={filter.category === cat}
              onClick={() => {
                onCategory(filter.category === cat ? null : cat);
                close();
              }}
            />
          ))}
        </>
      )}
    </FilterMenu>
  );
}

// ── ETF 드롭다운 (선택지 많음 → 내부 검색 + 카운트) ──
function EtfMenu({
  etfs,
  stats,
  filter,
  onEtf,
}: {
  etfs: SdEtf[];
  stats: SdStats | undefined;
  filter: FilterState;
  onEtf: (v: string | null) => void;
}) {
  const [q, setQ] = useState("");

  const totalByEtf = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of stats?.by_etf_source ?? [])
      m.set(r.etf_code, (m.get(r.etf_code) ?? 0) + r.n);
    return m;
  }, [stats]);
  const todayByEtf = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of stats?.today_by_etf ?? []) m.set(r.etf_code, r.n);
    return m;
  }, [stats]);

  // 발행사/분류로 좁힌 뒤 내부 검색어(이름·코드) 매칭 → 총건수 내림차순.
  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return etfs
      .filter(
        (e) =>
          (!filter.issuer || e.issuer === filter.issuer) &&
          (!filter.category || e.category === filter.category) &&
          (!needle ||
            e.name.toLowerCase().includes(needle) ||
            e.code.toLowerCase().includes(needle)),
      )
      .sort((a, b) => (totalByEtf.get(b.code) ?? 0) - (totalByEtf.get(a.code) ?? 0));
  }, [etfs, filter.issuer, filter.category, totalByEtf, q]);

  const selected = etfs.find((e) => e.code === filter.etfCode);

  return (
    <FilterMenu
      label="ETF"
      summary={selected ? selected.name : "전체"}
      active={filter.etfCode != null}
      accentColor={selected ? issuerColor(selected.issuer, selected.name) : undefined}
      panelClassName="min-w-[19rem]"
    >
      {(close) => (
        <>
          <div className="sticky top-0 -mx-1.5 -mt-1.5 mb-1 border-b border-hairline bg-canvas px-1.5 pb-1.5 pt-0.5">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
              <input
                autoFocus
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="ETF 이름·코드 검색"
                className="w-full rounded-md border border-hairline bg-canvas-soft py-1.5 pl-8 pr-2.5 text-[12px] text-ink outline-none focus:border-ge-point focus:bg-canvas"
              />
            </div>
          </div>
          <MenuOption
            label="전체"
            sub={etfs.length > 0 ? `${etfs.length}개 종목토론방` : undefined}
            active={filter.etfCode == null}
            right={<EtfCounts total={stats?.total} today={undefined} />}
            onClick={() => {
              onEtf(null);
              close();
            }}
          />
          {visible.map((e) => (
            <MenuOption
              key={e.code}
              label={e.name}
              sub={e.code}
              accentColor={issuerColor(e.issuer, e.name)}
              active={filter.etfCode === e.code}
              right={
                <EtfCounts
                  total={totalByEtf.get(e.code) ?? 0}
                  today={todayByEtf.get(e.code)}
                />
              }
              onClick={() => {
                onEtf(filter.etfCode === e.code ? null : e.code);
                close();
              }}
            />
          ))}
          {visible.length === 0 && (
            <div className="px-2.5 py-4 text-center text-[12px] text-ink-faint">
              검색 결과가 없습니다
            </div>
          )}
        </>
      )}
    </FilterMenu>
  );
}

function EtfCounts({
  total,
  today,
}: {
  total: number | undefined;
  today: number | undefined;
}) {
  return (
    <>
      {total != null && (
        <span className="text-[11px] tabular-nums text-ink-muted">
          {total.toLocaleString("ko-KR")}
        </span>
      )}
      {today != null && today > 0 && (
        <span className="rounded-full bg-ge-point/10 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-ge-point">
          +{today}
        </span>
      )}
    </>
  );
}

// ── 소스 세그먼트 (3개뿐 → 드롭다운 대신 인라인 세그) ──
function SourceSegment({
  source,
  onSource,
}: {
  source: SdSource | null;
  onSource: (v: SdSource | null) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <span className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">
        소스
      </span>
      <div className="inline-flex items-stretch rounded-lg border border-hairline p-0.5">
        <SourceSeg
          label="전체"
          active={source == null}
          onClick={() => onSource(null)}
        />
        {(["네이버", "토스증권"] as SdSource[]).map((s) => (
          <SourceSeg
            key={s}
            label={s}
            active={source === s}
            accent={SOURCE_STYLE[s].color}
            onClick={() => onSource(source === s ? null : s)}
          />
        ))}
      </div>
    </div>
  );
}

function SourceSeg({
  label,
  active,
  accent,
  onClick,
}: {
  label: string;
  active: boolean;
  accent?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative rounded-md px-2.5 py-1 text-[12px] font-semibold transition-colors",
        active ? "bg-ge-blue-bg text-ge-navy" : "text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {label}
      {active && accent && (
        <span
          className="absolute inset-x-2 bottom-0.5 h-0.5 rounded-full"
          style={{ background: accent }}
        />
      )}
    </button>
  );
}

function ConnectionDot({ fresh, hasData }: { fresh: boolean; hasData: boolean }) {
  if (!hasData) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11.5px] text-ink-faint">
        <span className="h-2 w-2 rounded-full bg-ink-faint" />연결 확인 중
      </span>
    );
  }
  return fresh ? (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-status-success">
      <Wifi className="h-3.5 w-3.5" strokeWidth={2.4} />
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success/60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
      </span>
      실시간 갱신
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-status-failed">
      <span className="h-2 w-2 rounded-full bg-status-failed" />수집 서버 미접속
    </span>
  );
}

function CountPill({ label, value }: { label: string; value: number | undefined }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas-soft px-2.5 py-1 text-[12px]">
      <span className="text-ink-muted">{label}</span>
      <span className="font-bold tabular-nums text-ge-navy">
        {value != null ? value.toLocaleString("ko-KR") : "—"}
      </span>
    </span>
  );
}
