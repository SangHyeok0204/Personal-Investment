"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  Clock,
  Menu,
  Scale,
  Search,
  User,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  getInavHoga,
  getInavSnapshot,
  type HogaEtf,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면 — 5박스 레이아웃 골격 (웹페이지 디자인 시안 사본.pdf).
// GE 하우스 스타일(그레이 캔버스 + 흰색 카드 + 블루 포인트)로 구현한 빈 골격이며,
// 각 박스의 콘텐츠 연동은 다음 단계다.
// ─────────────────────────────────────────────────────────────────────────────

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

function formatDate(d: Date) {
  return {
    year: String(d.getFullYear()),
    text: `${d.getMonth() + 1}월 ${d.getDate()}일, ${WEEKDAYS[d.getDay()]}요일`,
  };
}

function formatClock(d: Date) {
  let hour = d.getHours();
  const ampm = hour < 12 ? "오전" : "오후";
  hour %= 12;
  if (hour === 0) hour = 12;
  const minute = String(d.getMinutes()).padStart(2, "0");
  return `${ampm} ${hour}:${minute}`;
}

/** 마운트 후에만 시계를 채워 SSR/CSR 불일치를 피한다. */
function useNow() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function HomePage() {
  const now = useNow();
  const date = now ? formatDate(now) : null;
  const clock = now ? formatClock(now) : "—";

  return (
    <div className="flex min-h-screen flex-col gap-4 p-4 xl:gap-5 xl:p-5">
      {/* 상단 헤더 */}
      <header className="flex h-14 shrink-0 items-center gap-4 rounded-2xl border border-hairline bg-canvas px-5 shadow-card">
        <Menu className="h-5 w-5 text-ink-muted" />
        <div className="flex-1" />
        <button
          type="button"
          className="rounded-lg border border-[#e8735c] bg-white px-3 py-1.5 text-xs font-bold text-[#e8735c] transition-colors hover:bg-[#e8735c]/[0.06]"
        >
          로그아웃
        </button>
        <span className="text-[15px] text-ge-navy">
          안녕하세요. <b className="font-extrabold">홍길동님</b>
        </span>
        <span className="relative flex h-10 w-10 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-ge-main to-ge-point shadow-[0_4px_12px_rgba(70,105,170,0.25)]">
          <User className="h-6 w-6 text-white" />
          <span className="absolute bottom-0.5 right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400" />
        </span>
      </header>

      {/* 본문: 좌측 박스 영역 + 우측 위젯 레일 */}
      <div className="flex min-h-0 flex-1 gap-4 xl:gap-5">
        {/* 좌측 — 상단 2박스 + 하단 2박스 (크기 상이) */}
        <div className="flex min-w-0 flex-1 flex-col gap-4 xl:gap-5">
          <div className="grid h-[150px] shrink-0 grid-cols-2 gap-4 xl:gap-5">
            <Box tone="blue" label="시장 요약" />
            <Box tone="plain" label="주요 지표" />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 xl:gap-5">
            <Box tone="plain" label="모니터링 A">
              <MonitoringAAlerts />
            </Box>
            <Box tone="plain" label="모니터링 B" />
          </div>
        </div>

        {/* 우측 — 검색 / 날짜 / 시간 + 세로 박스 */}
        <aside className="flex w-[236px] shrink-0 flex-col gap-4">
          <div className="flex h-11 shrink-0 items-center gap-2 rounded-xl border border-hairline bg-canvas px-3.5 shadow-card">
            <Search className="h-4 w-4 shrink-0 text-ink-muted" />
            <input
              placeholder="검색"
              className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
            />
            <Menu className="h-4 w-4 shrink-0 text-ink-muted" />
          </div>

          <InfoCard icon={CalendarDays}>
            <div className="text-xs font-extrabold text-ge-point">
              {date?.year ?? "—"}
            </div>
            <div className="text-sm font-extrabold text-ge-navy">
              {date?.text ?? "날짜 확인 중"}
            </div>
          </InfoCard>

          <InfoCard icon={Clock}>
            <div className="text-[15px] font-extrabold text-ge-navy">{clock}</div>
          </InfoCard>

          <Box tone="blue" label="퀀트 스코어보드" className="min-h-0 flex-1" />
          <Box tone="plain" label="바로가기" className="h-[76px] shrink-0" />
        </aside>
      </div>
    </div>
  );
}

/** 콘텐츠 박스 (children 없으면 빈 골격 문구). */
function Box({
  tone,
  label,
  className,
  children,
}: {
  tone: "plain" | "blue";
  label: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-2xl border shadow-card",
        tone === "blue"
          ? "border-ge-line-soft bg-ge-blue-bg"
          : "border-hairline bg-canvas",
        className,
      )}
    >
      <div className="flex items-center gap-2 px-4 pt-4">
        <span className="h-4 w-1.5 rounded-full bg-ge-point" />
        <span className="text-[13px] font-extrabold text-ge-navy">{label}</span>
      </div>
      <div className="flex flex-1 items-center justify-center p-4 text-xs font-semibold text-ink-faint">
        {children ?? "콘텐츠 준비 중"}
      </div>
    </section>
  );
}

/* ── 모니터링 A — CHECK 호가 알림 (iNAV 카드의 부족 표시 이관, 2026-07-20) ──
   산식은 구 호가모니터링-대시보드.html 로직 그대로:
   · 물량부족: 매도/매수 5단 잔량합 < obThreshold (양쪽 각각 판정)
   · 괴리차이: |장중괴리(hoga premiumIntra) − 실제괴리(snapshot deviation_pct)| ≥ 1.0%p
     (구 뷰어의 실제괴리도 가격×KIS iNAV 클라이언트 병합값 — hoga의 premiumActual
      필드는 상시 0이라 쓰지 않는다) */

const DEV_DIFF_ALERT_PCT = 1.0;

// 경고 원인 5종 (2026-07-20 사용자 정의). "LP 호가가 시장가에서 멀어짐"은
// 현재 피드가 호가 가격 없이 잔량만 제공해 판정 산식 미정 — 예약만 해 둔다.
const CAUSE_ASK_LOW = "LP 매도 호가 물량 부족";
const CAUSE_BID_LOW = "LP 매수 호가 물량 부족";
const CAUSE_BOTH_LOW = "LP 매수/매도 호가 물량 부족";
const CAUSE_DEV_DIFF = "괴리율 심화";

interface HogaAlert {
  key: string;
  name: string;
  status: string;
  cause: string;
  tooltip: string;
}

function sumLevels(levels: number[] | null | undefined): number {
  return (levels ?? []).reduce(
    (s, v) => s + (Number.isFinite(v) ? Number(v) : 0),
    0,
  );
}

function signedPct(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function MonitoringAAlerts() {
  const hogaQuery = useQuery({
    queryKey: ["inavHoga"],
    queryFn: getInavHoga,
    refetchInterval: 1000,
    retry: false,
  });
  const snapQuery = useQuery({
    queryKey: ["inavSnapshot"],
    queryFn: getInavSnapshot,
    refetchInterval: 1000,
    retry: false,
  });

  const etfs: HogaEtf[] = hogaQuery.data?.payload?.etfs ?? [];
  const feedDown = hogaQuery.isError || hogaQuery.data?.payload == null;

  const devByCode = useMemo(() => {
    const map = new Map<string, number>();
    for (const e of snapQuery.data?.etfs ?? []) {
      if (e.deviation_pct != null) map.set(e.ticker, e.deviation_pct);
    }
    return map;
  }, [snapQuery.data]);

  const { obAlerts, devAlerts } = useMemo(() => {
    const ob: HogaAlert[] = [];
    const dev: HogaAlert[] = [];
    for (const e of etfs) {
      const threshold = e.obThreshold ?? 0;
      const totalAsk = sumLevels(e.asks);
      const totalBid = sumLevels(e.bids);
      const askLow = threshold > 0 && totalAsk < threshold;
      const bidLow = threshold > 0 && totalBid < threshold;
      if (askLow || bidLow) {
        const both = askLow && bidLow;
        ob.push({
          key: `ob:${e.code}`,
          name: e.name,
          status: both ? "매도·매수부족" : askLow ? "매도부족" : "매수부족",
          cause: both ? CAUSE_BOTH_LOW : askLow ? CAUSE_ASK_LOW : CAUSE_BID_LOW,
          tooltip: `총매도 ${totalAsk.toLocaleString("ko-KR")}주 / 총매수 ${totalBid.toLocaleString("ko-KR")}주 (기준 ${threshold.toLocaleString("ko-KR")}주)`,
        });
      }
      const intra = e.premiumIntra;
      const actual = devByCode.get(e.code);
      if (typeof intra === "number" && actual != null) {
        const diff = Math.abs(intra - actual);
        if (diff >= DEV_DIFF_ALERT_PCT) {
          dev.push({
            key: `dev:${e.code}`,
            name: e.name,
            status: "괴리차이",
            cause: CAUSE_DEV_DIFF,
            tooltip: `장중 ${signedPct(intra)} · 실제 ${signedPct(actual)} · 차이 ${diff.toFixed(2)}%p`,
          });
        }
      }
    }
    return { obAlerts: ob, devAlerts: dev };
  }, [etfs, devByCode]);

  // X 로 닫은 알림 — 조건이 해소되면 기록을 지워 재발 시 다시 뜨게 한다.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  useEffect(() => {
    const active = new Set([...obAlerts, ...devAlerts].map((a) => a.key));
    setDismissed((prev) => {
      const next = new Set([...prev].filter((k) => active.has(k)));
      return next.size === prev.size ? prev : next;
    });
  }, [obAlerts, devAlerts]);

  const dismiss = (key: string) =>
    setDismissed((prev) => new Set(prev).add(key));

  return (
    <div className="flex h-1/2 w-full flex-col gap-3 self-start">
      <AlertBox
        title="매수·매도 물량 부족"
        icon={AlertTriangle}
        alerts={obAlerts.filter((a) => !dismissed.has(a.key))}
        onDismiss={dismiss}
        emptyText={feedDown ? "호가 미수신" : "물량 부족 없음"}
      />
      <AlertBox
        title="괴리 차이 (장중 vs 실제)"
        icon={Scale}
        alerts={devAlerts.filter((a) => !dismissed.has(a.key))}
        onDismiss={dismiss}
        emptyText={feedDown ? "호가 미수신" : "괴리 차이 정상"}
      />
    </div>
  );
}

function AlertBox({
  title,
  icon: Icon,
  alerts,
  onDismiss,
  emptyText,
}: {
  title: string;
  icon: LucideIcon;
  alerts: HogaAlert[];
  onDismiss: (key: string) => void;
  emptyText: string;
}) {
  return (
    <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-hairline bg-canvas-soft">
      <div className="flex shrink-0 items-center gap-2 px-3.5 pb-1.5 pt-3">
        <Icon className="h-6 w-6 shrink-0 text-ge-point" strokeWidth={2.2} />
        <span className="text-[18pt] font-extrabold leading-tight text-ge-navy">
          {title}
        </span>
        {alerts.length > 0 && (
          <span className="ml-auto rounded-full bg-status-failed/[0.12] px-2.5 py-0.5 text-[13px] font-bold tabular-nums text-status-failed">
            {alerts.length}
          </span>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-2.5 pb-2.5">
        {alerts.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-[11px] font-semibold text-ink-faint">
            {emptyText}
          </div>
        ) : (
          alerts.map((a) => (
            <div
              key={a.key}
              title={a.tooltip}
              className="notif-in relative shrink-0 rounded-lg border border-hairline bg-canvas px-3.5 py-2 shadow-card"
            >
              <div className="truncate pr-7 text-[15px] leading-snug">
                <span className="font-extrabold text-ge-navy">{a.name}</span>
                <span className="font-bold text-ink">
                  : {a.status} · {a.cause}
                </span>
              </div>
              <button
                type="button"
                onClick={() => onDismiss(a.key)}
                title="알림 닫기"
                className="absolute right-1.5 top-1.5 rounded p-0.5 text-ink-faint transition-colors hover:bg-ge-th hover:text-ink"
              >
                <X className="h-3 w-3" strokeWidth={2.5} />
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

/** 검색 아래 날짜/시간 위젯. */
function InfoCard({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <div className="flex shrink-0 items-center gap-3 rounded-xl border border-hairline bg-canvas px-3.5 py-3 shadow-card">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-ge-blue-bg">
        <Icon className="h-[18px] w-[18px] text-ge-point" />
      </span>
      <div className="min-w-0 leading-tight">{children}</div>
    </div>
  );
}
