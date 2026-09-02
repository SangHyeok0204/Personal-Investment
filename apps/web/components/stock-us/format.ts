// [종목 모니터링 · 미국] 날짜 표기 헬퍼. 지금은 어닝 카드만 쓰지만, 이슈 모니터와
// 한국·중국 탭이 같은 표기를 이어받을 자리라 카드 밖에 둔다.
// 숫자·색 헬퍼는 [종목 모니터]의 `stock-monitor/format` 을 그대로 쓴다(등락 색 관례를
// 화면마다 다시 정하지 않기 위해서다).
import { EMDASH } from "@/components/stock-monitor/format";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/** "2026-08-27" → "08/27 (수)". Date 생성자에 문자열을 넘기면 UTC 로 읽혀 하루 밀린다. */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return EMDASH;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const wd = WEEKDAYS[new Date(y, m - 1, d).getDay()];
  return `${String(m).padStart(2, "0")}/${String(d).padStart(2, "0")} (${wd})`;
}

/** "2026-09-01 06:31:45" · ISO 둘 다 받아 "09/01 06:31" 로. */
export function fmtStamp(raw: string | null | undefined): string {
  if (!raw) return EMDASH;
  const m = raw.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return m ? `${m[2]}/${m[3]} ${m[4]}:${m[5]}` : raw;
}
