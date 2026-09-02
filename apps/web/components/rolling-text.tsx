"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * 룰렛(슬롯) 숫자 롤: 값이 바뀌면 기존 텍스트가 아래로 빠지고 새 텍스트가
 * 위에서 내려온다. 숫자/짧은 라벨용 — 색상·크기는 부모 클래스에서 준다.
 * 연속 변경 시 현재 span 이 key 로 리마운트되어 애니메이션이 재시작된다.
 *
 * ★기본은 CSS 의 0.35s(iNAV·WRAP·전광판이 쓰는 값). `durationMs` 를 주면 그 화면에서만
 *   길이를 바꾼다 — 전역 CSS 를 고치면 이미 쓰고 있는 세 화면이 같이 느려진다.
 *   (국내상장 ETF 신규상장 성적표는 1.5초, 사용자 지시 2026-09-02.)
 */
const ROLL_MS = 350;

export function RollingText({
  text,
  className,
  durationMs,
}: {
  text: string;
  className?: string;
  durationMs?: number;
}) {
  const shownRef = useRef(text);
  const idRef = useRef(0);
  const [prev, setPrev] = useState<{ text: string; id: number } | null>(null);

  useEffect(() => {
    if (shownRef.current === text) return;
    const old = shownRef.current;
    shownRef.current = text;
    idRef.current += 1;
    setPrev({ text: old, id: idRef.current });
    // 정리 타이머는 애니메이션보다 조금 길게 — 먼저 지우면 끝나기 전에 사라진다.
    const timer = setTimeout(() => setPrev(null), (durationMs ?? ROLL_MS) + 40);
    return () => clearTimeout(timer);
  }, [text, durationMs]);

  // inline-flex: overflow-hidden 인 inline-block 은 baseline 이 박스 하단으로
  // 바뀌어 주변 텍스트보다 살짝 떠 보인다 — flex 컨테이너는 첫 아이템의
  // baseline 을 그대로 쓰므로 클리핑을 유지하면서 정렬이 맞는다.
  return (
    <span className={cn("relative inline-flex overflow-hidden", className)}>
      <span
        key={`cur-${idRef.current}`}
        className={cn("inline-block", prev && "inav-roll-in")}
        style={durationMs ? { animationDuration: `${durationMs}ms` } : undefined}
      >
        {text}
      </span>
      {prev && (
        <span
          key={`prev-${prev.id}`}
          aria-hidden
          className="inav-roll-out absolute inset-0"
          style={durationMs ? { animationDuration: `${durationMs}ms` } : undefined}
        >
          {prev.text}
        </span>
      )}
    </span>
  );
}
