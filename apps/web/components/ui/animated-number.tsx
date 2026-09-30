"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// 값이 바뀌면 **기존 글자는 아래로 빠지고 새 글자가 위에서 내려오는** 숫자.
//
// ★2026-09-22 사용자 요청: "기존 숫자는 내려가고, 새로운 숫자는 위에서 내려오는
//   슬라이드 형태". 같은 움직임이 이미 iNAV 모니터에 `inav-roll-*` 로 있다.
//
// ⚠️이전 구현(0~9 띠를 translateY 로 밀어 올리는 오도미터)은 **실제로 애니메이션이
//   일어나지 않았다.** 자리 컴포넌트의 key 가 `${i}-${ch}` 라 글자가 바뀌는 순간
//   React 가 기존 노드를 버리고 새로 만들었고, transition 은 새 노드의 첫 렌더에는
//   걸리지 않는다. 그래서 숫자가 그냥 '툭' 바뀌었다.
//   → key 는 **자리(index)** 로만 잡는다. 글자는 그 자리 안에서 교체된다.
//
// ⚠️표시 문자열을 그대로 받는다(이미 포맷된 "₩37,108,766"). 여기서 숫자를 만들지
//   않는다 — 포맷 규칙이 두 곳에 생기면 화면마다 자릿수가 달라진다.
//
// ⚠️`prefers-reduced-motion` 이면 즉시 교체한다. 움직이는 숫자는 멀미를 유발할 수
//   있고, 그건 취향이 아니라 접근성 문제다.

// ★2026-09-25 사용자 요청: 0.75배속(420ms → 560ms). 5초 갱신 주기 안에 충분히 끝난다.
const DURATION_MS = 560;

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** 한 자리. 글자가 바뀌면 옛 글자는 아래로, 새 글자는 위에서 내려온다. */
function Slot({
  char,
  animate,
  lineHeight,
}: {
  char: string;
  animate: boolean;
  lineHeight: number;
}) {
  // `leaving` 이 있는 동안만 두 겹으로 그린다. 끝나면 새 글자 한 겹만 남는다.
  const [leaving, setLeaving] = useState<string | null>(null);
  const shown = useRef(char);

  useEffect(() => {
    if (shown.current === char) return;
    if (!animate) {
      shown.current = char;
      setLeaving(null);
      return;
    }
    setLeaving(shown.current);
    shown.current = char;
    const id = window.setTimeout(() => setLeaving(null), DURATION_MS);
    // 애니메이션 도중에 값이 또 바뀌면 타이머를 갈아끼운다(겹치지 않게).
    return () => window.clearTimeout(id);
  }, [char, animate]);

  return (
    <span
      className="relative inline-block overflow-hidden align-bottom"
      style={{ height: lineHeight, lineHeight: `${lineHeight}px` }}
      aria-hidden="true"
    >
      {/* 빠지는 글자 — 흐름에서 빼야 칸 너비가 흔들리지 않는다. */}
      {leaving != null && (
        <span
          key={`out-${leaving}`}
          className="number-roll-out absolute inset-x-0 top-0"
          style={{ animationDuration: `${DURATION_MS}ms` }}
        >
          {leaving}
        </span>
      )}
      {/* 들어오는 글자 — 칸 너비는 항상 이쪽이 정한다. */}
      <span
        key={`in-${char}-${leaving ?? ""}`}
        className={cn("inline-block", leaving != null && "number-roll-in")}
        style={leaving != null ? { animationDuration: `${DURATION_MS}ms` } : undefined}
      >
        {char}
      </span>
    </span>
  );
}

export function AnimatedNumber({
  value,
  className,
  /** 글자 높이(px). 이 높이만큼 잘라내므로 실제 폰트 크기와 맞아야 한다. */
  lineHeight = 28,
}: {
  value: string;
  className?: string;
  lineHeight?: number;
}) {
  const reduced = useReducedMotion();
  // 첫 렌더에는 굴리지 않는다 — 페이지를 열 때마다 전부 흘러내리면 산만하다.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setReady(true), 50);
    return () => window.clearTimeout(id);
  }, []);

  const animate = ready && !reduced;
  // ⚠️한 글자씩 inline-block 으로 나누면 **공백이 접혀 사라진다**("2/2 작동" → "2/2작동").
  //   줄바꿈 없는 공백으로 바꿔 그린다(스크린리더용 sr-only 는 원문 그대로).
  const chars = value.split("").map((ch) => (ch === " " ? "\u00A0" : ch));

  return (
    <span
      className={cn("inline-flex items-end tabular-nums", className)}
      style={{ lineHeight: `${lineHeight}px` }}
    >
      {/* 스크린리더는 흘러가는 글자 대신 값을 한 번에 읽는다. */}
      <span className="sr-only">{value}</span>
      {chars.map((ch, i) => (
        // ⚠️key 는 **자리**다. 글자를 key 에 넣으면 교체 때마다 노드가 새로 생겨
        //   애니메이션이 통째로 사라진다(이전 구현의 실패 원인).
        <Slot key={i} char={ch} animate={animate} lineHeight={lineHeight} />
      ))}
    </span>
  );
}
