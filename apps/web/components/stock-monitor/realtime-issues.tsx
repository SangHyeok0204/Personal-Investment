"use client";

import type { StockMonitorRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// [실시간 급등락 종목] — 카드 몸통. 상위 3 · 하위 3 을 **무조건** 보여준다
// (사용자 지시 2026-08-27).
//
// ★이전 버전은 "|등락률| ≥ 2% 인 1위" 만 헤드라인으로 뽑아서, 조용한 날엔 카드가
//   "지금 특이 급등락 없음" 한 줄로 비었다. 이제 문턱 없이 정렬 상위/하위를 그대로
//   채운다 — 조용한 날에도 오늘 뭐가 제일 움직였는지는 항상 보여야 하기 때문이다.
//   (거래량 급증 줄은 6줄과 자리를 다툴 수 없어 뺐다. 이상탐지는 표 팝업의
//    등락σ·거래량z 컬럼이 계속 한다.)
//
// 계산은 이 화면이 이미 받는 monitor rows 안에서 끝난다 — collector 변경 없음.
// 시각은 항목별 발화 시각이 아니라 스냅샷 기준 시각(asof) 하나다.

const TOP_N = 3;

function pickMovers(rows: StockMonitorRow[]) {
  const valid = rows.filter((r) => typeof r.change_pct === "number");
  const desc = [...valid].sort((a, b) => b.change_pct! - a.change_pct!);
  const up = desc.slice(0, TOP_N);
  // 유니버스가 6종목 미만이면 상·하위가 겹칠 수 있다 — 위에 쓴 종목은 뺀다.
  const taken = new Set(up.map((r) => r.symbol));
  const down = [...valid]
    .sort((a, b) => a.change_pct! - b.change_pct!)
    .filter((r) => !taken.has(r.symbol))
    .slice(0, TOP_N);
  return { up, down };
}

const pct1 = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export function RealtimeIssues({
  rows,
  asof,
  isLoading,
  isError,
  note,
}: {
  rows: StockMonitorRow[];
  asof: string | null;
  isLoading: boolean;
  isError: boolean;
  note?: string | null;
}) {
  if (isLoading) return <Center msg="불러오는 중…" />;
  if (isError)
    return <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />;
  if (rows.length === 0)
    return <Center msg={note ?? "오늘 분봉이 아직 없습니다."} />;

  const { up, down } = pickMovers(rows);
  const hhmm = asof ? asof.slice(11, 16) : null;

  if (up.length === 0)
    return <Center msg={note ?? "등락률이 있는 종목이 아직 없습니다."} />;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 py-2">
      <Group label="급등 상위" rows={up} tone="text-rose-600" />
      <Group label="급락 하위" rows={down} tone="text-blue-600" />
      {hhmm ? (
        <div className="shrink-0 pt-1.5 text-right text-[10.5px] tabular-nums text-slate-400">
          {hhmm} 기준
        </div>
      ) : null}
    </div>
  );
}

function Group({
  label,
  rows,
  tone,
}: {
  label: string;
  rows: StockMonitorRow[];
  tone: string;
}) {
  if (rows.length === 0) return null;
  return (
    // flex-1 로 두 그룹이 카드 세로를 반씩 나눠 갖는다(항목엔 min-h-0 을 주지
    // 않아 내용 밑으로는 안 줄고, 좁으면 컨테이너가 스크롤로 강등).
    <div className="flex flex-1 flex-col justify-center">
      <div className="shrink-0 text-[10.5px] font-bold text-ink-muted">{label}</div>
      {rows.map((r) => (
        <div
          key={r.symbol}
          className="flex items-baseline justify-between gap-2 py-0.5"
        >
          <span className="min-w-0 truncate text-[15px] font-extrabold text-ink">
            {r.name || r.symbol}
          </span>
          <span
            className={cn(
              "shrink-0 text-[15px] font-extrabold tabular-nums",
              tone,
            )}
          >
            {pct1(r.change_pct!)}
          </span>
        </div>
      ))}
    </div>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
      <span className={cn("text-[13px] font-semibold text-ink-muted", tone)}>{msg}</span>
    </div>
  );
}
