"use client";

import { useQuery } from "@tanstack/react-query";
import { getMarketSignal, type MarketSignalCard, type PriceCatKey } from "@/lib/api";
import type { PriceSel } from "@/components/stock-monitor/price-tree-card";
import { cn } from "@/lib/utils";

// [시장 시그널] — 종목 모니터 우상단 1칸. **ETF 순매수 모니터를 대체**한다(2026-08-31).
//
// 사용자 규격 그대로:
//   ===========================
//   [자산군] 에서 시그널이 감지
//   : (분석 내용 15자 내외 요약)
//   ===========================
//
// ★★문구는 **LLM 이 쓰지 않는다.** collector 의 2단(온톨로지 탐색)이 만드는
//   `summary`("암호화폐 전반 강세" = 9자)가 곧 그 요약이다. 판단은 1단 결정론 룰과
//   2단 그래프가 이미 끝냈으므로 LLM 을 부를 자리가 없다 — 부르면 오히려 결정론
//   결과를 흐리고, 컨테이너에 claude 가 없어 아키텍처도 갈라진다.
//
// ★근거 배지: 뉴스가 가설을 뒷받침하면 '근거확보', 아니면 '근거 대기'. 근거 없는
//   카드를 버리지 않는 이유는 뉴스가 늦게 붙는 사건이 많아서다 — 버리면 카드가 자주 빈다.
//
// ★★2026-09-01 폴링을 고쳤다 — "새로고침해야만 보인다"는 지적의 원인이 둘이었다:
//   ① **`refetchOnWindowFocus` 를 opt-in 하지 않았다.** 전역 providers.tsx 기본값이
//      `false` 이고, 이 저장소는 신규 쿼리마다 개별로 켜는 관용구다
//      (ai-usage-card.tsx 주석 참조). 그걸 빠뜨려 탭에 돌아와도 안 받아 왔다.
//   ② **`refetchIntervalInBackground` 가 없었다.** react-query 는 창이 포커스를 잃으면
//      interval 타이머를 **멈춘다**. 이 화면은 보조 모니터에 띄워 두는 대시보드라
//      그게 곧 "안 움직인다"가 된다.
// ★주기도 10분 → 2분으로 줄였다. 파이프라인이 매시+원천 mtime 캐시라 대부분의 폴링은
//   **캐시 적중 20ms** 다(실측). 실제 계산은 시각이 바뀌거나 시트가 갱신될 때만 돈다.
//   시트는 매 영업일 아침 ~7:45 에 갱신되므로, 2분이면 그 뒤 최대 2분 안에 반영된다.
const POLL_MS = 120_000;

// 자산군 배지 색 — 지표 리스트 탭과 같은 계열로 맞춘다.
const AC_TONE: Record<string, string> = {
  equity: "bg-rose-50 text-rose-700 ring-rose-200",
  bond: "bg-sky-50 text-sky-700 ring-sky-200",
  commodity: "bg-amber-50 text-amber-700 ring-amber-200",
  fx: "bg-violet-50 text-violet-700 ring-violet-200",
  crypto: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

// ★카드 클릭 → 가운데 차트 이동. 선택 상태(자산군 탭·시장)는 **페이지가 들고 있으므로**
//   여기서는 올려 보내기만 한다(지표 리스트 카드와 같은 구조).
export function MarketSignalCard({
  onSelect,
}: {
  onSelect?: (cat: PriceCatKey, sel: PriceSel) => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["market-signal"],
    queryFn: getMarketSignal,
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: true,   // 배경 탭에서도 타이머를 돌린다
    refetchOnWindowFocus: true,          // 전역 기본값(false)을 이 쿼리만 뒤집는다
  });
  const cards = data?.cards ?? [];
  // ★포착 시각 = `generated_at`(파이프라인이 실제로 돈 시각). 캐시로 응답해도 이 값은
  //   **계산 시점 그대로** 남는다 — 요청 시각이 아니라 시그널을 잡아낸 순간이다.
  const at = data?.generated_at ?? null;
  const caught = at ? `${at.slice(5, 10).replace("-", "/")} ${at.slice(11, 16)}` : null;

  return (
    // 6열 그리드의 마지막 열 상단 1칸. 아래 칸(수익률 요약)과 경계를 긋는 border-b 만.
    <section className="lg:col-span-1 lg:col-start-6 flex min-h-0 flex-col border-b border-hairline bg-canvas">
      <header className="flex shrink-0 flex-col gap-1 bg-ge-header px-2 py-1.5">
        <div className="flex items-baseline gap-1.5">
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">시장 시그널</h2>
          {caught ? (
            <span className="ml-auto shrink-0 text-[11.5px] font-semibold tabular-nums text-white/75">
              {caught} 포착
            </span>
          ) : null}
        </div>
        <span className="rounded bg-white/15 px-1.5 py-[3px] text-center text-[11.5px] font-bold leading-tight text-white/80">
          {data?.stats?.signals != null
            ? `${data.stats.markets}개 시장 · 시그널 ${data.stats.signals}건${
                data.asof ? ` · ${data.asof.slice(5).replace("-", "/")} 기준` : ""
              }`
            : "결정론 룰 + 지식그래프 + 뉴스"}
        </span>
      </header>

      {isLoading ? (
        <Center msg="시장을 훑는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : data?.note ? (
        <Center msg={data.note} tone="text-amber-600" />
      ) : cards.length === 0 ? (
        <Center msg="오늘은 임계를 넘은 시그널이 없습니다." />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col divide-y divide-hairline/60 overflow-y-auto">
          {cards.map((c, i) => (
            <SignalItem
              key={`${c.headline}-${i}`}
              c={c}
              first={i === 0}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SignalItem({
  c,
  first,
  onSelect,
}: {
  c: MarketSignalCard;
  first: boolean;
  onSelect?: (cat: PriceCatKey, sel: PriceSel) => void;
}) {
  const go = c.sel && onSelect
    ? () => {
        const s = c.sel!;
        onSelect(
          s.cat,
          s.kind === "leaf"
            ? { kind: "leaf", key: s.key }
            : { kind: "group", l1: s.l1, l2: s.l2, label: s.label },
        );
      }
    : undefined;

  return (
    // 첫 카드가 주인공이라 세로를 더 먹는다(flex-[1.4]) — 나머지는 맥락이다.
    // ★div 를 button 으로 바꾸지 않았다 — 안에 뉴스 <a> 가 들어 있어 버튼 중첩이 된다.
    //   role/tabIndex 로 키보드 접근만 살린다.
    <div
      onClick={go}
      role={go ? "button" : undefined}
      tabIndex={go ? 0 : undefined}
      onKeyDown={go ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } } : undefined}
      title={go ? "누르면 가운데 차트가 이 자산으로 이동합니다" : undefined}
      className={cn("flex flex-col justify-center px-2.5 py-2", first ? "flex-[1.4]" : "flex-1",
        go && "cursor-pointer transition-colors hover:bg-ge-blue-bg/60")}>
      <div className="flex flex-wrap items-center gap-1">
        <span
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[12.5px] font-extrabold ring-1",
            AC_TONE[c.asset_class] ?? "bg-slate-50 text-slate-700 ring-slate-200",
          )}
        >
          {c.asset_label}
        </span>
        <span className="text-[13px] font-semibold text-ink-muted">에서 시그널이 감지</span>
        {c.repeat ? (
          <span
            className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-bold text-slate-500"
            title="전일에도 떴던 시그널 — 지우지 않고 순위만 내린다(추세는 며칠 이어지는 게 정상)"
          >
            연속
          </span>
        ) : null}
        {c.news_supported ? (
          <span
            className="ml-auto shrink-0 rounded bg-emerald-600 px-1.5 py-0.5 text-[10.5px] font-bold text-white"
            title={`뉴스 근거 점수 ${c.news_score ?? 0}`}
          >
            근거확보
          </span>
        ) : (
          <span className="ml-auto shrink-0 text-[10.5px] font-semibold text-slate-400">
            근거 대기
          </span>
        )}
      </div>

      {/* ★★본문 3줄 — 수치 중심(사용자 지정 2026-09-01):
              [시그널 시기]
              [자산군] [하위분류] [무엇] [수치][단위] [동사]
              - (추가 간단설명)
          문구 조립은 **collector 가 한다**(pipeline._phrase) — 숫자·단위·기간을 화면에서
          다시 만들면 카드 문구와 시그널 계산이 두 곳에서 따로 정의된다. */}
      <div className="mt-1 text-[11.5px] font-semibold tabular-nums text-ink-muted">
        {c.period}
      </div>
      <div
        className={cn(
          "font-extrabold leading-snug text-ink",
          first ? "text-[18px]" : "text-[15px]",
        )}
      >
        {c.line}
      </div>
      {c.line_sub ? (
        <div className="mt-0.5 text-[11.5px] leading-snug text-ink-muted">
          - {c.line_sub}
        </div>
      ) : null}

      {/* 첫 카드만 뉴스 제목 1건 — 근거가 실제로 뭔지 보여준다. */}
      {first && c.articles?.[0] ? (
        <a
          href={c.articles[0].link}
          target="_blank"
          rel="noreferrer noopener"
          onClick={(e) => e.stopPropagation()}   // 뉴스 링크가 카드 클릭을 겸하지 않게
          className="mt-1 line-clamp-2 text-[11px] leading-tight text-ge-point underline-offset-2 hover:underline"
          title={c.articles[0].title}
        >
          {c.articles[0].title}
        </a>
      ) : null}
    </div>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-3 text-center">
      <span className={cn("text-[12.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
