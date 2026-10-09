import { NextRequest, NextResponse } from "next/server";

// ★2026-10-09 입장 게이트: 비밀번호를 통과하지 않았으면(쿠키 없음) 어떤 화면이든 랜딩(/)으로.
// ⚠️로컬 1인용 대시보드의 '입장 문'이다 — 보안 경계가 아니다(API :8000 은 따로 열려 있다).
const COOKIE = "pi_unlocked"; // lib/gate.ts 의 GATE_COOKIE 와 같다(미들웨어는 node: 모듈을 못 읽어 따로 둔다)

export function middleware(req: NextRequest) {
  if (req.nextUrl.pathname === "/") return NextResponse.next();
  if (req.cookies.get(COOKIE)?.value === "1") return NextResponse.next();
  return NextResponse.redirect(new URL("/", req.url));
}

export const config = {
  // 정적 파일·Next 내부·라우트 핸들러(/api/unlock)는 막지 않는다.
  matcher: ["/((?!_next/|api/|.*\\..*).*)"],
};
