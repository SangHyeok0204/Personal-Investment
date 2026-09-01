"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  getEtfClass,
  type EtfAxisKey,
  type EtfGroupRow,
  type EtfIvKey,
  type EtfPeriodKey,
  type EtfRow,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import { DetailCard } from "@/components/etf-class/detail-card";
import { HistoryCard } from "@/components/etf-class/history-card";
import { IntervalCard } from "@/components/etf-class/interval-card";
import { RankCard, type RankMetric } from "@/components/etf-class/rank-card";
import { ScatterCard } from "@/components/etf-class/scatter-card";
import { fmtEok, fmtPct, tone } from "@/components/etf-class/format";
import { cn } from "@/lib/utils";

/* [국내상장 ETF] 분류별 개인 순매수와 성과.
 *
 * 무엇을 보는 화면인가: **장 끝나고, 개인 자금이 어느 분류로 몰렸고 그 분류의 수익률은
 * 어땠나.** daily_analysis 가 Slack 으로 쏘던 상·하위 10개 발췌를 전수(861종목) ·
 * 4계층 분류 · 5기간으로 편 것이다.
 *
 * 원천은 운용역이 매일 굽는 워크북 한 장(`국내상장ETF 모니터링.xlsm` value 시트)이고,
 * 분류(구분/대분류/중분류/소분류/투자국가)도 그 시트가 이미 갖고 있다 — 우리가 새 분류를
 * 만들지 않는다. 회의에서 쓰는 말과 화면의 말이 갈리면 안 되기 때문이다.
 *
 * ★★HISTORICAL 이 두 갈래인 이유. 워크북은 매일 덮어써서 과거가 없다. 그런데 시트가
 *   1주·1개월·3개월·6개월 **누적**을 같이 주므로, 누적끼리 빼면 겹치지 않는 4구간이
 *   나온다(= 구간 분해 카드, 첫날부터 그려진다). 진짜 일별 시계열은 collector 가
 *   스냅샷을 적재하면서 자란다(= 일별 누적 카드). 둘을 한 화면에 두되 서로 다른
 *   카드로 갈라 놓았다 — 성격이 다른 두 과거를 한 그래프에 섞으면 읽는 사람이 속는다.
 *
 * ★컨트롤 4개(축·기간 갈래·기간·지표)는 **전부 클라이언트 상태**다. 서버가 축 5개 ×
 *   기간 9개를 한 묶음에 실어 보내므로 재요청이 없다(집계식도 서버 한 곳에만 있다).
 */

const REFETCH = 600_000; // 10분 — 하루 한 번 갱신되는 워크북이라 더 자주 볼 이유가 없다

type Mode = "cum" | "iv";
type Weighting = "cap" | "equal";

// 분류 축 → ETF 한 줄에서 그 축의 그룹키를 만드는 열 순서.
// ★서버(etf_class.AXES)의 path + col 과 **같은 순서**여야 한다. 어긋나면 분류를 눌러도
//   상세 표가 비는데, 그게 "데이터가 없다"로 보여 오진을 부른다.
const AXIS_COLS: Record<EtfAxisKey, (keyof EtfRow)[]> = {
  gubun: ["gubun"],
  big: ["gubun", "big"],
  mid: ["gubun", "big", "mid"],
  small: ["gubun", "big", "mid", "small"],
  country: ["country"],
};

// 컨트롤 바가 첫 페인트에 무너지지 않게 두는 정적 사본. 서버가 보내는 목록도 상수라
// 값이 갈릴 일이 없고, 데이터가 오면 서버 것으로 덮는다(라벨·기간 창은 서버가 정본).
const FALLBACK_AXES: { key: EtfAxisKey; label: string }[] = [
  { key: "gubun", label: "구분" },
  { key: "big", label: "대분류" },
  { key: "mid", label: "중분류" },
  { key: "small", label: "소분류" },
  { key: "country", label: "투자국가" },
];
const FALLBACK_PERIODS = [
  { key: "d", label: "당일" },
  { key: "1w", label: "1주" },
  { key: "1m", label: "1개월" },
  { key: "3m", label: "3개월" },
  { key: "6m", label: "6개월" },
];
const FALLBACK_INTERVALS = [
  { key: "1w", label: "최근 1주" },
  { key: "1m", label: "1주~1개월" },
  { key: "3m", label: "1~3개월" },
  { key: "6m", label: "3~6개월" },
];

function etfGroupKey(e: EtfRow, axis: EtfAxisKey): string {
  return AXIS_COLS[axis].map((c) => (e[c] as string) || "미분류").join(" / ");
}

function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        "rounded-full px-3 py-1 text-[12px] font-bold transition-colors",
        active
          ? "bg-ge-point text-white shadow-card"
          : "bg-white text-ink-secondary hover:bg-ge-blue-bg hover:text-ge-point",
      )}
    >
      {children}
    </button>
  );
}

function ControlGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] font-bold tracking-wide text-ink-faint">
        {label}
      </span>
      <div className="flex items-center gap-1 rounded-full border border-hairline bg-canvas-soft p-0.5">
        {children}
      </div>
    </div>
  );
}

export default function EtfClassPage() {
  const [axis, setAxis] = useState<EtfAxisKey>("mid");
  const [mode, setMode] = useState<Mode>("cum");
  const [period, setPeriod] = useState<EtfPeriodKey>("d");
  const [metric, setMetric] = useState<RankMetric>("amount");
  const [weighting, setWeighting] = useState<Weighting>("cap");
  const [picked, setPicked] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["etf-class"],
    queryFn: getEtfClass,
    refetchInterval: REFETCH,
  });

  const rows = data?.groups?.[axis] ?? [];

  // 구간(iv) 에는 '당일'이 없다 — 갈래를 바꿀 때 없는 기간에 남아 있지 않게 잡아 준다.
  const periodKey: EtfPeriodKey =
    mode === "iv" && period === "d" ? "1w" : period;

  const netOf = (r: EtfGroupRow) =>
    mode === "cum" ? r.net_cum[periodKey] : r.net_iv[periodKey as EtfIvKey] ?? null;
  const ratioOf = (r: EtfGroupRow) =>
    mode === "cum"
      ? r.ratio_cum[periodKey]
      : r.ratio_iv[periodKey as EtfIvKey] ?? null;
  const retOf = (r: EtfGroupRow) => {
    if (mode === "cum") {
      return weighting === "cap" ? r.ret_cum[periodKey] : r.ret_cum_eq[periodKey];
    }
    const k = periodKey as EtfIvKey;
    return weighting === "cap" ? r.ret_iv[k] ?? null : r.ret_iv_eq[k] ?? null;
  };

  // 고른 분류가 지금 축에 없으면(축을 바꾼 직후) 이 기간 순매수 1위로 떨어진다.
  const selected = useMemo(() => {
    if (picked && rows.some((r) => r.key === picked)) return picked;
    const top = [...rows].sort((a, b) => (netOf(b) ?? 0) - (netOf(a) ?? 0))[0];
    return top?.key ?? null;
  }, [picked, rows, mode, periodKey]);

  const selectedRow = rows.find((r) => r.key === selected) ?? null;
  const detailEtfs = useMemo(
    () =>
      selected
        ? (data?.etfs ?? []).filter((e) => etfGroupKey(e, axis) === selected)
        : [],
    [data, axis, selected],
  );

  const periodSpec = data?.periods.find((p) => p.key === periodKey);
  const ivSpec = data?.intervals.find((s) => s.key === periodKey);
  const periodLabel =
    (mode === "cum"
      ? (periodSpec?.label ??
        FALLBACK_PERIODS.find((p) => p.key === periodKey)?.label)
      : (ivSpec?.label ??
        FALLBACK_INTERVALS.find((p) => p.key === periodKey)?.label)) ?? "";
  const windowLabel =
    mode === "cum"
      ? periodSpec?.start && periodSpec.start !== periodSpec.end
        ? `${periodSpec.start} ~ ${periodSpec.end}`
        : (periodSpec?.end ?? "")
      : ivSpec
        ? `${ivSpec.start ?? ""} ~ ${ivSpec.end ?? ""}`
        : "";

  const ranked = useMemo(
    () => [...rows].sort((a, b) => (netOf(b) ?? 0) - (netOf(a) ?? 0)),
    [rows, mode, periodKey],
  );
  const inflow = ranked.slice(0, 3);
  const outflow = ranked.slice(-3).reverse();
  const totalNet = data?.totals ? netOf(data.totals) : null;

  return (
    <>
      <Topbar
        title="국내상장 ETF"
        subtitle={
          data?.asof
            ? `분류별 개인 순매수와 성과 · 기준일 ${data.asof} · ${data.etfs.length}종목`
            : "분류별 개인 순매수와 성과"
        }
        status={
          data?.source_modified ? (
            <span className="text-[11.5px] font-semibold text-ink-faint">
              워크북 {data.source_modified}
            </span>
          ) : undefined
        }
      />

      {/* 카드가 세로로 세 묶음이라 화면을 넘긴다 — 안쪽 스크롤을 만들지 않고
          문서 스크롤에 맡긴다(Topbar 가 sticky 라 헤더는 따라온다). */}
      <div className="min-h-screen bg-canvas-soft px-5 py-4">
        {error && (
          <div className="mb-3">
            <ApiErrorBanner error={error} />
          </div>
        )}
        {data?.note && (
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <p className="text-[12.5px] font-semibold text-amber-900">
              {data.note}
            </p>
          </div>
        )}

        {/* ── 요약 밴드 — 고른 기간의 전체 흐름과 양 끝 ─────────────────── */}
        <div className="mb-3 grid gap-3 lg:grid-cols-[minmax(0,220px)_minmax(0,1fr)_minmax(0,1fr)]">
          <div className="rounded-xl border border-hairline bg-canvas px-4 py-3 shadow-card">
            <div className="text-[11px] font-bold tracking-wide text-ink-faint">
              전체 개인 순매수 · {periodLabel}
            </div>
            <div
              className={cn(
                "mt-0.5 text-[26px] font-extrabold tabular-nums leading-tight",
                tone(totalNet),
              )}
            >
              {isLoading ? <Skeleton className="h-7 w-28" /> : fmtEok(totalNet)}
            </div>
            <div className="text-[11px] font-medium text-ink-faint">
              {windowLabel}
            </div>
          </div>
          <SummaryList title="자금이 몰린 분류" rows={inflow} netOf={netOf} retOf={retOf} />
          <SummaryList title="자금이 빠진 분류" rows={outflow} netOf={netOf} retOf={retOf} />
        </div>

        {/* ── 컨트롤 ─────────────────────────────────────────────────────── */}
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-hairline bg-canvas px-4 py-2.5 shadow-card">
          <ControlGroup label="분류">
            {(data?.axes ?? FALLBACK_AXES).map((a) => (
              <Chip key={a.key} active={axis === a.key} onClick={() => setAxis(a.key)}>
                {a.label}
              </Chip>
            ))}
          </ControlGroup>

          <ControlGroup label="기간">
            <Chip
              active={mode === "cum"}
              onClick={() => setMode("cum")}
              title="오늘로 끝나는 창 그대로 (당일·1주·1개월·3개월·6개월)"
            >
              누적
            </Chip>
            <Chip
              active={mode === "iv"}
              onClick={() => {
                setMode("iv");
                if (period === "d") setPeriod("1w");
              }}
              title="누적끼리 뺀, 서로 겹치지 않는 구간"
            >
              구간
            </Chip>
          </ControlGroup>

          <div className="flex items-center gap-1 rounded-full border border-hairline bg-canvas-soft p-0.5">
            {(mode === "cum"
              ? (data?.periods ?? FALLBACK_PERIODS)
              : (data?.intervals ?? FALLBACK_INTERVALS)
            ).map(
              (p) => (
                <Chip
                  key={p.key}
                  active={periodKey === p.key}
                  onClick={() => setPeriod(p.key as EtfPeriodKey)}
                  title={"start" in p && "end" in p ? `${p.start ?? ""} ~ ${p.end ?? ""}` : undefined}
                >
                  {p.label}
                </Chip>
              ),
            )}
          </div>

          <ControlGroup label="정렬">
            <Chip
              active={metric === "amount"}
              onClick={() => setMetric("amount")}
              title="절대 금액 — 규모가 큰 분류가 상위를 고정한다"
            >
              금액
            </Chip>
            <Chip
              active={metric === "ratio"}
              onClick={() => setMetric("ratio")}
              title="시총 대비 — 분류 크기를 걷어낸 유입 강도"
            >
              강도
            </Chip>
          </ControlGroup>

          <ControlGroup label="수익률">
            <Chip
              active={weighting === "cap"}
              onClick={() => setWeighting("cap")}
              title="시총가중(현재 시총 기준). 과거 구간에도 현재 시총을 쓰는 근사다."
            >
              시총가중
            </Chip>
            <Chip
              active={weighting === "equal"}
              onClick={() => setWeighting("equal")}
              title="단순평균 — daily_analysis 리포트의 중분류 평균과 같은 기준"
            >
              단순평균
            </Chip>
          </ControlGroup>
        </div>

        {isLoading ? (
          <div className="grid gap-3 lg:grid-cols-12">
            <Skeleton className="h-[560px] lg:col-span-7" />
            <Skeleton className="h-[560px] lg:col-span-5" />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-12">
              <div className="h-[560px] lg:col-span-7">
                <RankCard
                  rows={rows}
                  metric={metric}
                  netOf={netOf}
                  ratioOf={ratioOf}
                  retOf={retOf}
                  selected={selected}
                  onSelect={setPicked}
                  periodLabel={periodLabel}
                  windowLabel={windowLabel}
                />
              </div>
              <div className="h-[560px] lg:col-span-5">
                <ScatterCard
                  rows={rows}
                  ratioOf={ratioOf}
                  retOf={retOf}
                  netOf={netOf}
                  selected={selected}
                  onSelect={setPicked}
                  periodLabel={periodLabel}
                />
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-12">
              <div className="h-[470px] lg:col-span-7">
                <IntervalCard
                  rows={rows}
                  intervals={data?.intervals ?? []}
                  selected={selected}
                  onSelect={setPicked}
                />
              </div>
              <div className="h-[470px] lg:col-span-5">
                <DetailCard
                  title={selectedRow ? selectedRow.label : "분류를 고르세요"}
                  subtitle={
                    selectedRow
                      ? `${selectedRow.n}종목 · 시총 ${fmtEok(selectedRow.mcap, false)} · ${periodLabel}`
                      : ""
                  }
                  rows={detailEtfs}
                  periodKey={periodKey}
                  mode={mode}
                  periodLabel={periodLabel}
                />
              </div>
            </div>

            <div className="h-[340px]">
              <HistoryCard axis={axis} />
            </div>

            {/* ★숫자의 뜻을 화면에 적어 둔다 — 회의에서 "이 순매수가 뭐냐"가 나오면
                그 자리에서 답이 되어야 한다. */}
            <p className="px-1 pb-2 text-[11px] leading-relaxed text-ink-faint">
              개인 순매수·수익률 모두 원천 워크북(`국내상장ETF 모니터링.xlsm` value
              시트)의 값이다. 순매수는 <b>개인</b> 투자자 순매수(억원)이고, 기간 값은
              그 창의 일별 합계다. 분류 수익률 기본값은 <b>시총가중</b>(현재 시총 기준
              — 과거 구간에도 현재 시총을 쓰는 근사)이며, 단순평균으로도 볼 수 있다.
              레버리지·인버스 ETF 도 분류에 그대로 들어 있으므로 수익률 폭이 큰 분류는
              구성 종목을 함께 볼 것.
            </p>
          </div>
        )}
      </div>
    </>
  );
}

function SummaryList({
  title,
  rows,
  netOf,
  retOf,
}: {
  title: string;
  rows: EtfGroupRow[];
  netOf: (r: EtfGroupRow) => number | null;
  retOf: (r: EtfGroupRow) => number | null;
}) {
  return (
    <div className="rounded-xl border border-hairline bg-canvas px-4 py-3 shadow-card">
      <div className="text-[11px] font-bold tracking-wide text-ink-faint">
        {title}
      </div>
      <div className="mt-1 space-y-1">
        {rows.length === 0 && (
          <div className="text-[12px] text-ink-faint">—</div>
        )}
        {rows.map((r) => (
          <div key={r.key} className="flex items-baseline gap-2">
            <span className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink">
              {r.label}
              <span className="ml-1.5 text-[10.5px] font-medium text-ink-faint">
                {r.path[r.path.length - 1] ?? ""}
              </span>
            </span>
            <span
              className={cn(
                "shrink-0 text-[13px] font-extrabold tabular-nums",
                tone(netOf(r)),
              )}
            >
              {fmtEok(netOf(r))}
            </span>
            <span
              className={cn(
                "w-[62px] shrink-0 text-right text-[12px] font-bold tabular-nums",
                tone(retOf(r)),
              )}
            >
              {fmtPct(retOf(r), 1)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
