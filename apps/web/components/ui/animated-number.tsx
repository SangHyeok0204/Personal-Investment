"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// 값이 바뀌면 자릿수가 **위로 굴러 올라가며** 갱신되는 숫자.
//
// ★2026-09-21 사용자 요청: "5초마다 뜨는 숫자를 scroll-up 되는 형태로".
//
// 구현 방식: 자리마다 0~9 를 세로로 쌓은 띠를 두고 translateY 로 해당 숫자까지
// 밀어 올린다. 숫자를 통째로 교체하면 값이 '깜빡'이는데, 그러면 어느 자리가
// 얼마나 변했는지 눈이 못 쫓는다. 자릿수가 굴러가면 변화의 크기가 보인다.
//
// ⚠️표시 문자열을 그대로 받는다(이미 포맷된 "₩37,108,766"). 여기서 숫자를 만들지
//   않는다 — 포맷 규칙이 두 곳에 생기면 화면마다 자릿수가 달라진다.
//
// ⚠️`prefers-reduced-motion` 이면 애니메이션을 끈다. 굴러가는 숫자는 멀미를
//   유발할 수 있고, 그건 취향이 아니라 접근성 문제다.

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

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

/** 한 자리 — 0~9 띠를 밀어 올린다. */
function Digit({
  value,
  animate,
  lineHeight,
}: {
  value: string;
  animate: boolean;
  lineHeight: number;
}) {
  const index = DIGITS.indexOf(value);
  return (
    <span
      className="inline-block overflow-hidden align-bottom"
      style={{ height: lineHeight }}
      aria-hidden="true"
    >
      <span
        className={cn(
          "flex flex-col",
          animate && "transition-transform duration-500 ease-out",
        )}
        style={{ transform: `translateY(-${index * lineHeight}px)` }}
      >
        {DIGITS.map((d) => (
          <span key={d} style={{ height: lineHeight, lineHeight: `${lineHeight}px` }}>
            {d}
          </span>
        ))}
      </span>
    </span>
  );
}

export function AnimatedNumber({
  value,
  className,
  /** 글자 높이(px). 자리 띠의 한 칸 높이와 같아야 잘리지 않는다. */
  lineHeight = 28,
}: {
  value: string;
  className?: string;
  lineHeight?: number;
}) {
  const reduced = useReducedMotion();
  const previous = useRef(value);
  // 첫 렌더에는 굴리지 않는다 — 페이지를 열 때마다 0 에서 올라오면 산만하다.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (previous.current !== value) previous.current = value;
    const id = window.setTimeout(() => setReady(true), 50);
    return () => window.clearTimeout(id);
  }, [value]);

  const animate = ready && !reduced;

  return (
    <span
      className={cn("inline-flex items-end tabular-nums", className)}
      style={{ lineHeight: `${lineHeight}px` }}
    >
      {/* 스크린리더는 굴러가는 띠 대신 값을 한 번에 읽는다. */}
      <span className="sr-only">{value}</span>
      {value.split("").map((ch, i) =>
        DIGITS.includes(ch) ? (
          <Digit key={`${i}-${ch}`} value={ch} animate={animate} lineHeight={lineHeight} />
        ) : (
          <span
            key={`${i}-${ch}`}
            aria-hidden="true"
            className="inline-block"
            style={{ height: lineHeight }}
          >
            {ch}
          </span>
        ),
      )}
    </span>
  );
}
