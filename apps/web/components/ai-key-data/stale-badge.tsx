"use client";

import { cn } from "@/lib/utils";
import type { AiKeyDataSource } from "@/lib/api";

// [AI Key Data] staleness 마커 — AI 사용량·Epoch 카드 공용. ws2 설계 §4.3 그대로.
// ★2026-08-28 재정정: 한때 `irrecoverable` 필드가 라이브에 안 보여 `fetch_ok` 로
//   우회했었는데, 이제 6개 엔드포인트 전부가 이 필드를 항상 명시적으로 싣는다
//   (vscode 만 true, 나머지는 false — curl 재확인). 원래 설계대로 되돌린다.
// stale_days<=1 이면 아무것도 안 띄운다(정상). stale_days>=2 && irrecoverable
// 이면 rose "N일 미수집 — 복구 불가"(VS Code 처럼 결측이 영구 손실인 소스 —
// "나중에 백필하면 되지"가 성립하지 않는다). 그 외 stale_days>=2 면 amber
// "N일 지연". 색 규약: rose=조치 필요 / amber=데이터 사유 / 무채색=정상.
// ★2026-08-28(2차) 톤만 300 대로 — 이 뱃지가 얹히는 제목 띠가 강조색(다크 브라운
//   `ge-header`)이 되면서 600 대는 대비가 죽어 경고가 경고로 안 읽힌다.
export function StaleBadge({ source }: { source: AiKeyDataSource | null | undefined }) {
  if (!source || source.stale_days <= 1) return null;
  const rose = source.irrecoverable === true;
  return (
    <span
      className={cn(
        "shrink-0 text-[12px] font-bold tabular-nums",
        rose ? "text-rose-300" : "text-amber-300",
      )}
    >
      ⚠ {source.stale_days}일{rose ? " 미수집 — 복구 불가" : " 지연"}
    </span>
  );
}
