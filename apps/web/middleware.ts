import { NextRequest, NextResponse } from "next/server";
import { GATE_COOKIE, verifyToken } from "@/lib/gate";

// ★2026-10-09 입장 게이트: 랜딩(/)을 뺀 모든 화면은 서명이 맞고 만료 전(1시간)인 토큰이 있어야 연다.
//   없거나·위조됐거나·만료됐으면 랜딩으로 보내고 낡은 쿠키는 지운다.
// ⚠️화면(Next :3000)만 막는다 — 백엔드 API(:8000)는 이 게이트 밖이다.
export function middleware(req: NextRequest) {
  if (req.nextUrl.pathname === "/") return NextResponse.next();
  if (verifyToken(req.cookies.get(GATE_COOKIE)?.value) !== null) return NextResponse.next();
  const res = NextResponse.redirect(new URL("/", req.url));
  if (req.cookies.has(GATE_COOKIE)) res.cookies.delete(GATE_COOKIE);
  return res;
}

export const config = {
  // Node 런타임 — 서명 검증에 node:crypto, 루트 .env 읽기에 node:fs 를 쓴다(Next 15.5 정식 지원).
  runtime: "nodejs",
  // 정적 파일·Next 내부·라우트 핸들러(/api/unlock)는 막지 않는다.
  matcher: ["/((?!_next/|api/|.*\\..*).*)"],
};
