"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Star } from "lucide-react";
import {
  getUsEarnings,
  type EarningsPayload,
  type EarningsResult,
  type EarningsUpcoming,
  type EarningsWatchpoint,
} from "@/lib/api";
import { TabChips } from "@/components/ai-key-data/tab-chips";
import { EMDASH } from "@/components/stock-monitor/format";
import { fmtDay, fmtStamp } from "@/components/stock-us/format";
import { cn } from "@/lib/utils";

// [종목 모니터링 · 미국] 어닝 카드 — 화면 왼쪽 절반.
//
// 데이터는 전부 S: 어닝모니터 daily-server 가 굽는다(크롤 → SEC 8-K → claude CLI
// 관전포인트/시장반응 → Slack). 이 카드는 collector 가 마스터 원장에서 읽어 낸 것을
// 그리기만 한다 — 계산도, 판단 문구도 여기서 만들지 않는다.
//
// ★탭을 결과/예정으로 가른 이유: 두 목록은 **필드 집합 자체가 다르다**. 마스터가 티커당
//   한 행에 다음 분기와 직전 분기를 같이 담아서, 예정 행의 결과 열은 아직 지난 분기 값이다
//   (collector `earnings_monitor.py` 상단 주석). 한 표에 섞으면 그 함정을 화면이 그대로
//   물려받는다.
// ★행을 접어 둔 이유: 관전포인트 결과가 종목당 3~4문단이라 다 펴 두면 하루치가 화면을
//   넘긴다. 접힌 줄에는 '무엇이 언제 발표됐고 컨센서스 대비 어땠나'만 두고, 근거 문장은
//   펴서 읽는다.
//
// 폴링 30초 — 상류는 KST 새벽·저녁 슬롯에만 쓰므로 대개 아무것도 안 바뀌지만,
// 같은 배선을 한국·중국 탭이 이어받을 것이라 장중 갱신을 전제로 잡아 둔다.
const POLL_MS = 30_000;

type Tab = "results" | "upcoming";

function fmtEps(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return v.toFixed(2);
}

// 컨센서스 판정은 상류가 EPS·매출을 같이 보고 매긴다. 색은 국내 관례(상회 빨강 / 하회 파랑).
const CONSENSUS_TONE: Record<string, string> = {
  상회: "bg-rose-50 text-rose-600 ring-rose-200",
  하회: "bg-blue-50 text-blue-600 ring-blue-200",
  부합: "bg-slate-100 text-ink-secondary ring-slate-200",
};

function SessionBadge({ session }: { session: "AMC" | "BMO" | null }) {
  if (!session) return null;
  return (
    <span
      className="shrink-0 rounded px-1 py-px text-[10.5px] font-bold text-ink-muted ring-1 ring-hairline"
      title={session === "AMC" ? "장 마감 후 발표" : "장 개시 전 발표"}
    >
      {session}
    </span>
  );
}

function Watchpoints({ items }: { items: EarningsWatchpoint[] }) {
  if (items.length === 0) {
    return (
      <div className="text-[12.5px] text-ink-faint">관전포인트가 아직 없습니다.</div>
    );
  }
  return (
    <ol className="flex flex-col gap-1.5">
      {items.map((w, i) => (
        <li key={i} className="flex gap-2">
          <span className="mt-px shrink-0 text-[11px] font-extrabold tabular-nums text-ge-point">
            {i + 1}
          </span>
          <div className="min-w-0">
            <div className="text-[12.5px] font-semibold leading-snug text-ink">
              {w.point}
            </div>
            {/* 결과는 발표 다음 슬롯에 붙는다 — 그전까지는 '분석 대기'로 비워 둔다. */}
            {w.result === undefined ? null : w.result ? (
              <div className="mt-0.5 text-[12.5px] leading-snug text-ink-secondary">
                {w.result}
              </div>
            ) : (
              <div className="mt-0.5 text-[12px] text-ink-faint">분석 대기</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Row({
  row,
  open,
  onToggle,
}: {
  row: EarningsUpcoming | EarningsResult;
  open: boolean;
  onToggle: () => void;
}) {
  const result = "consensus" in row ? row : null;
  const tone = result?.consensus ? CONSENSUS_TONE[result.consensus] : null;

  return (
    <div className="border-b border-hairline/70 last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-ge-blue-bg/50"
      >
        <ChevronDown
          className={cn(
            "mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform",
            open && "rotate-180",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0 text-[13px] font-extrabold tracking-tight text-ink">
              {row.ticker}
            </span>
            {row.highlight && (
              <Star
                className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400"
                aria-label="하이라이트 종목"
              />
            )}
            <span className="min-w-0 truncate text-[12.5px] text-ink-secondary">
              {row.name}
            </span>
            {!row.active && (
              <span className="shrink-0 rounded bg-slate-100 px-1 py-px text-[10.5px] font-semibold text-ink-faint">
                미보유
              </span>
            )}
            <SessionBadge session={row.session} />
            {tone && (
              <span
                className={cn(
                  "ml-auto shrink-0 rounded px-1.5 py-px text-[11px] font-bold ring-1",
                  tone,
                )}
              >
                {result?.consensus}
              </span>
            )}
          </div>

          {/* 숫자 줄 — 결과는 실적(예상), 예정은 예상만. 매출은 상류가 이미 사람이 읽는
              꼴("2.71B")로 만들어 둔 문자열이라 그대로 쓴다. */}
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[12px] text-ink-muted">
            {result ? (
              <>
                <span className="tabular-nums">
                  EPS{" "}
                  <b className="font-extrabold text-ink">{fmtEps(result.epsActual)}</b>
                  <span className="text-ink-faint"> (예상 {fmtEps(result.epsEstimate)})</span>
                </span>
                <span className="tabular-nums">
                  매출{" "}
                  <b className="font-extrabold text-ink">
                    {result.revenueActual ?? EMDASH}
                  </b>
                  <span className="text-ink-faint">
                    {" "}
                    (예상 {result.revenueEstimate ?? EMDASH})
                  </span>
                </span>
                {result.quarter && <span>{result.quarter}</span>}
              </>
            ) : (
              <>
                <span className="tabular-nums">
                  예상 EPS{" "}
                  <b className="font-extrabold text-ink">{fmtEps(row.epsEstimate)}</b>
                </span>
                <span className="tabular-nums">
                  예상 매출{" "}
                  <b className="font-extrabold text-ink">
                    {row.revenueEstimate ?? EMDASH}
                  </b>
                </span>
              </>
            )}
            {row.marketCap && <span>시총 {row.marketCap}</span>}
          </div>
        </div>
      </button>

      {open && (
        <div className="flex flex-col gap-2.5 border-t border-hairline/70 bg-canvas-soft/60 px-3 py-2.5 pl-8">
          {result?.keyMetric && (
            <div className="text-[12.5px]">
              <span className="font-bold text-ge-navy">{result.keyMetric}</span>
              <span className="text-ink-secondary">
                {" "}
                {result.keyMetricResult ?? EMDASH}
              </span>
            </div>
          )}
          <Watchpoints items={row.watchpoints} />
          {result?.reaction && (
            <div className="rounded-md bg-ge-blue-bg/70 px-2.5 py-2 text-[12.5px] leading-snug text-ink-secondary">
              <span className="font-bold text-ge-point">시장 반응 </span>
              {result.reaction}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-3 text-[11.5px] text-ink-faint">
            {row.funds.length > 0 && <span>보유 {row.funds.join(" · ")}</span>}
            {row.updatedAt && <span>갱신 {fmtStamp(row.updatedAt)}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export function EarningsCard() {
  const [tab, setTab] = useState<Tab>("results");
  const [activeOnly, setActiveOnly] = useState(true);
  const [openKey, setOpenKey] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<EarningsPayload>({
    queryKey: ["us-earnings"],
    queryFn: getUsEarnings,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  const results = useMemo(
    () => (data?.results ?? []).filter((r) => !activeOnly || r.active),
    [data, activeOnly],
  );
  const upcoming = useMemo(
    () => (data?.upcoming ?? []).filter((r) => !activeOnly || r.active),
    [data, activeOnly],
  );

  const rows: (EarningsUpcoming | EarningsResult)[] =
    tab === "results" ? results : upcoming;

  // 날짜 묶음 — 같은 날 발표가 5~14건씩 몰려서, 줄마다 날짜를 반복하면 그것만 읽힌다.
  const groups = useMemo(() => {
    const out: { date: string | null; rows: typeof rows }[] = [];
    for (const r of rows) {
      const last = out[out.length - 1];
      if (last && last.date === r.date) last.rows.push(r);
      else out.push({ date: r.date, rows: [r] });
    }
    return out;
  }, [rows]);

  const tabs = [
    { key: "results" as const, label: `결과 ${results.length}` },
    { key: "upcoming" as const, label: `예정 ${upcoming.length}` },
  ];

  return (
    <section className="flex min-h-0 min-w-0 flex-col border-r border-hairline bg-canvas">
      <header className="flex shrink-0 items-center gap-2 bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">어닝</h2>
        <TabChips tabs={tabs} value={tab} onChange={setTab} />
        <button
          type="button"
          onClick={() => setActiveOnly((v) => !v)}
          title="보유 중인 종목만 보기 (관리상태 = 활성)"
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[12px] font-bold transition-colors",
            activeOnly
              ? "bg-white text-ge-header"
              : "bg-white/15 text-white/75 hover:bg-white/30",
          )}
        >
          보유만
        </button>
        {/* 크롤링 서버가 조용하면 화면이 조용히 옛 판을 보여주지 않게 표시한다.
            ★마스터를 아예 못 읽은 경우(available=false)는 여기 걸지 않는다 — 그건
              서버가 조용한 게 아니라 이쪽이 못 읽은 것이고, 아래 note 가 그걸 말한다. */}
        {data?.available && data.stale && (
          <span className="shrink-0 text-[12px] font-bold text-amber-300">
            ⚠ 크롤링 서버 응답 없음
          </span>
        )}
        {/* available=false 일 때의 note 는 본문이 크게 말하므로 여기서는 겹쳐 쓰지 않는다. */}
        {data?.available && data.note && (
          <span className="min-w-0 truncate text-[12px] font-semibold text-amber-300">
            {data.note}
          </span>
        )}
        <span className="ml-auto shrink-0 text-[12px] tabular-nums text-white/60">
          {fmtStamp(data?.generatedAt ?? null)} 기준
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-[13.5px] font-semibold text-ink-muted">
            불러오는 중…
          </div>
        ) : isError ? (
          <div className="flex h-full items-center justify-center text-[13.5px] font-semibold text-rose-600">
            collector 에 못 닿았습니다.
          </div>
        ) : data && !data.available ? (
          // 마운트가 빠졌거나 마스터를 못 읽은 경우 — '발표가 없다'와 섞으면 안 된다.
          <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
            <div className="text-[13px] font-bold text-amber-600">
              마스터 원장을 읽지 못했습니다
            </div>
            <div className="text-[12px] text-ink-faint">{data.note}</div>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-[13px] text-ink-muted">
            {tab === "results"
              ? `최근 ${data?.windowDays ?? 0}일 안에 발표된 종목이 없습니다.`
              : "예정된 발표가 없습니다."}
          </div>
        ) : (
          groups.map((g) => (
            <div key={g.date ?? "none"}>
              <div className="sticky top-0 z-10 flex items-baseline gap-2 border-y border-hairline bg-ge-th px-3 py-1">
                <span className="text-[12px] font-extrabold text-ge-navy">
                  {fmtDay(g.date)}
                </span>
                <span className="text-[11.5px] text-ink-muted">{g.rows.length}건</span>
              </div>
              {g.rows.map((r) => {
                const key = `${tab}-${r.ticker}`;
                return (
                  <Row
                    key={key}
                    row={r}
                    open={openKey === key}
                    onToggle={() => setOpenKey(openKey === key ? null : key)}
                  />
                );
              })}
            </div>
          ))
        )}
      </div>

      {/* 원천이 어디이고 언제 살아 있었는지 — 화면이 비었을 때 어디를 봐야 하는지가 여기 있다. */}
      <footer className="flex shrink-0 items-center gap-2 border-t border-hairline bg-canvas-soft px-3 py-1 text-[11px] text-ink-faint">
        <span className="truncate">
          어닝모니터 마스터 원장 · ET {data?.asOfET ?? EMDASH} 기준
        </span>
        <span className="ml-auto shrink-0 tabular-nums">
          서버 heartbeat {fmtStamp(data?.heartbeat ?? null)}
        </span>
      </footer>
    </section>
  );
}
