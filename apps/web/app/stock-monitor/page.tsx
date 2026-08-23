"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getIndexStrip,
  getStockMonitor,
  type IndexStripItem,
  type StockMonitorRow,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { cn } from "@/lib/utils";

// [종목 모니터] — KOSPI200 분봉 급등락·이상현상. 시장 모니터링 하위(iNAV·WRAP·LP평가와 동급).
//
// 화면 규격(사용자 확정 2026-08-21): 대시보드를 가로3×세로2로 6등분했을 때 **왼쪽 위 +
// 가운데 위** 2칸. 그래서 grid 는 3열 2행이고 이 표가 `col-span-2`(상단 좌·중)를 먹는다.
// 나머지 4칸은 아직 비어 있다 — 다음 카드가 들어올 자리다.
//
// 컬럼은 토스 '실시간 차트'(docs/toss 실시간.png)를 따른다. 다만
//   · `토스증권 거래 비율` 은 토스 앱 내부값이라 뺐다(사용자 확정).
//   · `시가총액`·`산업`·`실시간 이슈`(구 토스 AI 요약)는 원천이 없어 **자리만** 둔다.
//     빈 칸으로 두는 편이 나중에 소스가 붙을 때 화면을 안 건드린다.
// ★거래대금은 분봉 Σ(volume×close)다. 토스는 자기 앱 체결분만 세므로 같은 이름이지만
//   값이 다르다 — 서버가 value_basis 로 그 사실을 실어 보내고 화면은 그걸 그대로 적는다.

const EMDASH = "−";
const POLL_MS = 30_000; // 장중 분봉이 1분마다 갱신된다. LP평가와 같은 주기.

type SortKey = "value" | "change" | "sigma";

const SORTS: { key: SortKey; label: string; hint: string }[] = [
  { key: "value", label: "거래대금", hint: "토스 화면과 같은 정렬" },
  { key: "change", label: "등락률", hint: "당일 등락 큰 순" },
  { key: "sigma", label: "이상탐지", hint: "그 종목 자신의 변동성 대비 몇 σ인가" },
];

function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return Math.round(v).toLocaleString("en-US");
}

// 억/조 단위 — 토스 화면 표기(225억원 · 1,749.4조원)를 따른다.
function fmtWon(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  if (v >= 1e12) return `${(v / 1e12).toLocaleString("en-US", { maximumFractionDigits: 1 })}조원`;
  if (v >= 1e8) return `${Math.round(v / 1e8).toLocaleString("en-US")}억원`;
  return `${Math.round(v).toLocaleString("en-US")}원`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function fmtSigma(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return EMDASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}σ`;
}

// 등락 색 — 한국 관례(상승 빨강 / 하락 파랑). 토스 화면과 같다.
function moveColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

// σ 강조 — |σ|≥2 는 그 종목 기준 드문 움직임이다. 고정 임계값(±5%)으로는 못 가르는 자리.
function sigmaTone(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-ink-muted";
  const a = Math.abs(v);
  if (a >= 3) return "font-extrabold text-rose-700";
  if (a >= 2) return "font-bold text-amber-600";
  return "text-ink-muted";
}

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
  const [sort, setSort] = useState<SortKey>("value");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["stock-monitor", sort],
    queryFn: () => getStockMonitor(sort, 30),
    refetchInterval: POLL_MS,
  });

  const rows: StockMonitorRow[] = data?.rows ?? [];

  // 지수 스트립 — 분봉 표와 별개 폴링(원천 DB 도 다르다: INDEX_MONITOR.db).
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
        subtitle="시장 모니터링 · KOSPI200 분봉 급등락 / 이상현상"
        status={
          data?.asof ? (
            <span className="truncate text-[11px] tabular-nums text-slate-400">
              {data.asof} 기준 · 유니버스 {data.universe ?? EMDASH}종목 · 30초 폴링
            </span>
          ) : undefined
        }
        actions={
          <div className="flex overflow-hidden rounded-lg border border-hairline text-[12px] font-bold">
            {SORTS.map((s) => (
              <button
                key={s.key}
                title={s.hint}
                onClick={() => setSort(s.key)}
                className={cn(
                  "px-2.5 py-1 transition-colors",
                  sort === s.key
                    ? "bg-ge-navy text-white"
                    : "bg-canvas text-ink-muted hover:bg-canvas-soft",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        }
      />

      {/* ★PageContainer 를 쓰지 않는다. 기본형은 `mx-auto max-w-5xl px-8 py-10` 이라
          표가 가운데로 밀리고, wide 형도 `px-6 py-6` 라 왼쪽·위에 여백이 남는다.
          이 화면은 표 모서리가 사이드바·톱바 모서리에 딱 붙어야 한다(사용자 확정
          2026-08-21). 그래서 왼쪽·위 여백을 0 으로 두고 오른쪽·아래만 숨통을 준다.
          ⚠️공용 PageContainer 는 건드리지 않는다 — inav·wrap·lp-eval 등 10개 화면이
            같이 쓴다. 한 화면 때문에 전부를 밀면 안 된다. */}
      {/* 지수 스트립 — 톱바 바로 아래, 표 위. 높이는 내용만큼만 먹고(shrink-0)
          나머지를 아래 그리드가 가져간다. 6등분 계산에서 제외되는 띠다. */}
      <div className="shrink-0 border-b border-hairline bg-surface">
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

      <div className="min-h-0 flex-1 pb-6 pr-6">
        {/* 가로3 × 세로2 = 6등분. 이 표가 상단 좌·중 2칸을 차지한다.
            h-full 이라야 두 행이 각각 절반을 갖는다 — 없으면 내용 높이로 커진다. */}
        <div className="grid h-full grid-cols-1 gap-4 lg:grid-cols-3 lg:grid-rows-2">
          <section className="lg:col-span-2 lg:row-span-1 flex min-h-0 flex-col rounded-xl border border-hairline bg-surface">
            <header className="flex items-baseline gap-2 border-b border-hairline px-4 py-2.5">
              <h2 className="text-[13px] font-extrabold text-ink">실시간 차트</h2>
              <span className="text-[11px] text-ink-muted">
                {SORTS.find((s) => s.key === sort)?.hint}
              </span>
              {data?.value_basis ? (
                <span
                  title={data.value_basis}
                  className="ml-auto shrink-0 cursor-help text-[10px] text-slate-400"
                >
                  거래대금 정의 ⓘ
                </span>
              ) : null}
            </header>

            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full border-collapse text-[12px]">
                <thead className="sticky top-0 z-10 bg-canvas-soft">
                  <tr className="text-[11px] font-semibold text-ink-muted">
                    <th className="px-2 py-1.5 text-left">순위</th>
                    <th className="px-2 py-1.5 text-left">종목</th>
                    <th className="px-2 py-1.5 text-right">현재가</th>
                    <th className="px-2 py-1.5 text-right">등락률</th>
                    <th className="px-2 py-1.5 text-right">거래대금</th>
                    <th className="px-2 py-1.5 text-right">시가총액</th>
                    <th className="px-2 py-1.5 text-left">산업</th>
                    <th className="px-2 py-1.5 text-left">실시간 이슈</th>
                    {/* 이상탐지 재료 — 토스 화면에는 없다. 이 탭의 존재 이유다. */}
                    <th className="px-2 py-1.5 text-right" title="등락률 ÷ 그 종목의 일간 σ">
                      등락 σ
                    </th>
                    <th className="px-2 py-1.5 text-right" title="(당일 누적거래량 − 평균) ÷ 표준편차">
                      거래량 z
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    <tr>
                      <td colSpan={10} className="px-3 py-8 text-center text-ink-muted">
                        불러오는 중…
                      </td>
                    </tr>
                  ) : isError ? (
                    <tr>
                      <td colSpan={10} className="px-3 py-8 text-center text-rose-600">
                        collector 에 못 닿았습니다.
                      </td>
                    </tr>
                  ) : rows.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="px-3 py-8 text-center text-ink-muted">
                        {data?.note ?? "표시할 종목이 없습니다."}
                      </td>
                    </tr>
                  ) : (
                    rows.map((r) => (
                      <tr
                        key={r.symbol}
                        className="border-t border-hairline/60 hover:bg-canvas-soft"
                      >
                        <td className="px-2 py-1.5 tabular-nums text-ink-muted">{r.rank}</td>
                        <td className="px-2 py-1.5">
                          <span className="font-semibold text-ink">{r.name}</span>
                          <span className="ml-1.5 text-[10px] tabular-nums text-slate-400">
                            {r.symbol}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-ink">
                          {fmtInt(r.price)}원
                        </td>
                        <td
                          className={cn(
                            "px-2 py-1.5 text-right font-semibold tabular-nums",
                            moveColor(r.change_pct),
                          )}
                        >
                          {fmtPct(r.change_pct)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-ink">
                          {fmtWon(r.value)}
                        </td>
                        {/* 원천 없음 — 자리만 둔다 */}
                        <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                          {fmtWon(r.market_cap)}
                        </td>
                        <td className="px-2 py-1.5 text-slate-300">{r.industry ?? EMDASH}</td>
                        <td className="px-2 py-1.5 text-slate-300">{r.issue ?? EMDASH}</td>
                        <td
                          className={cn(
                            "px-2 py-1.5 text-right tabular-nums",
                            sigmaTone(r.change_sigma),
                          )}
                        >
                          {fmtSigma(r.change_sigma)}
                        </td>
                        <td
                          className={cn(
                            "px-2 py-1.5 text-right tabular-nums",
                            sigmaTone(r.volume_z),
                          )}
                        >
                          {fmtSigma(r.volume_z)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* 섹터별 등락률 — 우상단 1칸. 아직 placeholder 다.
              ★막아 둔 이유: 섹터 분류 기준(밸류체인 L1/L2? GICS? KRX 업종?)이 안 정해졌고
                종목→섹터 매핑도 없다. 기준을 먼저 정하지 않고 아무 분류나 붙이면 숫자가
                그럴듯해 보여서 틀린 것을 못 알아본다 — 빈 채로 두는 편이 안전하다.
              universe 199종목은 이미 손에 있으므로, 매핑만 생기면 이 자리에서 집계한다. */}
          <section className="flex min-h-0 flex-col rounded-xl border border-dashed border-hairline bg-canvas-soft/40">
            <header className="flex items-baseline gap-2 border-b border-hairline px-4 py-2.5">
              <h2 className="text-[13px] font-extrabold text-ink-muted">섹터별 등락률</h2>
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                준비 중
              </span>
            </header>
            <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
              <div className="text-[11px] leading-relaxed text-ink-muted">
                섹터 분류 기준과 종목 매핑이 정해지면 채웁니다.
                <br />
                <span className="text-slate-400">
                  후보 — 밸류체인 L1/L2 · KRX 업종 · GICS
                </span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
