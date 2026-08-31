"use client";

import { useQuery } from "@tanstack/react-query";
import { getPriceReturns, type PriceReturnAsset } from "@/lib/api";
import { EMDASH, moveColor } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [주목해야할 지수 / 자산 수익률 변동] — 우하단 2칸 (ETF 순매수 모니터 바로 아래,
// 같은 폭. 2026-08-26). 관심 자산(금·비트코인·30년 국채금리)의 YtD·MtD·WtD·DtD +
// 저점 대비 상승 + 1년 스파크. 계산은 전부 collector price_returns.py — 여기는
// 표시만 한다. 자산을 바꾸려면 그쪽 ASSETS 를 고친다(제목은 고정 문구).
//
// 표시 형태(사용자 지시 2026-08-26): ETF 순매수 카드처럼 가로 줄로 나누고,
//   각 줄 왼쪽 위에 자산명 bold → 밑에 YtD·MtD·WtD·DtD + 저점 대비 상승 1개,
//   맨 오른쪽에 1년 시계열 스파크(지수 스트립과 같은 viewBox 0 0 100 28).

const POLL_MS = 30_000; // 같은 화면의 다른 카드와 같은 주기 (원천 xlsx 는 일단위 갱신)

// unit="pct" 는 %수익률, "bp" 는 금리 변화폭. 금리를 %변화율로 내면 오해를 부르니
// (4%→5% 가 +25%) collector 가 단위를 정하고 여기는 그대로 붙여 그린다.
function fmtDelta(v: number | null | undefined, unit: "pct" | "bp"): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (unit === "bp") return `${sign}${a >= 100 ? a.toFixed(0) : a.toFixed(1)}bp`;
  return `${sign}${a.toFixed(2)}%`;
}

function fmtLevel(v: number): string {
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

// 지수 스트립의 Spark 와 같은 접기 — 값 배열을 폭 100 높이 28 path 로.
// 색은 1년 처음-마지막 부호(상승 빨강/하락 파랑, 화면 공통 idiom).
function Spark({ pts }: { pts: number[] }) {
  if (!pts || pts.length < 2) return <div className="h-7 w-[76px]" />;
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const span = hi - lo || 1;
  const d = pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * 100;
      const y = 26 - ((v - lo) / span) * 24;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = pts[pts.length - 1] >= pts[0] ? "#e11d48" : "#2563eb";
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-7 w-[76px] shrink-0">
      <path d={d} fill="none" stroke={stroke} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Metric({ label, value, unit }: {
  label: string;
  value: number | null;
  unit: "pct" | "bp";
}) {
  return (
    <span>
      {label}{" "}
      <b className={cn("font-bold", moveColor(value))}>{fmtDelta(value, unit)}</b>
    </span>
  );
}

function AssetRow({ a }: { a: PriceReturnAsset }) {
  return (
    // flex-1 로 자산 수만큼 세로 균등 분할(ETF 카드와 같은 접근) — 항목엔 min-h-0
    // 을 주지 않아 내용 밑으로는 안 줄고, 넘치면 컨테이너가 스크롤로 강등.
    // ★배치(사용자 지시 2026-08-26 3차): 왼쪽 = 자산명 + YtD~DtD 세로 스택(박스
    //   왼쪽에 붙임), 오른쪽 = 저점 대비를 크게, 맨 오른쪽 = 1년 스파크.
    //   자산명은 확실한 검정, 지표 라벨은 적당한 검정(slate-800).
    <div className="flex flex-1 items-center gap-2 px-1.5 py-0.5">
      <div className="min-w-0 shrink-0">
        <div className="flex items-baseline gap-x-2">
          <span className="text-[17px] font-extrabold leading-snug text-black">{a.name}</span>
          <span className="shrink-0 text-[12px] tabular-nums text-slate-500">
            {fmtLevel(a.last)}
            {a.unit === "bp" ? "%" : ""}
          </span>
        </div>
        <div className="mt-0.5 flex flex-col text-[13px] leading-snug tabular-nums text-slate-800">
          <Metric label="YtD" value={a.returns.ytd} unit={a.unit} />
          <Metric label="MtD" value={a.returns.mtd} unit={a.unit} />
          <Metric label="WtD" value={a.returns.wtd} unit={a.unit} />
          <Metric label="DtD" value={a.returns.dtd} unit={a.unit} />
        </div>
      </div>
      {a.rebound ? (
        // 저점 대비 — 오른쪽에 크게(라벨 → 큰 수치 → 저점 상세 3줄).
        <div className="min-w-0 flex-1 text-right">
          <div className="text-[13px] font-semibold text-slate-800">{a.rebound.label}</div>
          <div
            className={cn(
              "text-[21px] font-extrabold leading-tight tabular-nums",
              moveColor(a.rebound.value),
            )}
          >
            {fmtDelta(a.rebound.value, a.unit)}
          </div>
          <div className="text-[12px] tabular-nums text-slate-500">
            {a.rebound.low_date.slice(5).replace("-", "/")} 에 {fmtLevel(a.rebound.low)} 로 저점
          </div>
        </div>
      ) : (
        <div className="flex-1" />
      )}
      <Spark pts={a.spark} />
    </div>
  );
}

export function PriceReturnCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["price-returns"],
    queryFn: getPriceReturns,
    refetchInterval: POLL_MS,
  });
  const assets = data?.assets ?? [];

  return (
    // 우하단 고정: 6열 그리드의 5~6열 × 2행. row-start 를 명시해 아래 행에 다른
    // 카드가 먼저 들어와도 자리가 밀리지 않는다.
    <section className="lg:col-span-2 lg:col-start-5 lg:row-start-2 flex min-h-0 flex-col rounded-xl border border-hairline bg-canvas">
      {/* 제목은 자산 나열 없이 고정 문구(사용자 확정 2026-08-26). */}
      <header className="flex items-center gap-2 border-b border-hairline px-3 py-2">
        <h2 className="min-w-0 truncate text-[13px] font-extrabold text-ink">
          주목해야할 지수 / 자산 수익률 변동
        </h2>
        {data?.asof ? (
          <span className="ml-auto shrink-0 text-[11px] tabular-nums text-slate-400">
            {data.asof} 기준
          </span>
        ) : null}
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : assets.length === 0 ? (
        <Center msg="price_monitor.xlsx 판독 대기 중 — 데이터가 들어오면 자동 표시됩니다." />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col divide-y divide-hairline/60 overflow-y-auto">
          {assets.map((a) => (
            <AssetRow key={a.key} a={a} />
          ))}
        </div>
      )}
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
      <span className={cn("text-[12px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
