"use client";

// [뉴스 모니터링 · 텔레그램] 카드 피드.
// 카드 내용과 '언급 n건'은 상류(S: Telegram_Bot)가 일간 HTML 리포트와 **같은 방식**
// 으로 구운 집계 JSON 에서 온다 — Opus 가 24h 토픽을 의미 단위로 묶고, 열마다
// 상위 3 + 단독·특이 2 = 5장이라 5×3 격자가 딱 찬다. 풀링은 08:00·13:00 KST.
//
// 레이아웃(2026-08-12 사용자 지시): 카드가 메인 영역을 꽉 채운다. Topbar 아래 높이를
// 통째로 격자에 주고(h-[calc(100vh-4rem)]) margin·border 는 최소로 — 바깥 래퍼
// 테두리·그림자를 없애고 카드 좌측 강조선만 남겼다.

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import {
  getTelegramNews,
  type TelegramNewsCard,
  type TelegramNewsSection,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { ApiErrorBanner } from "@/components/states";
import { cn } from "@/lib/utils";

const POLL_MS = 30_000;
// 카드 퇴장 애니메이션 길이. CSS 의 .tgn-out 과 같은 값이어야 한다.
const EXIT_MS = 420;
const TICK_MS = 30_000;

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function agoLabel(iso: string, now: number) {
  if (!iso) return "-";
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}시간 ${min % 60}분 전`;
  return `${Math.floor(h / 24)}일 ${h % 24}시간 전`;
}

function clockLabel(iso: string) {
  if (!iso) return "-";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 다음 풀링 시각 — "13:00" 목록에서 지금 이후 가장 가까운 것. */
function nextPool(poolTimes: string[], now: number) {
  const d = new Date(now);
  const mins = d.getHours() * 60 + d.getMinutes();
  const slots = poolTimes.map((t) => {
    const [h, m] = t.split(":").map(Number);
    return { t, v: h * 60 + m };
  });
  return (slots.find((s) => s.v > mins) ?? slots[0])?.t ?? "-";
}

type SlotState = "in" | "live" | "out";
type Slot = { card: TelegramNewsCard; state: SlotState };

/**
 * 서버가 준 목록을 '등장/유지/퇴장' 슬롯으로 바꾼다. 풀링에서 빠진 카드는 원래
 * 자리에 out 상태로 남겼다가 EXIT_MS 뒤에 제거한다 — 툭 사라지지 않고 밀려나는
 * 게 보이도록. 카드 id 는 제목 해시라 제목이 그대로면 같은 카드로 남는다.
 */
function useAnimatedSlots(items: TelegramNewsCard[]): Slot[] {
  const [slots, setSlots] = useState<Slot[]>(() =>
    items.map((card) => ({ card, state: "live" as SlotState })),
  );
  const seen = useRef(new Set(items.map((c) => c.id)));

  useEffect(() => {
    setSlots((prev) => {
      const nextIds = new Set(items.map((c) => c.id));
      const merged: Slot[] = items.map((card) => ({
        card,
        state: seen.current.has(card.id) ? "live" : "in",
      }));
      prev.forEach((s, i) => {
        if (s.state !== "out" && !nextIds.has(s.card.id)) {
          merged.splice(Math.min(i, merged.length), 0, { card: s.card, state: "out" });
        }
      });
      seen.current = nextIds;
      return merged;
    });
  }, [items]);

  useEffect(() => {
    if (!slots.some((s) => s.state === "out")) return;
    const id = setTimeout(
      () => setSlots((prev) => prev.filter((s) => s.state !== "out")),
      EXIT_MS + 40,
    );
    return () => clearTimeout(id);
  }, [slots]);

  return slots;
}

function Card({ slot }: { slot: Slot }) {
  const { card, state } = slot;
  return (
    <article
      className={cn(
        // 테두리는 좌측 강조선 하나만 — 리포트의 .issue 정체성이 이 선이다.
        // 단독·특이는 리포트와 같은 앰버로 구분한다.
        "flex min-h-0 flex-1 flex-col justify-center border-l-[5px] px-3 py-2",
        card.notable
          ? "border-l-[#d08a2e] bg-[#fffcf5]"
          : "border-l-ge-point bg-white",
        state === "in" && "tgn-in",
        state === "out" && "tgn-out",
      )}
    >
      <div className="flex items-start gap-2">
        <b className="line-clamp-3 flex-1 text-[15px] font-extrabold leading-snug tracking-tight text-ge-navy">
          {card.title}
        </b>
        {card.mentions != null && (
          <span
            className={cn(
              "shrink-0 px-1.5 py-[1px] text-[11.5px] font-extrabold tabular-nums",
              card.notable
                ? "bg-[#f7ead2] text-[#a96a16]"
                : "bg-ge-blue-bg text-ge-point",
            )}
          >
            {card.mentions}건
          </span>
        )}
      </div>

      {card.chips.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {card.chips.map((chip, i) => (
            <span
              key={`${chip}-${i}`}
              className={cn(
                "px-1.5 text-[11.5px] font-bold tabular-nums",
                card.notable
                  ? "bg-[#f7ead2] text-[#8a5a1b]"
                  : "bg-ge-blue-bg text-[#2f5a86]",
              )}
            >
              {chip}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

function Column({ section }: { section: TelegramNewsSection }) {
  const slots = useAnimatedSlots(section.cards);
  const blanks = Math.max(0, 5 - slots.length);
  return (
    <div className="flex min-h-0 min-w-0 flex-col">
      <div className="mb-1 flex items-center gap-2 border-b-2 border-ge-point pb-1">
        <span className="text-[17px] leading-none">{section.icon}</span>
        <span className="text-[18px] font-extrabold tracking-tight text-ge-navy">
          {section.label}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1">
        {slots.map((slot) => (
          <Card key={slot.card.id + (slot.state === "out" ? ":out" : "")} slot={slot} />
        ))}
        {Array.from({ length: blanks }, (_, i) => (
          <div
            key={`blank-${i}`}
            className="flex min-h-0 flex-1 items-center justify-center bg-white/60 text-[12px] text-ink-faint"
          >
            대기
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TelegramNewsPage() {
  const now = useNow(TICK_MS);
  const query = useQuery({
    queryKey: ["telegram-news"],
    queryFn: getTelegramNews,
    refetchInterval: POLL_MS,
  });
  const data = query.data;

  // 풀링이 하루 12슬롯(2시간 간격)이라 시각을 다 나열하면 머리글을 넘긴다 →
  // 간격이 일정하면 "2시간 간격"으로 접고, 아니면 그대로 나열한다.
  const pools = useMemo(() => {
    const ts = data?.poolTimes ?? [];
    if (ts.length < 3) return ts.join(" · ");
    const mins = ts.map((t) => {
      const [h, m] = t.split(":").map(Number);
      return h * 60 + m;
    });
    const step = mins[1] - mins[0];
    const even = mins.every((v, i) => i === 0 || v - mins[i - 1] === step);
    return even && step % 60 === 0 ? `${step / 60}시간 간격` : ts.join(" · ");
  }, [data?.poolTimes]);
  const empty = data != null && data.categories.every((s) => s.cards.length === 0);

  return (
    <>
      <style>{`
@keyframes tgnIn{from{opacity:0;transform:translateY(-12px) scale(.97)}to{opacity:1;transform:none}}
@keyframes tgnOut{from{opacity:1;transform:none;max-height:240px}to{opacity:0;transform:translateY(10px) scale(.96);max-height:0}}
.tgn-in{animation:tgnIn .42s cubic-bezier(.2,.8,.3,1)}
.tgn-out{animation:tgnOut ${EXIT_MS}ms ease-in forwards;overflow:hidden;pointer-events:none}
      `}</style>

      <Topbar
        title="텔레그램"
        subtitle="뉴스 모니터링 · 증권가 텔레그램 집계 카드"
        status={
          data ? (
            <span className="bg-ge-blue-bg px-2 py-[3px] text-[11.5px] font-bold tabular-nums text-ge-point">
              {data.rooms}개 방 · 토픽 {data.topics}건 / 최근 {data.windowHours}시간
            </span>
          ) : null
        }
        actions={
          <button
            type="button"
            onClick={() => query.refetch()}
            className="flex items-center gap-1.5 px-2 py-1.5 text-[12px] font-bold text-ink-secondary hover:bg-ge-blue-bg"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} />
            갱신
          </button>
        }
      />

      {/* Topbar(h-16) 아래를 통째로 쓴다 — 페이지 자체는 스크롤되지 않는다. */}
      <div className="flex h-[calc(100vh-4rem)] flex-col bg-canvas-soft">
        {query.isError && <ApiErrorBanner error={query.error} />}

        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 bg-ge-main px-4 py-1.5">
          <div className="flex items-baseline gap-2.5">
            <span className="text-[19px] font-extrabold tracking-tight text-white">
              텔레그램 뉴스 카드
            </span>
            <span className="text-[12.5px] font-semibold text-white/90">
              <b className="mr-1.5 bg-white/20 px-1.5 py-[1px]">매크로 · 산업 · 종목</b>
              일간 리포트와 같은 산정 · 분류별 다빈도 3 + 단독·특이 2
            </span>
          </div>
          <div className="text-right text-[11.5px] font-semibold text-white/90">
            <span className="tabular-nums">
              집계 {clockLabel(data?.generatedAt ?? "")}
              {data?.generatedAt && ` (${agoLabel(data.generatedAt, now)})`}
            </span>
            <span className="ml-2 tabular-nums text-white/75">
              풀링 {pools || "-"} · 다음 {data ? nextPool(data.poolTimes, now) : "-"}
            </span>
          </div>
        </div>

        {/* 풀링은 하루 2회뿐이라 한 번 빠지면 반나절 옛 집계를 보게 된다.
            예정 시각을 유예(90분) 넘겨 지났는데 파일이 그보다 앞서면 알린다. */}
        {data?.stale && data.available && (
          <div className="flex shrink-0 items-center gap-2 bg-[#fffcf5] px-4 py-1 text-[12px] font-semibold text-[#8a5a1b]">
            <AlertTriangle className="h-3.5 w-3.5" />
            {clockLabel(data.expectedAt)} 풀링이 반영되지 않았습니다 — 지금 카드는{" "}
            {clockLabel(data.generatedAt)} 집계({agoLabel(data.generatedAt, now)})입니다.
            상류 수집기(collect.py --watch)가 켜져 있는지 확인해 주세요.
          </div>
        )}

        {data && !data.available && (
          <div className="flex shrink-0 items-center gap-2 bg-[#fffcf5] px-4 py-1 text-[12px] font-semibold text-[#8a5a1b]">
            <AlertTriangle className="h-3.5 w-3.5" />
            집계 파일이 아직 없습니다 ({data.analysisPath}) — 상류에서 08:00 · 13:00 풀링이
            한 번 돌면 채워집니다.
          </div>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 p-2 lg:grid-cols-3">
          {(data?.categories ?? []).map((section) => (
            <Column key={section.key} section={section} />
          ))}
          {!data && (
            <div className="col-span-full flex items-center justify-center text-[13px] text-ink-muted">
              {query.isLoading ? "카드를 불러오는 중…" : "표시할 카드가 없습니다."}
            </div>
          )}
          {empty && (
            <div className="col-span-full flex items-center justify-center text-[13px] text-ink-muted">
              집계 결과가 비어 있습니다.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
