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
  // 공개 경로만 이름으로 뺀다 — Next 정적 파일, 입장 API, 랜딩 이미지·아이콘.
  // ⚠️예전엔 '점이 든 경로 전부'를 뺐는데, /research/valuechain/foo.bar 처럼 동적 경로에 점을
  //   넣으면 화면이 토큰 없이 열렸다(보안 리뷰 #3). 새 /api/* 라우트도 기본은 막힌다.
  matcher: ["/((?!_next/static/|_next/image|_next/webpack-hmr|api/unlock$|landing\\.jpg$|icon\\.svg$|favicon\\.ico$).*)"],
};
