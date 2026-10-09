import { timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { GATE_COOKIE, GATE_MAX_AGE, dashboardPassword } from "@/lib/gate";

export const runtime = "nodejs";

// 이미 들어와 있나(쿠키) — 랜딩이 '시작하기'에서 비밀번호 칸을 건너뛸지 정한다.
export function GET(req: NextRequest) {
  return NextResponse.json({ unlocked: req.cookies.get(GATE_COOKIE)?.value === "1" });
}

// 비밀번호 확인 → 맞으면 쿠키(httpOnly, 7일). ⚠️비밀번호를 응답에 싣지 않는다.
export async function POST(req: NextRequest) {
  const expected = dashboardPassword();
  if (!expected) {
    return NextResponse.json({ ok: false, error: "비밀번호가 설정되지 않았습니다(.env DASHBOARD_PASSWORD)." }, { status: 500 });
  }
  const body = (await req.json().catch(() => ({}))) as { password?: unknown };
  const given = typeof body.password === "string" ? body.password : "";
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return NextResponse.json({ ok: false, error: "비밀번호가 맞지 않습니다." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(GATE_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: GATE_MAX_AGE,
  });
  return res;
}
