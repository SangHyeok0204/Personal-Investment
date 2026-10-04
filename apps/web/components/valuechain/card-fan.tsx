"use client";

import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { VcCategory, VcCompany } from "@/lib/api-valuechain";
import { cn } from "@/lib/utils";
import { CompanyCard } from "./company-card";

// 카드 부채(손에 쥔 트럼프처럼 겹쳐 펼친 카드) — 2026-09-28 사용자 요청(참고 이미지: 두 줄 아치로 펼친 카드 덱).
// ★`Fan` = 배치만 하는 틀(카드 내용은 renderCard). 기업 카드(CardFan)와 허브의 L1 카드(sector-hub.tsx)가 같이 쓴다.
// ★아치 한 줄 = 한 번에 펼칠 수 있는 만큼. 많으면 아치를 여러 줄로 겹쳐 쌓는다(이미지처럼 아래 줄이 위 줄 아랫부분을 덮는다).
// ★hover/포커스 시 **안쪽 카드만** 들린다 — 위치·회전을 가진 바깥 슬롯은 제자리라, 들린 카드 밑으로 포인터가 빠져
//   내려앉았다 다시 들리는 떨림이 없다. 슬롯은 hover 동안 맨 앞(z)으로 올라온다. `active` 카드는 계속 들려 있다.
// ⚠️배치는 폭을 재서 JS 로 계산한다(ResizeObserver). CSS 만으로는 "한 줄에 몇 장·간격·기울기"를 폭에 맞춰 못 정한다.

const MAX_PER_ROW = 16;
const ROW_OFFSET = 0.6; // 다음 아치가 시작하는 높이(카드 높이 비율) — 아랫줄이 윗줄 아래 40% 를 덮는다
const EDGE_DROP = 20; // 아치 양 끝이 가운데보다 내려가는 px
const MAX_SPREAD_DEG = 16; // 한 줄 전체 회전 폭(양 끝 ±8°)
const SIDE_PAD = 30; // 양 끝 카드가 회전하며 바깥으로 삐져나오는 만큼(≈ sin 8° × 카드 높이)
const PAD_TOP = 26; // 들린 카드가 잘리지 않게 위 여백

type Slot = { x: number; y: number; rot: number; z: number };

interface FanGeometry {
  cardW: number;
  cardH: number;
  /** 겹쳤을 때 보이는 최소 폭. */
  minStep: number;
  /** 적을 때 너무 벌어지지 않게. */
  maxStep: number;
}

function layout(n: number, width: number, g: FanGeometry) {
  const { cardW, cardH, minStep, maxStep } = g;
  // 좁으면 회전 여백을 줄인다 — 카드가 컨테이너 밖으로 나가 페이지 가로 스크롤을 만들지 않게.
  const pad = Math.max(0, Math.min(SIDE_PAD, (width - cardW) / 2));
  const usable = Math.max(cardW, width - pad * 2);
  const fit = Math.max(1, Math.floor((usable - cardW) / minStep) + 1);
  const perRowMax = Math.min(MAX_PER_ROW, fit, Math.max(1, n));
  const rows = Math.max(1, Math.ceil(n / perRowMax));
  // 줄마다 장수를 고르게 — 마지막 줄만 한두 장 남는 모양을 피한다.
  const base = Math.floor(n / rows);
  const extra = n % rows;
  const slots: Slot[] = [];
  let top = PAD_TOP;
  for (let r = 0; r < rows; r++) {
    const m = base + (r < extra ? 1 : 0);
    const step = m > 1 ? Math.min(maxStep, (usable - cardW) / (m - 1)) : 0;
    const rowW = cardW + step * (m - 1);
    const x0 = pad + (usable - rowW) / 2;
    const half = (m - 1) / 2;
    const dDeg = m > 1 ? Math.min(2.2, MAX_SPREAD_DEG / (m - 1)) : 0;
    for (let i = 0; i < m; i++) {
      const t = half > 0 ? (i - half) / half : 0; // -1 … 1
      slots.push({
        x: x0 + step * i,
        y: top + EDGE_DROP * t * t,
        rot: (i - half) * dDeg,
        z: r * 100 + i + 1,
      });
    }
    top += cardH * ROW_OFFSET;
  }
  const height = top - cardH * ROW_OFFSET + cardH + EDGE_DROP + 12;
  return { slots, height };
}

export function Fan({
  keys,
  cardW: wantW,
  cardH,
  minStep,
  maxStep,
  active,
  renderCard,
}: {
  keys: string[];
  cardW: number;
  cardH: number;
  minStep: number;
  maxStep: number;
  /** 들린 채로 맨 앞에 둘 카드(선택된 카드). */
  active?: string | null;
  renderCard: (key: string, index: number) => ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 좁은 화면(폰)에서는 카드 폭을 컨테이너에 맞춘다.
  const cardW = width > 0 && width < wantW + SIDE_PAD * 2 ? Math.max(150, width - 8) : wantW;
  const { slots, height } = useMemo(
    () => layout(keys.length, width, { cardW, cardH, minStep, maxStep }),
    [keys.length, width, cardW, cardH, minStep, maxStep],
  );

  // 양 끝 카드가 기울면 모서리가 오른쪽으로 2px 남짓 삐져 가로 스크롤이 생긴다 — 가로만 자른다
  // (clip 은 세로를 건드리지 않아 hover 로 들리는 카드는 그대로).
  return (
    <div ref={ref} className="relative w-full overflow-x-clip" style={{ height: width ? height : cardH + PAD_TOP }}>
      {width > 0 &&
        keys.map((key, i) => {
          const s = slots[i];
          const on = key === active;
          return (
            <div
              key={key}
              className={cn(
                "group/slot absolute left-0 top-0 origin-[50%_140%] focus-within:[z-index:9999] hover:[z-index:9999]",
                on ? "[z-index:9000]" : "[z-index:var(--z)]",
              )}
              style={
                {
                  width: cardW,
                  height: cardH,
                  transform: `translate(${s.x}px, ${s.y}px) rotate(${s.rot}deg)`,
                  "--z": s.z,
                } as React.CSSProperties
              }
            >
              <div
                className={cn(
                  "h-full w-full transition-transform duration-200 ease-out will-change-transform group-hover/slot:-translate-y-5 group-focus-within/slot:-translate-y-5 motion-reduce:transition-none",
                  on && "-translate-y-7",
                )}
              >
                {renderCard(key, i)}
              </div>
            </div>
          );
        })}
    </div>
  );
}

/** 기업 카드 부채 — 겹친 채로도 읽히도록 카드 왼쪽 "등"(색 띠)에 티커·이름을 세로로 둔다(company-card.tsx). */
export function CardFan({
  ids,
  companies,
  byCode,
}: {
  ids: string[];
  companies: Record<string, VcCompany>;
  byCode: Map<string, VcCategory>;
}) {
  // ⚠️scroll-margin 이 걸린 article(`vc-co-*`)은 그대로 — jumpTo 로 카드에 가는 경로가 유지된다.
  return (
    <Fan
      keys={ids}
      cardW={256}
      cardH={236}
      minStep={44 /* 카드 등(34px) + 여유 */}
      maxStep={150}
      renderCard={(id) => <CompanyCard id={id} co={companies[id]} byCode={byCode} fan />}
    />
  );
}
