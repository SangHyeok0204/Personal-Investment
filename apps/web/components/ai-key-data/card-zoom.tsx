"use client";

import { useCallback, useEffect, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { cn } from "@/lib/utils";

// [AI Key Data] 카드 확대 — 2026-08-31 사용자 지시.
//
// 카드 제목 띠 오른쪽 끝의 버튼을 누르면 그 카드가 **그리드 영역을 꽉 채운다**
// (`page.tsx` 의 `grid h-full ... lg:grid-rows-3` 가 차지하던 자리 = 톱바 아래 전부).
//
// ★구현이 오버레이가 아니라 **카드 자신을 fixed 로 띄우는** 방식인 이유:
//   오버레이에 카드를 다시 그리면 같은 컴포넌트가 두 번 마운트돼 차트가 재계산되고
//   ResizeObserver 가 두 번 붙는다. 자기 자리에서 커지면 인스턴스가 하나로 유지된다.
// ★부드럽게 보이게 하는 장치: static -> fixed 는 CSS 로 보간이 안 되므로(레이아웃 점프)
//   **2단계 렌더**로 만든다 — fixed 로 띄우자마자 `scale-[0.97] opacity-0` 이고,
//   다음 프레임에 `scale-100 opacity-100` 로 바뀌면서 transition 이 걸린다.
//   `requestAnimationFrame` 을 쓰는 이유는 같은 프레임에 두 상태를 넣으면 브라우저가
//   중간값 없이 최종 상태만 그려서 애니메이션이 안 보이기 때문이다.
// ★배경 막(backdrop)은 두지 않는다 — 확대된 카드가 그리드 영역을 이미 꽉 덮어서
//   뒤에 보일 게 없다. 막을 깔면 톱바까지 어두워져 오히려 어색하다.
//
// 확대 상태에서 ESC 로 닫힌다.
export function useCardZoom() {
  const [zoomed, setZoomed] = useState(false);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!zoomed) {
      setShown(false);
      return;
    }
    const id = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(id);
  }, [zoomed]);

  useEffect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoomed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomed]);

  const toggle = useCallback(() => setZoomed((v) => !v), []);

  // top-16 = 톱바 높이(h-16). 좌우·아래 1.5는 그리드가 카드 사이에 주는 간격과 같은 값.
  const zoomCls = zoomed
    ? cn(
        "fixed bottom-1.5 left-1.5 right-1.5 top-16 z-50 shadow-2xl",
        "transition-[transform,opacity] duration-300 ease-out motion-reduce:transition-none",
        shown ? "scale-100 opacity-100" : "scale-[0.97] opacity-0",
      )
    : "";

  return { zoomed, toggle, zoomCls };
}

export function ZoomButton({
  zoomed,
  onToggle,
}: {
  zoomed: boolean;
  onToggle: () => void;
}) {
  const Icon = zoomed ? Minimize2 : Maximize2;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={zoomed ? "카드 축소" : "카드 확대"}
      title={zoomed ? "축소 (ESC)" : "확대"}
      // shrink-0 이 없으면 제목이 길 때 버튼이 찌그러진다. ml-auto 는 붙이지 않는다 —
      // 카드마다 앞에 `ml-auto` 를 가진 asof 표시가 있어서 자연히 오른쪽 끝에 선다.
      className="shrink-0 rounded p-0.5 text-white/70 transition-colors hover:bg-white/20 hover:text-white"
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={2.4} />
    </button>
  );
}
