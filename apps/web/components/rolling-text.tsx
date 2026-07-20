"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * 룰렛(슬롯) 숫자 롤: 값이 바뀌면 기존 텍스트가 아래로 빠지고 새 텍스트가
 * 위에서 내려온다. 숫자/짧은 라벨용 — 색상·크기는 부모 클래스에서 준다.
 * 연속 변경 시 현재 span 이 key 로 리마운트되어 애니메이션이 재시작된다.
 */
export function RollingText({
  text,
  className,
}: {
  text: string;
  className?: string;
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
    const timer = setTimeout(() => setPrev(null), 380);
    return () => clearTimeout(timer);
  }, [text]);

  // inline-flex: overflow-hidden 인 inline-block 은 baseline 이 박스 하단으로
  // 바뀌어 주변 텍스트보다 살짝 떠 보인다 — flex 컨테이너는 첫 아이템의
  // baseline 을 그대로 쓰므로 클리핑을 유지하면서 정렬이 맞는다.
  return (
    <span className={cn("relative inline-flex overflow-hidden", className)}>
      <span
        key={`cur-${idRef.current}`}
        className={cn("inline-block", prev && "inav-roll-in")}
      >
        {text}
      </span>
      {prev && (
        <span
          key={`prev-${prev.id}`}
          aria-hidden
          className="inav-roll-out absolute inset-0"
        >
          {prev.text}
        </span>
      )}
    </span>
  );
}
