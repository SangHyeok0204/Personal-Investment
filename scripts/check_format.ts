/**
 * 금액·단가·수량 표시 규칙을 잠근다.
 *
 * ★왜 스크립트인가: 웹에는 테스트 러너가 없다. 러너를 들이는 것보다 이 파일
 *   하나로 잠그는 편이 가볍다 — `audit_*.py` 와 같은 결이다.
 *
 * ★왜 필요한가: 금액 표시가 소수점을 **잘라** 버리고 있었다(₩174,261.89 →
 *   "₩174,261"). 한 줄만 보면 1원이라 눈에 안 띄지만, 더해지는 칸끼리 합이
 *   안 맞는다 — 보유 종목 화면에서 매입 + 평가손익 + 제비용이 평가금액보다
 *   1원 모자랐다.
 *
 * ⚠️고치면서 **거의 더 큰 것을 깨뜨릴 뻔했다.** 정수부를 올리는 로직을
 *   `splitDecimal` 안에 넣었더니 소수를 살려 쓰는 곳까지 올라가, 단가 139.90 이
 *   "140.90" 이 될 뻔했다. 그래서 이 파일의 절반은 **반올림하면 안 되는 것들**이다.
 *
 * 사용: npx tsx scripts/check_format.ts   (apps/web 에서 실행)
 */

import {
  formatKrwCompactString,
  formatKrwSigned,
  formatKrwString,
  formatPercentString,
  formatPriceString,
  formatQuantityString,
} from "../apps/web/lib/format";

type Case = { got: string; want: string; why: string };

const cases: Case[] = [
  // ── 금액: 반올림한다 ──────────────────────────────────────────────
  { got: formatKrwString("174261.89"), want: "₩174,262", why: "잘라 버리면 합이 1원 모자란다" },
  { got: formatKrwString("33352051.11"), want: "₩33,352,051", why: "내림 쪽도 반올림 규칙대로" },
  { got: formatKrwSigned("2881334.00"), want: "+₩2,881,334", why: "손익은 부호를 붙인다" },
  { got: formatKrwSigned("-149544.50"), want: "-₩149,545", why: "음수는 크기로 반올림한다" },
  { got: formatKrwSigned("0.00"), want: "₩0", why: "0 에는 부호를 붙이지 않는다" },
  { got: formatKrwSigned("-0.40"), want: "₩0", why: "반올림해서 0 이면 '-₩0' 이 아니다" },
  { got: formatPriceString("19710.91", "KRW"), want: "19,711", why: "원화 단가도 반올림" },

  // ── 소수를 살려 쓰는 것: 절대 반올림하지 않는다 ──────────────────
  { got: formatPriceString("139.90", "USD"), want: "139.90", why: "정수부를 올리면 140.90 이 된다" },
  { got: formatPriceString("130.85", "USD"), want: "130.85", why: "외화 단가는 소수 두 자리 그대로" },
  { got: formatPriceString("5103.49", "USD"), want: "5,103.49", why: "천 단위 구분 + 소수 유지" },
  { got: formatQuantityString("10.500000"), want: "10.5", why: "수량은 반올림하지 않는다" },
  { got: formatQuantityString("170.000000"), want: "170", why: "뒤의 0 은 지운다" },

  // ── 요약 표시 ────────────────────────────────────────────────────
  { got: formatKrwCompactString("248500000.60"), want: "₩2.49억", why: "헤드라인용 억 단위" },
  { got: formatKrwCompactString("36407647.00"), want: "₩3,641만", why: "만 단위" },

  // ── 비율 ─────────────────────────────────────────────────────────
  { got: formatPercentString("0.086392"), want: "+8.64%", why: "수익률은 부호를 붙인다" },
  { got: formatPercentString("-0.019802"), want: "-1.98%", why: "음수 수익률" },

  // ── 없는 값은 0 이 아니다 ────────────────────────────────────────
  { got: formatKrwString(null), want: "—", why: "null 을 ₩0 으로 그리면 거짓말이 된다" },
  { got: formatKrwSigned(undefined), want: "—", why: "undefined 도 마찬가지" },
  { got: formatPriceString("", "USD"), want: "—", why: "빈 문자열" },
];

let bad = 0;
for (const c of cases) {
  const ok = c.got === c.want;
  if (!ok) bad += 1;
  console.log(
    `${ok ? "  OK" : "실패"} ${JSON.stringify(c.got).padEnd(18)} ` +
      `기대 ${JSON.stringify(c.want).padEnd(18)} ${c.why}`,
  );
}

console.log("=".repeat(56));
console.log(bad === 0 ? `전부 일치 — 검사 ${cases.length}건` : `${bad}건 어긋남`);
process.exit(bad === 0 ? 0 : 1);
