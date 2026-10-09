// 대시보드 입장 비밀번호 — 서버(라우트 핸들러)에서만 쓴다. 클라이언트로 내보내지 않는다.
//
// ★2026-10-09 사용자 요청: 랜딩(/)의 '시작하기' 뒤에 비밀번호. 값은 저장소 루트 `.env` 의
//   DASHBOARD_PASSWORD 에 둔다(git 에 안 올라간다). Next 는 apps/web 의 .env 만 읽으므로
//   루트 `.env` 를 직접 읽는다. 프로세스 환경변수가 있으면 그쪽이 우선.
import { readFileSync } from "node:fs";
import path from "node:path";

export const GATE_COOKIE = "pi_unlocked";
export const GATE_MAX_AGE = 60 * 60 * 24 * 7; // 7일

export function dashboardPassword(): string | null {
  if (process.env.DASHBOARD_PASSWORD) return process.env.DASHBOARD_PASSWORD;
  try {
    const text = readFileSync(path.resolve(process.cwd(), "../../.env"), "utf8");
    const line = text.split("\n").find((l) => l.startsWith("DASHBOARD_PASSWORD="));
    const value = line?.slice("DASHBOARD_PASSWORD=".length).trim().replace(/^["']|["']$/g, "");
    return value || null;
  } catch {
    return null;
  }
}
