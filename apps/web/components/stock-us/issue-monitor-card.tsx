"use client";

import { Construction } from "lucide-react";

// [종목 모니터링 · 미국] 이슈 모니터 — 화면 오른쪽 절반. **아직 자리만 잡아 둔 것**이다.
//
// 앞으로 붙일 원천은 이미 있다: 어닝모니터 프로젝트의 `stock_issue_alert` 가 KST 06:00
// 슬롯마다 굽는 `output/results/stock_issue_alert/{YYYYMM}/{DD}/analysis_data.json`
// (숫자) + `종목이슈분석.md`(claude 가 쓴 분석 3줄·이슈 사유·근거 출처). 어닝과 같은
// 배선(collector 가 :ro 마운트에서 읽어 넘기고 화면은 그리기만)으로 이으면 된다.
//
// ★한 번 구현했다가 2026-09-01 사용자 지시로 되돌렸다(placeholder 복귀). 그때 확인해 둔
//   것들은 다시 만들 때 그대로 쓸 수 있으니 남겨 둔다:
//   · 숫자는 json, 서사는 md 에 있어 **둘을 티커로 합쳐야** 카드 한 장이 된다.
//     숫자를 md 표에서 정규식으로 긁지 말 것 — 타입이 있는 쪽(json)에서 가져온다.
//   · **리포트는 매일 나오지 않는다.** 버즈·주가 필터를 통과한 종목이 없으면 그날은
//     "통과한 종목이 없습니다" txt 한 줄뿐이다(2026-08-27~31 닷새 연속). 그래서 '오늘 것'만
//     띄우는 설계면 카드가 며칠씩 빈다 — '내용이 있는 가장 최근 리포트'와 '오늘 슬롯 상태'를
//     따로 실어야 며칠 전 것을 오늘 것으로 읽지 않는다.
//   · `analysis_data.json` 의 `cap_tier` 는 리포트 머리글의 필터 기준과 라벨이 한 칸 어긋난다
//     (INTU $97.8B→"mid", KO $394.3B→"large"). 화면에 옮기지 말 것.
export function IssueMonitorCard() {
  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-canvas">
      <header className="flex shrink-0 items-center gap-2 bg-ge-header px-3 py-1.5">
        <h2 className="shrink-0 text-[15px] font-extrabold text-white">이슈 모니터</h2>
        <span className="min-w-0 truncate text-[13px] text-white/60">
          종목별 이슈·버즈 — 준비 중
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-8 text-center">
        <Construction className="h-7 w-7 text-ink-faint" strokeWidth={1.6} />
        <div className="text-[13.5px] font-bold text-ink-muted">아직 구현 전입니다</div>
        <div className="max-w-[320px] text-[12.5px] leading-relaxed text-ink-faint">
          어닝모니터의 종목 이슈 분석(매일 06:00 KST)을 이 자리에 붙일 예정입니다.
        </div>
      </div>
    </section>
  );
}
