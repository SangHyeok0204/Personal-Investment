"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getIndexStrip, type IndexStripItem, type PriceCatKey } from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { EtfFlowCard } from "@/components/stock-monitor/etf-flow-card";
import { PriceTreeCard, type PriceSel } from "@/components/stock-monitor/price-tree-card";
import { PriceMetricChartCard } from "@/components/stock-monitor/price-metric-chart-card";
import { PriceSummaryCard } from "@/components/stock-monitor/price-summary-card";
import { EMDASH, moveColor } from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [종목 모니터] — 시장 모니터링 하위(iNAV·WRAP·LP평가와 동급).
//
// 화면 규격(사용자 지시 2026-08-28 전면 개편): 가로6×세로2 = 12등분.
//   · 1번째 칸 위·아래 2칸   = 지표 리스트 (자산군 탭 + layer1/layer2 계층 트리)
//   · 2~5번째 칸 위·아래 8칸 = 지표 추이 차트 (누적수익률 / 벤치마크 대비 / 롤링 3M)
//   · 상단 6번째 1칸         = ETF 순매수 모니터
//   · 아래 6번째 1칸         = 수익률 요약 표 (DtD~YtD + 롤링 1M·3M·6M·1Y)
//
// ★★2026-08-31 개편(사용자 지시): 달력 앵커 지표(DtD·WtD·MtD·YtD)의 **시계열을
//   차트에서 걷어내고 표로 옮겼다**. 그 지표들은 월초·연초마다 0 으로 리셋되는
//   톱니라 추세를 읽을 수 없고, 월초에는 모든 시장이 0 근처로 뭉쳐 비교도 안 된다.
//   그래서 화면의 역할을 갈랐다 — **발견은 표(정렬·틴트), 확인은 차트(궤적)**.
// ★2026-08-28 ETF 카드를 2칸→1칸으로 줄였다(사용자 지시). 그만큼 차트가 3칸→4칸으로
//   넓어진다 — 안 늘리면 5번째 열이 통째로 빈 구멍이 된다.
// 참조 화면: S:\GE\raw\data\주간가격모니터\reference\주간가격모니터.png
//
// ★★'실시간 급등락 종목' 카드는 2026-08-28 제거(사용자 지시). 그와 함께 미장 분봉
//   쿼리·표 팝업(StockTableModal)·이슈 헤드라인(RealtimeIssues)도 이 화면에서
//   빠졌다 — 컴포넌트와 collector lane(us_stock_monitor)은 남아 있으니 되살릴 땐
//   import 와 카드 한 장만 다시 놓으면 된다.
//
// ★가격 모니터 두 카드는 상태(자산군 탭 · 선택 지수)를 **페이지가 들고 있다** —
//   서로 다른 그리드 칸이라 형제로 놓인다. 목록은 자산군 payload 를, 차트는 고른
//   지수의 지표 시계열을 각각 받는다(선택할 때마다 한 시장씩).

const POLL_MS = 30_000; // 지수 스트립 — 장중 분단위로 갱신된다.

// 스파크라인 — 값 배열을 폭 100 높이 28 의 path 로 접는다. 차트 라이브러리를 쓰지 않는
// 이유는 이 화면에 5개가 동시에 뜨고 각각 60점뿐이라, SVG 한 줄이 더 싸고 빠르기 때문이다.
// ★색은 마지막-처음 부호로 정한다(등락률과 같은 방향). 상승 빨강 / 하락 파랑.
function Spark({ pts, up }: { pts: number[]; up: boolean }) {
  if (!pts || pts.length < 2) return <div className="h-7 w-[76px]" />;
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const span = hi - lo || 1;
  const d = pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * 100;
      const y = 26 - ((v - lo) / span) * 24; // 위아래 1px 여백
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = up ? "#e11d48" : "#2563eb";
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-7 w-[76px] shrink-0">
      <path d={d} fill="none" stroke={stroke} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function IndexCell({ x }: { x: IndexStripItem }) {
  const up = (x.change_pct ?? 0) > 0;
  return (
    <div className="flex min-w-0 items-center gap-2.5 px-3 py-2">
      <Spark pts={x.spark} up={up} />
      <div className="min-w-0">
        <div className="truncate text-[11px] font-semibold text-ink-muted">{x.name}</div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[13px] font-extrabold tabular-nums text-ink">
            {x.price == null ? EMDASH : x.price.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </span>
          <span className={cn("text-[11px] font-semibold tabular-nums", moveColor(x.change_pct))}>
            {x.change == null
              ? EMDASH
              : `${x.change > 0 ? "+" : ""}${x.change.toLocaleString("en-US", { maximumFractionDigits: 2 })}`}
            {x.change_pct == null ? "" : ` (${Math.abs(x.change_pct).toFixed(2)}%)`}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function StockMonitorPage() {
  // 가격 모니터 — 목록과 차트가 공유하는 상태. 탭을 바꾸면 선택을 비워
  // 그 자산군의 첫 지수로 떨어지게 한다.
  const [priceCat, setPriceCat] = useState<PriceCatKey>("equity");
  // 선택은 지수 하나(leaf) 또는 묶음(group) 둘 중 하나다 — 차트가 모드를 갈라 쓴다.
  const [priceSel, setPriceSel] = useState<PriceSel | null>(null);

  // 지수 스트립 — 원천이 CHECK 에이전트의 INDEX_MONITOR.db 다.
  const { data: strip } = useQuery({
    queryKey: ["index-strip"],
    queryFn: getIndexStrip,
    refetchInterval: POLL_MS,
  });
  const indices: IndexStripItem[] = strip?.indices ?? [];

  return (
    // ★화면 높이를 여기서 확정한다. 루트 레이아웃은 `min-h-screen`(내용만큼 늘어남)이라
    //   그대로 두면 grid-rows-2 가 내용 높이로 커져 6등분이 아니게 되고 페이지가 스크롤된다
    //   (실측: 행 1개 높이 1001px, 문서 2106px). 톱바 높이를 px 로 박지 않으려고
    //   flex 컬럼으로 잡는다 — 톱바는 제 높이만 먹고 나머지를 그리드가 가져간다.
    <div className="flex h-screen flex-col">
      <Topbar
        title="종목 모니터"
        subtitle="시장 모니터링 · 미장 실시간 체결 급등락 / 이상현상"
      />

      {/* ★PageContainer 를 쓰지 않는다. 기본형은 `mx-auto max-w-5xl px-8 py-10` 이라
          표가 가운데로 밀리고, wide 형도 `px-6 py-6` 라 왼쪽·위에 여백이 남는다.
          이 화면은 표 모서리가 사이드바·톱바 모서리에 딱 붙어야 한다(사용자 확정
          2026-08-21). 그래서 왼쪽·위 여백을 0 으로 두고 오른쪽·아래만 숨통을 준다.
          ⚠️공용 PageContainer 는 건드리지 않는다 — inav·wrap·lp-eval 등 10개 화면이
            같이 쓴다. 한 화면 때문에 전부를 밀면 안 된다. */}
      {/* 지수 스트립 — 톱바 바로 아래, 카드 위. 높이는 내용만큼만 먹고(shrink-0)
          나머지를 아래 그리드가 가져간다. 6등분 계산에서 제외되는 띠다. */}
      <div className="shrink-0 border-b border-hairline bg-canvas">
        <div className="flex divide-x divide-hairline overflow-x-auto">
          {indices.length === 0
            ? <div className="px-3 py-3 text-[11px] text-ink-muted">지수 불러오는 중…</div>
            : indices.map((x) => (
                <div key={x.code} className="min-w-[188px] flex-1">
                  <IndexCell x={x} />
                </div>
              ))}
        </div>
      </div>

      {/* ★2026-08-28 사용자 지시로 여백을 **완전히** 걷어냈다 — gap 도 0, 바깥 padding
          도 0. 카드끼리 맞붙어 화면을 꽉 채운다.
          ⚠️그래서 카드는 `rounded-xl border` 를 버리고 **오른쪽/아래 한 방향 테두리**만
            갖는다. 사방 테두리를 그대로 두면 맞닿은 자리마다 선이 2px 로 겹치고, 둥근
            모서리가 카드 사이에 흰 홈을 판다. */}
      <div className="min-h-0 flex-1">
        {/* 가로6 × 세로2 = 12등분. h-full 이라야 두 행이 각각 절반을 갖는다. */}
        <div className="grid h-full grid-cols-1 gap-0 lg:grid-cols-6 lg:grid-rows-2">
          {/* 가격 모니터 — 왼쪽 4칸(1칸 목록 + 3칸 차트)을 위아래 통으로 쓴다.
              참조 화면: S:\GE\raw\data\주간가격모니터\reference\주간가격모니터.png
              (왼쪽 지표 리스트 + 오른쪽 큰 차트 + 하단 클릭 가능한 범례) */}
          <PriceTreeCard
            cat={priceCat}
            onCat={(c) => {
              setPriceCat(c);
              setPriceSel(null); // 자산군이 바뀌면 선택을 비워 그 군의 첫 지수로 떨어뜨린다
            }}
            selected={priceSel}
            onSelect={setPriceSel}
          />
          <PriceMetricChartCard sel={priceSel} cat={priceCat} />

          {/* ETF 순매수 모니터 — 상단 6번째 1칸. 관심 ETF(주로 신규상장)의 개인 순매수.
              원천은 CHECK 에이전트가 적재하는 ETF_FLOW_MONITOR.db — 적재 전에는 카드가
              대기 문구를 띄운다. */}
          <EtfFlowCard />

          {/* 수익률 요약 표 — 아래 행 6번째 1칸('주목해야할 지수'가 있던 자리).
              차트에서 뺀 달력 앵커 지표(DtD~YtD)에 롤링 1M·3M·6M·1Y 를 더해 놓는다.
              ★쿼리 키가 PriceTreeCard 와 같아(["price-board", cat]) 요청은 한 번만
                나간다 — 이 카드는 네트워크를 더 쓰지 않는다.
              ⚠️price-return-card.tsx · price-board-card.tsx · price-chart-card.tsx 와
                collector price_returns.py 는 여전히 안 쓰인다(되살릴 때 배선만 이으면 된다). */}
          <PriceSummaryCard cat={priceCat} sel={priceSel} />
        </div>
      </div>
    </div>
  );
}
