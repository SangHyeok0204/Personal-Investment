"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bot,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Landmark,
  Newspaper,
  ServerCog,
  Sparkles,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { getHealth, getJobStats, getPortfolioOverview } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatKrw, formatPercent, formatRelativeTime } from "@/lib/format";

const news = [
  ["연합뉴스", "미국 소비자물가 발표 앞두고 뉴욕 증시 혼조", "2분 전"],
  ["Bloomberg", "Fed officials signal a data-dependent rate path", "6분 전"],
  ["한국경제", "반도체 수출 회복세… 글로벌 수요 주목", "9분 전"],
  ["Reuters", "Oil prices move higher as geopolitical risk persists", "13분 전"],
  ["CNBC", "Big Tech earnings remain the market's focal point", "18분 전"],
] as const;

const events = [
  ["21", "화", "21:30", "미국", "소비자물가지수 (CPI)", "높음"],
  ["22", "수", "03:00", "미국", "FOMC 의사록 공개", "높음"],
  ["24", "금", "08:30", "한국", "주요 기업 실적 발표", "중간"],
] as const;

// Dashboard-only presentation filter. These positions remain in the source DB,
// sync results, and detailed portfolio APIs.
const EXCLUDED_DASHBOARD_TICKERS = new Set(["000660", "SKHYV", "388720", "GLD"]);

export default function OverviewPage() {
  const overview = useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: getPortfolioOverview,
    refetchInterval: 5000,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 5000,
  });
  const jobStats = useQuery({
    queryKey: ["jobStats"],
    queryFn: getJobStats,
    refetchInterval: 5000,
  });

  const data = overview.data;
  const summary = data?.summary;
  const dashboardPositions = (data?.positions ?? []).filter(
    (position) => !EXCLUDED_DASHBOARD_TICKERS.has(position.ticker ?? ""),
  );
  const dashboardSecuritiesValue = dashboardPositions.reduce(
    (totalValue, position) => totalValue + (position.market_value_krw ?? 0),
    0,
  );
  const dashboardPnl = dashboardPositions.reduce(
    (totalValue, position) => totalValue + (position.unrealized_pnl_krw ?? 0),
    0,
  );
  const dashboardPurchaseValue = dashboardPositions.reduce(
    (totalValue, position) => {
      if (position.purchase_amount_local == null || position.exchange_rate == null) {
        return totalValue;
      }
      return totalValue + position.purchase_amount_local * position.exchange_rate;
    },
    0,
  );
  const dashboardTotal = data
    ? dashboardSecuritiesValue + (summary?.cash_value_krw ?? 0)
    : undefined;
  const dashboardReturnPct = dashboardPurchaseValue
    ? (dashboardPnl / dashboardPurchaseValue) * 100
    : null;
  const cashRatio = dashboardTotal
    ? ((summary?.cash_value_krw ?? 0) / dashboardTotal) * 100
    : null;
  const topPositions = [...dashboardPositions]
    .sort((a, b) => (b.market_value_krw ?? 0) - (a.market_value_krw ?? 0))
    .slice(0, 3);
  const gainers = [...dashboardPositions]
    .filter((position) => position.unrealized_return != null)
    .sort((a, b) => (b.unrealized_return ?? 0) - (a.unrealized_return ?? 0));
  const best = gainers[0];
  const worst = gainers.at(-1);
  const market = new Map<string | null, number>();
  for (const position of dashboardPositions) {
    market.set(
      position.country,
      (market.get(position.country) ?? 0) + (position.market_value_krw ?? 0),
    );
  }
  const total = dashboardTotal ?? 0;
  const krWeight = total ? ((market.get("KR") ?? 0) / total) * 100 : 0;
  const usWeight = total ? ((market.get("US") ?? 0) / total) * 100 : 0;
  const cashWeight = total ? ((summary?.cash_value_krw ?? 0) / total) * 100 : 0;
  const donutStyle = {
    background: `conic-gradient(#2f78ed 0 ${krWeight}%, #1eb4cc ${krWeight}% ${krWeight + usWeight}%, #f3bd55 ${krWeight + usWeight}% ${krWeight + usWeight + cashWeight}%, #dce2eb ${krWeight + usWeight + cashWeight}% 100%)`,
  };

  return (
    <div className="mx-auto w-full max-w-[1480px] px-5 py-5 xl:px-6">
      <div className="grid gap-4 xl:grid-cols-3">
        <PortfolioPanel
          loading={overview.isLoading}
          total={dashboardTotal}
          returnPct={dashboardReturnPct}
          pnl={data ? dashboardPnl : undefined}
          cashRatio={cashRatio}
          topPositions={topPositions}
          donutStyle={donutStyle}
          allocation={[
            ["국내 주식", krWeight, "bg-blue-500"],
            ["해외 주식", usWeight, "bg-cyan-500"],
            ["현금", cashWeight, "bg-amber-400"],
            ["기타", Math.max(0, 100 - krWeight - usWeight - cashWeight), "bg-slate-300"],
          ]}
        />

        <NewsPanel />
        <PerformancePanel best={best} worst={worst} />
        <EventsPanel />
        <SystemPanel
          apiOk={!health.isError && health.data?.status === "ok"}
          portfolioOk={data?.sync_status === "SUCCESS"}
          lastSynced={data?.last_synced_at}
          jobs={jobStats.data}
        />
      </div>
    </div>
  );
}

function PanelTitle({
  title,
  action,
}: {
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 pb-3 pt-4">
      <h2 className="text-[18px] font-semibold tracking-tight text-slate-900">{title}</h2>
      {action}
    </div>
  );
}

function PortfolioPanel({
  loading,
  total,
  returnPct,
  pnl,
  cashRatio,
  topPositions,
  donutStyle,
  allocation,
}: {
  loading: boolean;
  total: number | undefined;
  returnPct: number | null | undefined;
  pnl: number | undefined;
  cashRatio: number | null;
  topPositions: { ticker: string | null; asset_name: string | null; market_value_krw: number | null; unrealized_return: number | null }[];
  donutStyle: React.CSSProperties;
  allocation: [string, number, string][];
}) {
  return (
    <Card className="overflow-hidden xl:col-span-2">
      <PanelTitle
        title="내 포트폴리오 현황"
        action={
          <button type="button" className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm">
            전체 포트폴리오 <ChevronDown className="h-3.5 w-3.5" />
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-3 px-5 md:grid-cols-4">
        <PortfolioMetric label="총 자산 (KRW)" value={loading ? "…" : formatKrw(total)} detail="실시간 포트폴리오 기준" />
        <PortfolioMetric label="총 수익률" value={loading ? "…" : formatPercent(returnPct)} detail="누적 평가손익 기준" positive={(returnPct ?? 0) >= 0} />
        <PortfolioMetric label="평가 손익" value={loading ? "…" : formatKrw(pnl)} detail="현재 보유 종목 기준" positive={(pnl ?? 0) >= 0} />
        <PortfolioMetric label="현금 비중" value={loading ? "…" : cashRatio == null ? "—" : `${cashRatio.toFixed(1)}%`} detail="국내·해외 예수금 합산" />
      </div>

      <div className="grid gap-3 p-5 pt-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3.5">
          <h3 className="text-sm font-semibold text-slate-800">자산 배분</h3>
          <div className="mt-3 flex items-center gap-4">
            <div className="relative h-24 w-24 shrink-0 rounded-full" style={donutStyle}>
              <div className="absolute inset-[17px] flex flex-col items-center justify-center rounded-full bg-white text-center">
                <span className="text-[10px] text-slate-400">총 자산</span>
                <span className="text-xs font-semibold text-slate-800">{total ? `${(total / 1_000_000).toFixed(1)}M` : "—"}</span>
              </div>
            </div>
            <div className="min-w-0 flex-1 space-y-1.5">
              {allocation.slice(0, 3).map(([label, value, color]) => (
                <div key={label} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="flex items-center gap-1.5 text-slate-500"><span className={cn("h-2 w-2 rounded-full", color)} />{label}</span>
                  <span className="font-medium tabular-nums text-slate-700">{value.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3.5">
          <h3 className="text-sm font-semibold text-slate-800">보유 종목 TOP 3</h3>
          <div className="mt-2 divide-y divide-slate-200/80">
            {topPositions.length ? topPositions.map((position, index) => (
              <div key={`${position.ticker}-${index}`} className="flex items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <div className="truncate text-xs font-semibold text-slate-800">{position.ticker ?? "—"}</div>
                  <div className="truncate text-[10px] text-slate-400">{position.asset_name ?? "보유 종목"}</div>
                </div>
                <div className="text-right">
                  <div className="text-[11px] font-medium text-blue-600">{total && position.market_value_krw ? `${((position.market_value_krw / total) * 100).toFixed(1)}%` : "—"}</div>
                  <div className={cn("text-[10px]", (position.unrealized_return ?? 0) >= 0 ? "text-emerald-600" : "text-rose-500")}>{formatPercent(position.unrealized_return)}</div>
                </div>
              </div>
            )) : <div className="py-8 text-center text-xs text-slate-400">동기화된 보유 종목이 없습니다.</div>}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3.5">
          <h3 className="text-sm font-semibold text-slate-800">위험 지표</h3>
          <div className="mt-3 space-y-3">
            <RiskRow label="포트폴리오 변동성" value="연동 예정" progress={56} />
            <RiskRow label="샤프 비율" value="연동 예정" progress={48} />
            <RiskRow label="최대 낙폭 (MDD)" value="연동 예정" progress={36} />
          </div>
        </div>
      </div>
    </Card>
  );
}

function PortfolioMetric({ label, value, detail, positive }: { label: string; value: string; detail: string; positive?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3.5 py-3.5 shadow-sm">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className={cn("mt-2 text-lg font-semibold tracking-tight tabular-nums", positive === undefined ? "text-slate-900" : positive ? "text-emerald-600" : "text-rose-500")}>{value}</div>
      <div className="mt-2 text-[10px] text-slate-400">{detail}</div>
    </div>
  );
}

function RiskRow({ label, value, progress }: { label: string; value: string; progress: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2 text-[11px]"><span className="text-slate-500">{label}</span><span className="font-medium text-slate-700">{value}</span></div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-500" style={{ width: `${progress}%` }} /></div>
    </div>
  );
}

function NewsPanel() {
  return (
    <Card className="overflow-hidden">
      <PanelTitle title="실시간 뉴스" action={<button type="button" className="text-xs font-medium text-blue-600">더보기</button>} />
      <div className="divide-y divide-slate-100 px-5">
        {news.map(([source, headline, time], index) => (
          <button key={headline} type="button" className="flex w-full items-center gap-3 py-3 text-left hover:bg-slate-50">
            <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[9px] font-bold text-white", index % 3 === 0 ? "bg-blue-600" : index % 3 === 1 ? "bg-slate-700" : "bg-teal-600")}>{source.slice(0, 2)}</span>
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium text-slate-800">{headline}</span><span className="mt-0.5 block text-[10px] text-slate-400">{source}</span></span>
            <span className="flex shrink-0 items-center gap-1 text-[10px] text-slate-400">{time}<ExternalLink className="h-3.5 w-3.5" /></span>
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 border-t border-slate-200 px-5 py-3 text-xs text-slate-500"><span className="h-2 w-2 rounded-full bg-emerald-500" />뉴스 수집 파이프라인 연결 예정</div>
    </Card>
  );
}

function PerformancePanel({ best, worst }: { best: { ticker: string | null; unrealized_return: number | null } | undefined; worst: { ticker: string | null; unrealized_return: number | null } | undefined }) {
  return (
    <Card className="overflow-hidden">
      <PanelTitle title="최근 성과 분석" action={<button type="button" className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-500">6개월 <ChevronDown className="h-3 w-3" /></button>} />
      <div className="px-5">
        <div className="flex items-center justify-between text-[10px] text-slate-400"><span>누적 수익률 (%)</span><span className="flex gap-3"><i className="inline-block h-0.5 w-3 bg-blue-500" />나의 포트폴리오 <i className="inline-block h-0.5 w-3 bg-slate-400" />벤치마크</span></div>
        <PerformanceChart />
        <div className="mt-2 grid grid-cols-2 gap-2">
          <PerformanceBadge label="Best" position={best} positive />
          <PerformanceBadge label="Worst" position={worst} />
        </div>
        <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-blue-700"><Bot className="h-4 w-4" />AI Agent 코멘트</div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-600">성과 원인 분석과 리스크 요약이 이 영역에 표시됩니다.</p>
        </div>
      </div>
    </Card>
  );
}

function PerformanceChart() {
  return <svg viewBox="0 0 420 142" className="mt-2 h-36 w-full" aria-label="성과 추이 프리뷰"><g stroke="#e5e7eb" strokeWidth="1"><line x1="0" y1="20" x2="420" y2="20" /><line x1="0" y1="55" x2="420" y2="55" /><line x1="0" y1="90" x2="420" y2="90" /><line x1="0" y1="125" x2="420" y2="125" /></g><path d="M0 95 C22 100 34 91 52 93 S83 86 100 82 S130 69 151 65 S182 54 204 60 S235 45 250 51 S280 38 302 44 S334 28 355 35 S389 31 420 20" fill="none" stroke="#2878f0" strokeWidth="3" /><path d="M0 98 C20 100 39 97 58 101 S92 94 108 96 S139 82 157 88 S193 76 212 79 S251 70 272 78 S311 61 330 68 S374 59 420 57" fill="none" stroke="#94a3b8" strokeWidth="2.5" /><g fill="#94a3b8" fontSize="9"><text x="0" y="140">'25.11</text><text x="76" y="140">'25.12</text><text x="154" y="140">'26.01</text><text x="232" y="140">'26.02</text><text x="310" y="140">'26.03</text><text x="386" y="140">'26.04</text></g></svg>;
}

function PerformanceBadge({ label, position, positive }: { label: string; position: { ticker: string | null; unrealized_return: number | null } | undefined; positive?: boolean }) {
  const isPositive = position ? (position.unrealized_return ?? 0) >= 0 : positive;
  return <div className={cn("rounded-md border px-3 py-2", isPositive ? "border-emerald-200 bg-emerald-50/60" : "border-rose-200 bg-rose-50/60")}><div className={cn("text-[10px] font-semibold", isPositive ? "text-emerald-600" : "text-rose-500")}>{label}</div><div className="mt-0.5 flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{position?.ticker ?? "—"}</span><span className={isPositive ? "text-emerald-600" : "text-rose-500"}>{formatPercent(position?.unrealized_return)}</span></div></div>;
}

function EventsPanel() {
  return <Card className="overflow-hidden"><PanelTitle title="주요 이벤트" /><div className="flex border-b border-slate-200 px-5 text-xs font-medium"><button type="button" className="border-b-2 border-blue-500 px-5 py-2 text-blue-600">매크로</button><button type="button" className="px-5 py-2 text-slate-500">종목</button><button type="button" className="px-5 py-2 text-slate-500">지정학</button></div><div className="px-5 pt-3"><div className="mb-2 text-xs font-medium text-slate-500">2026년 7월</div>{events.map(([day, weekday, time, country, title, priority]) => <div key={title} className="mb-2 flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2.5"><div className="w-8 text-center"><div className="text-lg font-semibold leading-none text-slate-800">{day}</div><div className="mt-1 text-[10px] text-slate-400">{weekday}</div></div><div className="min-w-0 flex-1"><div className="text-[10px] text-slate-400">{time} · {country}</div><div className="mt-0.5 truncate text-xs font-medium text-slate-700">{title}</div></div><span className={cn("rounded px-1.5 py-1 text-[10px] font-medium", priority === "높음" ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-500")}>중요도: {priority}</span></div>)}</div><button type="button" className="mt-1 flex w-full items-center justify-between border-t border-slate-200 px-5 py-3 text-xs font-medium text-blue-600">전체 일정 보기 <ChevronRight className="h-4 w-4" /></button></Card>;
}

function SystemPanel({ apiOk, portfolioOk, lastSynced, jobs }: { apiOk: boolean; portfolioOk: boolean; lastSynced: string | null | undefined; jobs: { total: number; pending: number; running: number; success: number; failed: number } | undefined }) {
  return <Card className="overflow-hidden"><PanelTitle title="시스템 상태" /><div className="space-y-2 px-5"><SystemRow icon={Newspaper} label="뉴스 수집" detail="파이프라인 설계 단계" ok={false} status="준비 중" /><SystemRow icon={Activity} label="시장 데이터" detail="실시간 수집 연동 예정" ok={false} status="준비 중" /><SystemRow icon={Landmark} label="포트폴리오 연동" detail={lastSynced ? `마지막 동기화 ${formatRelativeTime(lastSynced)}` : "동기화 이력 없음"} ok={portfolioOk} status={portfolioOk ? "정상" : "확인 필요"} /><SystemRow icon={ServerCog} label="API / 데이터베이스" detail={apiOk ? "백엔드 연결 상태" : "연결 확인 필요"} ok={apiOk} status={apiOk ? "정상" : "오류"} /></div><div className="mx-5 mt-3 rounded-lg border border-slate-200 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-slate-700"><Sparkles className="h-4 w-4 text-blue-600" />AI 모델 사용량 <span className="ml-auto text-slate-500">연동 예정</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full w-[64%] rounded-full bg-blue-500" /></div><div className="mt-1.5 flex justify-between text-[10px] text-slate-400"><span>Usage preview</span><span>64%</span></div></div><div className="mx-5 mt-3 rounded-lg border border-slate-200 p-3"><div className="flex items-center justify-between text-xs font-semibold text-slate-700"><span>최근 작업</span><span className="text-blue-600">전체 보기</span></div><div className="mt-2 space-y-1.5 text-[11px] text-slate-500"><div className="flex items-center justify-between"><span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />성공 작업</span><span>{jobs?.success ?? "—"}</span></div><div className="flex items-center justify-between"><span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-blue-500" />진행 중 작업</span><span>{(jobs?.pending ?? 0) + (jobs?.running ?? 0)}</span></div></div></div></Card>;
}

function SystemRow({ icon: Icon, label, detail, ok, status }: { icon: typeof Activity; label: string; detail: string; ok: boolean; status: string }) {
  return <div className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2.5"><div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-50"><Icon className="h-4 w-4 text-blue-600" /></div><div className="min-w-0 flex-1"><div className="text-xs font-semibold text-slate-700">{label}</div><div className="mt-0.5 truncate text-[10px] text-slate-400">{detail}</div></div><span className={cn("flex items-center gap-1 text-[11px] font-medium", ok ? "text-emerald-600" : "text-slate-400")}><span className={cn("h-2 w-2 rounded-full", ok ? "bg-emerald-500" : "bg-slate-300")} />{status}</span></div>;
}
