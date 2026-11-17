"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCandles, type Candles } from "@/lib/api";
import { cn } from "@/lib/utils";

// 관심종목 봉차트 — 일봉 OHLCV, 휠·핀치 확대/축소, 끌어서 이동, 커서 위치 봉의 OHLCV.
//
// ★2026-10-20 사용자 요청: 행을 누르면 최근 N년 봉차트를 **메모리 덜 쓰게**.
//   · 그리기는 TradingView `lightweight-charts`(canvas, gzip ≈60KB). 다른 차트처럼 SVG 로
//     그리면 봉 하나에 요소가 둘씩 생겨 10년치(≈2,500봉)를 확대할 때마다 DOM 을 다시 그린다.
//   · 라이브러리는 **차트를 처음 열 때** `import()` 로 받는다 — 안 열면 번들 비용 0.
//   · 10년치를 한 번 받고, 기간 버튼은 보이는 구간만 바꾼다(다시 받지 않는다).
//   · 닫으면 `chart.remove()` — canvas·리스너를 남기지 않는다. 쿼리 캐시도 5분 뒤 버린다.
// ⚠️색은 가이드 §8: 상승 = bid(브라운 계열 레드), 하락 = ask(블루 계열). SVG 안처럼 raw hex.
// ⚠️TradingView 출처 로고(attributionLogo)는 끄지 않는다 — Apache 2.0 + 출처 표시 조건.

const UP = "#A33A2A";
const DOWN = "#3A6B96";
const GRID = "#F2F2F2";
const AXIS_TEXT = "#7F7F7F";

const RANGES: { label: string; months: number | null }[] = [
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "3Y", months: 36 },
  { label: "5Y", months: 60 },
  { label: "전체", months: null },
];

type Bar = { time: string; open: number; high: number; low: number; close: number; volume: number };

function monthsBefore(day: string, months: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - months);
  return d.toISOString().slice(0, 10);
}

function fmtPrice(v: number, currency: string): string {
  const body = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency === "KRW" ? `₩${body}` : `$${body}`;
}

function fmtVolume(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

function toBars(c: Candles): Bar[] {
  return c.time.map((time, i) => ({
    time,
    open: c.open[i],
    high: c.high[i],
    low: c.low[i],
    close: c.close[i],
    volume: c.volume[i],
  }));
}

export function CandleChart({ symbol, name }: { symbol: string; name?: string | null }) {
  const box = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // 차트 핸들 — 기간 버튼이 보이는 구간을 바꿀 때 쓴다(라이브러리 타입은 동적 import 라 느슨하게).
  const chartRef = useRef<{ timeScale: () => { setVisibleRange: (r: { from: string; to: string }) => void; fitContent: () => void } } | null>(null);
  const [range, setRange] = useState("1Y");
  // ⚠️차트는 라이브러리를 받은 뒤에 생긴다. 그 전에 누른 기간 버튼을 잃지 않게 최신 값을 ref 로 본다.
  const rangeRef = useRef(range);
  rangeRef.current = range;
  const [hover, setHover] = useState<Bar | null>(null);

  const candles = useQuery({
    queryKey: ["candles", symbol],
    queryFn: () => getCandles(symbol, 10),
    staleTime: 60 * 60_000, // 서버도 1시간 캐시 — 그 안에 다시 묻지 않는다
    gcTime: 5 * 60_000, // 닫고 5분 지나면 브라우저 메모리에서 버린다
    retry: false,
  });

  // 표 아래쪽 행을 누르면 차트가 스크롤 영역 밖에 펼쳐진다 — 열릴 때 보이는 곳으로 당긴다.
  useEffect(() => {
    wrap.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const bars = useMemo(() => (candles.data ? toBars(candles.data) : []), [candles.data]);
  const byTime = useMemo(() => new Map(bars.map((b) => [b.time, b])), [bars]);
  const currency = candles.data?.currency ?? "USD";

  const applyRange = (label: string) => {
    setRange(label);
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    const months = RANGES.find((r) => r.label === label)?.months ?? null;
    const last = bars[bars.length - 1].time;
    if (months == null) chart.timeScale().fitContent();
    else chart.timeScale().setVisibleRange({ from: monthsBefore(last, months), to: last });
  };

  useEffect(() => {
    if (!box.current || bars.length === 0) return;
    let disposed = false;
    let cleanup = () => {};

    void import("lightweight-charts").then((lw) => {
      if (disposed || !box.current) return;
      const chart = lw.createChart(box.current, {
        autoSize: true,
        layout: {
          background: { type: lw.ColorType.Solid, color: "#FFFFFF" },
          textColor: AXIS_TEXT,
          fontSize: 11,
          attributionLogo: true,
        },
        grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
        rightPriceScale: { borderColor: GRID },
        timeScale: { borderColor: GRID, rightOffset: 3 },
        crosshair: { mode: lw.CrosshairMode.Normal },
        localization: { locale: "ko-KR" },
      });
      const price = chart.addSeries(lw.CandlestickSeries, {
        upColor: UP,
        downColor: DOWN,
        borderUpColor: UP,
        borderDownColor: DOWN,
        wickUpColor: UP,
        wickDownColor: DOWN,
        priceLineVisible: false,
      });
      // 거래량은 아래 20% 에 따로(가격 축과 섞지 않는다).
      const volume = chart.addSeries(lw.HistogramSeries, {
        priceScaleId: "",
        priceFormat: { type: "volume" },
        lastValueVisible: false,
        priceLineVisible: false,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

      price.setData(bars.map(({ volume: _v, ...ohlc }) => ohlc));
      volume.setData(
        bars.map((b) => ({
          time: b.time,
          value: b.volume,
          color: b.close >= b.open ? `${UP}55` : `${DOWN}55`,
        })),
      );

      const onMove = (param: { time?: unknown }) => {
        setHover(typeof param.time === "string" ? byTime.get(param.time) ?? null : null);
      };
      chart.subscribeCrosshairMove(onMove);
      chartRef.current = chart as unknown as typeof chartRef.current;
      applyRange(rangeRef.current);

      cleanup = () => {
        chart.unsubscribeCrosshairMove(onMove);
        chart.remove();
        chartRef.current = null;
      };
    });

    return () => {
      disposed = true;
      cleanup();
    };
    // 기간(range)은 버튼이 직접 바꾼다 — 데이터가 바뀔 때만 차트를 새로 만든다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, byTime]);

  const shown = hover ?? bars[bars.length - 1] ?? null;
  const prev = shown ? bars[bars.findIndex((b) => b.time === shown.time) - 1] : undefined;
  const change = shown && prev ? shown.close / prev.close - 1 : null;

  return (
    <div ref={wrap} className="rounded-lg border border-hairline bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12px] font-bold text-ink">
          {name ?? symbol} <span className="text-[10px] text-ink-faint">{symbol} · 일봉</span>
        </p>
        <div className="flex items-center gap-1">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => applyRange(r.label)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
                range === r.label ? "bg-ge-point text-white" : "text-ink-muted hover:bg-canvas-soft",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* 커서 위치 봉(없으면 마지막 봉)의 OHLCV */}
      <p className="mb-1 min-h-[16px] text-[11px] font-semibold tabular-nums text-ink-muted">
        {shown && (
          <>
            <span className="text-ink">{shown.time}</span> · 시 {fmtPrice(shown.open, currency)} · 고{" "}
            {fmtPrice(shown.high, currency)} · 저 {fmtPrice(shown.low, currency)} · 종{" "}
            <b className={shown.close >= shown.open ? "text-bid" : "text-ask"}>
              {fmtPrice(shown.close, currency)}
            </b>
            {change != null && (
              <b className={change >= 0 ? "text-bid" : "text-ask"}>
                {" "}
                ({change >= 0 ? "+" : ""}
                {(change * 100).toFixed(2)}%)
              </b>
            )}{" "}
            · 거래량 {fmtVolume(shown.volume)}
          </>
        )}
      </p>

      {candles.isLoading && <p className="py-10 text-center text-[11px] text-ink-muted">불러오는 중…</p>}
      {candles.isError && (
        <p className="py-10 text-center text-[11px] font-bold text-ask">
          일봉을 받지 못했습니다 — 잠시 뒤 다시 열어 보세요.
        </p>
      )}
      <div ref={box} className={cn("h-[320px] w-full", bars.length === 0 && "hidden")} />
      <p className="mt-1 text-[10px] text-ink-faint">휠·두 손가락으로 확대/축소, 끌어서 이동 · 원천 야후(1시간 캐시)</p>
    </div>
  );
}
