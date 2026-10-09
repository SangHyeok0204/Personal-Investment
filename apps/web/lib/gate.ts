// 대시보드 입장 게이트 — 비밀번호 확인 → 1시간짜리 서명 토큰(쿠키) → middleware 가 매 요청 검증.
// 서버(라우트 핸들러·Node middleware)에서만 쓴다. 클라이언트로 내보내지 않는다.
//
// ★2026-10-09 사용자 요청: 비밀번호를 넣으면 1시간 유지되는 토큰을 발급, 그걸로 페이지 접근을 판단.
//   토큰 = "<만료 epoch초>.<HMAC-SHA256(서명키, 'v1.'+만료)>" — 쿠키 값을 위조하거나 만료를
//   늘리면 서명이 안 맞는다. 서명키는 DASHBOARD_SESSION_SECRET + 비밀번호라서, 둘 중 하나만
//   바꿔도 이미 발급된 토큰은 전부 무효가 된다.
// 값은 저장소 루트 `.env` 의 DASHBOARD_PASSWORD · DASHBOARD_SESSION_SECRET(git 에 안 올라간다).
//   Next 는 apps/web 의 .env 만 읽으므로 루트 `.env` 를 직접 읽는다. 프로세스 환경변수가 우선.
import { createHmac, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

export const GATE_COOKIE = "pi_session";
export const GATE_TTL_SECONDS = 60 * 60; // 1시간(연장 없음 — 만료되면 다시 비밀번호)

function rootEnv(name: string): string | null {
  if (process.env[name]) return process.env[name]!;
  try {
    const text = readFileSync(path.resolve(process.cwd(), "../../.env"), "utf8");
    const line = text.split("\n").find((l) => l.startsWith(`${name}=`));
    const value = line?.slice(name.length + 1).trim().replace(/^["']|["']$/g, "");
    return value || null;
  } catch {
    return null;
  }
}

export function dashboardPassword(): string | null {
  return rootEnv("DASHBOARD_PASSWORD");
}

function signingKey(): string | null {
  const secret = rootEnv("DASHBOARD_SESSION_SECRET");
  const password = dashboardPassword();
  return secret && password ? `${secret}:${password}` : null;
}

function sign(key: string, exp: number): string {
  return createHmac("sha256", key).update(`v1.${exp}`).digest("base64url");
}

export function safeEqual(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** 새 토큰과 만료 시각(epoch초). 서명키가 없으면 null. */
export function issueToken(now = Date.now()): { token: string; exp: number } | null {
  const key = signingKey();
  if (!key) return null;
  const exp = Math.floor(now / 1000) + GATE_TTL_SECONDS;
  return { token: `${exp}.${sign(key, exp)}`, exp };
}

/** 서명이 맞고 아직 만료 전이면 만료 시각(epoch초), 아니면 null. */
export function verifyToken(token: string | undefined, now = Date.now()): number | null {
  if (!token) return null;
  const key = signingKey();
  if (!key) return null;
  const dot = token.indexOf(".");
  if (dot <= 0) return null;
  const exp = Number(token.slice(0, dot));
  if (!Number.isInteger(exp) || exp * 1000 <= now) return null;
  // 서명이 맞아도 1시간보다 먼 만료는 받지 않는다(키가 새 나가도 정책보다 오래 못 쓰게).
  if (exp * 1000 > now + GATE_TTL_SECONDS * 1000 + 60_000) return null;
  return safeEqual(token.slice(dot + 1), sign(key, exp)) ? exp : null;
}
