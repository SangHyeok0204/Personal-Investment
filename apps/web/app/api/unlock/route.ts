import { NextRequest, NextResponse } from "next/server";
import {
  GATE_COOKIE,
  GATE_TTL_SECONDS,
  dashboardPassword,
  issueToken,
  safeEqual,
  verifyToken,
} from "@/lib/gate";

export const runtime = "nodejs";

// 비밀번호가 4자리라 무작정 대입을 막는다 — 5번 틀리면 1분 잠금(프로세스 메모리, 재시작하면 풀림).
const MAX_FAILS = 5;
const LOCK_MS = 60_000;
let fails = 0;
let lockedUntil = 0;

// 토큰이 살아 있나 — 랜딩이 '시작하기'에서 비밀번호 칸을 건너뛸지 정한다.
export function GET(req: NextRequest) {
  const exp = verifyToken(req.cookies.get(GATE_COOKIE)?.value);
  return NextResponse.json({ unlocked: exp !== null, expires_at: exp });
}

// 비밀번호 확인 → 맞으면 1시간짜리 서명 토큰을 httpOnly 쿠키로. ⚠️비밀번호·토큰을 응답 본문에 싣지 않는다.
export async function POST(req: NextRequest) {
  // ⚠️본문을 먼저 다 읽고 나서 잠금 확인·시도 차감을 await 없이 한 번에 — 그 사이에 await 가 끼면
  //   동시에 쏜 요청들이 전부 잠금 확인을 통과해 4자리를 한 번에 다 대입할 수 있다(보안 리뷰 #1).
  const body = (await req.json().catch(() => ({}))) as { password?: unknown };
  const now = Date.now();
  if (now < lockedUntil) {
    const wait = Math.ceil((lockedUntil - now) / 1000);
    return NextResponse.json(
      { ok: false, error: `여러 번 틀려 잠겼습니다. ${wait}초 뒤 다시 시도하세요.` },
      { status: 429 },
    );
  }
  fails += 1; // 비교 전에 시도를 먼저 센다 — 맞으면 아래에서 0 으로 되돌린다
  if (fails >= MAX_FAILS) {
    fails = 0;
    lockedUntil = now + LOCK_MS;
  }
  const expected = dashboardPassword();
  const issued = issueToken(now);
  if (!expected || !issued) {
    return NextResponse.json(
      { ok: false, error: "입장 설정이 없습니다(.env DASHBOARD_PASSWORD · DASHBOARD_SESSION_SECRET)." },
      { status: 500 },
    );
  }
  const given = typeof body.password === "string" ? body.password : "";
  if (!safeEqual(given, expected)) {
    return NextResponse.json({ ok: false, error: "비밀번호가 맞지 않습니다." }, { status: 401 });
  }
  fails = 0;
  lockedUntil = 0;
  const res = NextResponse.json({ ok: true, expires_at: issued.exp });
  res.cookies.set(GATE_COOKIE, issued.token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: GATE_TTL_SECONDS,
  });
  return res;
}
