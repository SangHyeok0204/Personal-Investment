"use client";

import { useQuery } from "@tanstack/react-query";
import { getEtfFlows, type EtfFlowRow } from "@/lib/api";
import { EMDASH, fmtInt, fmtWon, moveColor } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [ETF 순매수 모니터] — 우상단 1칸 (섹터별 등락률 자리, 2026-08-25 사용자 계획 변경).
// 관심 ETF(주로 신규상장)의 거래대금·거래량·개인 순매수. 원천은 CHECK 에이전트가
// 매초 보내는 호가 envelope 의 newEtfs 배열(collector /etf-flows 가 접어 준다).
//
// 표시 형태(사용자 확정 2026-08-25, 2026-08-28 1칸 폭에 맞춰 조정): 표가 아니라
// **종목별 블록**이다 —
//   1줄: 이름 크게 + (코드). 이름은 절대 자르지 않는다(줄바꿈은 허용).
//   그 아래: 거래대금 / 거래량 / 개인 순매수 / 개인 순매수(LP추정) 를 한 줄에 하나씩,
//   이름 왼쪽·값 오른쪽으로.
// 상장일은 화면에서 뺐다(신규상장 맥락은 헤더 멘트가 이미 말해 준다).
// 최대 ~5종 기준 — 블록마다 flex-1 로 세로를 꽉 채우고, 넘치면 스크롤로 강등.
// ★개인 순매수(LP기반 추정)는 피드에 아직 없는 값이라 − 로 비워 둔다 — 자리는
//   먼저 깔아 두고 CHECK 가 필드를 실으면 채운다(이 카드 자체와 같은 idiom).

const POLL_MS = 30_000; // 같은 화면의 다른 카드와 같은 주기

// 국내 ETF 신규상장은 관례적으로 화요일이다 — 멘트는 브라우저 시간대와 무관하게
// KST 요일로 판정한다.
function kstIsTuesday(): boolean {
  return new Date(Date.now() + 9 * 3_600_000).getUTCDay() === 2;
}

// 순매수는 음수가 있다 — fmtWon 은 양수 전용이라 부호를 밖에서 붙인다.
// ★단위는 **억원 고정**(2026-08-25 사용자 지시): 1억 미만이 원 단위로 떨어지면
//   한 종목만 자릿수가 튀어 옆 종목과 비교가 안 된다. 1억 미만은 소수 둘째
//   자리(+0.67억원), 그 이상은 기존 표기(fmtWon: 억/조 자동) 그대로.
function fmtNetWon(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  if (v === 0) return "0원";
  const a = Math.abs(v);
  const sign = v > 0 ? "+" : "−";
  if (a < 1e8) return `${sign}${(a / 1e8).toFixed(2)}억원`;
  return `${sign}${fmtWon(a)}`;
}

export function EtfFlowCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["etf-flows"],
    queryFn: getEtfFlows,
    refetchInterval: POLL_MS,
  });
  const rows: EtfFlowRow[] = data?.rows ?? [];
  const hhmm = data?.asof ? data.asof.slice(11, 16) : null;
  const tuesday = kstIsTuesday();

  // ★2026-08-28 폭을 2칸 → **1칸**으로 줄였다(사용자 지시). 6열 그리드의 마지막 열
  //   하나(≈280px)만 쓴다 — col-start-6 을 못 박아야 왼쪽 빈자리로 흘러들지 않는다.
  //   좁아진 만큼 헤더와 지표 줄은 가로 한 줄을 포기하고 **세로로 쌓는다**(아래 참고).
  // 테두리는 아래 한 줄만 — 오른쪽은 화면 끝이고, 밑칸은 비어 있어 선이 없으면 뜬다.
  return (
    <section className="lg:col-span-1 lg:col-start-6 flex min-h-0 flex-col border-b border-hairline bg-canvas">
      {/* 제목 띠 — 강조색(ge-header). 배경이 어두우니 글자를 흰색 계열로 뒤집는다.
          1칸 폭에서는 제목+배지+시각이 한 줄에 안 들어가 2줄로 나눈다. */}
      <header className="flex shrink-0 flex-col gap-1 bg-ge-header px-2 py-1.5">
        <div className="flex items-baseline gap-1.5">
          <h2 className="shrink-0 text-[12.5px] font-extrabold text-white">
            ETF 순매수 모니터
          </h2>
          {hhmm ? (
            <span className="ml-auto shrink-0 text-[10px] tabular-nums text-white/60">
              {hhmm}
            </span>
          ) : null}
        </div>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-center text-[10px] font-bold leading-tight",
            tuesday ? "bg-white text-ge-header" : "bg-white/15 text-white/75",
          )}
        >
          {tuesday ? "오늘은 ETF 신규상장 날입니다" : "오늘은 ETF 상장 날이 아닙니다"}
        </span>
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : rows.length === 0 ? (
        <Center msg="CHECK 에이전트 적재 대기 중 — 데이터가 들어오면 자동 표시됩니다." />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col divide-y divide-hairline/60 overflow-y-auto">
          {rows.map((r) => (
            // flex-1 이라 5종이면 5등분으로 꽉 찬다. 항목에 min-h-0 을 주지 않는 게
            // 요점 — 내용 높이 밑으로는 안 줄어들고, 6종 이상이면 컨테이너가 스크롤.
            <div key={r.code} className="flex flex-1 flex-col justify-center px-2.5 py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-1.5">
                {/* 이름은 truncate 금지(사용자 확정) — 길면 줄바꿈한다. */}
                <span className="text-[14px] font-extrabold leading-tight text-ink">
                  {r.name ?? r.code}
                </span>
                <span className="shrink-0 text-[10px] tabular-nums text-slate-400">
                  ({r.code})
                </span>
              </div>
              {/* ★1칸 폭(≈280px)에서는 "거래대금 | 거래량"처럼 가로로 이으면 줄바꿈이
                  구분자를 줄 끝에 남긴다. 그래서 **한 지표당 한 줄**, 이름은 왼쪽·값은
                  오른쪽으로 붙여 값의 자릿수가 세로로 맞게 한다. */}
              <div className="mt-0.5 flex flex-col text-[10.5px] leading-[1.45] tabular-nums">
                <Metric label="거래대금" value={fmtWon(r.trade_value)} />
                <Metric label="거래량" value={`${fmtInt(r.trade_volume)} 주`} />
                <Metric
                  label="개인 순매수"
                  value={fmtNetWon(r.indiv_net_buy)}
                  tone={moveColor(r.indiv_net_buy)}
                />
                <Metric
                  label="개인 순매수(LP추정)"
                  value={fmtNetWon(r.indiv_net_lp_est)}
                  tone={moveColor(r.indiv_net_lp_est)}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// 지표 한 줄 — 이름 왼쪽 / 값 오른쪽. 이름이 길면 줄바꿈해서 값을 밀지 않는다.
function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-1.5">
      <span className="min-w-0 text-ink-muted">{label}</span>
      <span className={cn("shrink-0 font-bold text-ink", tone)}>{value}</span>
    </div>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-3 text-center">
      <span className={cn("text-[12px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
