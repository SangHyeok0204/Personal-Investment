"use client";

import { cn } from "@/lib/utils";

// [AI Key Data] 카드 제목 띠 위의 탭 칩.
//
// ★2026-08-28 사용자 지시로 이 페이지 카드의 제목 띠가 **전부** 강조색
//   (`ge-header` #483629, 다크 브라운)이 되면서 칩도 어두운 배경 위에서 읽히게
//   뒤집었다 — 활성은 흰 알약(글자를 띠 색으로), 비활성은 반투명 흰색.
// 네 군데(매크로·물가/유가·AI 사용량·Epoch)가 같은 모양을 쓰므로 한 곳에 둔다.
//
// 탭 상태를 카드가 아니라 **부모가 들 수도** 있다(page.tsx 의 두 묶음) — 서로
// 다른 컴포넌트를 한 칸에 갈아 끼우는 묶음이라 상태가 카드 밖에 있어야 한다.
export function TabChips<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string }[];
  value: T;
  onChange: (k: T) => void;
}) {
  return (
    <div className="flex shrink-0 gap-0.5">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={cn(
            "rounded px-1.5 py-0.5 text-[12px] font-bold transition-colors",
            value === t.key
              ? "bg-white text-ge-header"
              : "bg-white/15 text-white/75 hover:bg-white/30",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
