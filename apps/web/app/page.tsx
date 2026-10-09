"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Lock } from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// 랜딩(/) — 사이드바 없이 전체 화면 그림 + '시작하기'.
//
// ★2026-10-09 사용자 요청: 처음 들어오면 그림 한 장이 천천히 떠오르고, 가운데 '시작하기 →'.
//   누르면 비밀번호(.env DASHBOARD_PASSWORD) → 맞으면 내 자산/자산현황(/portfolio).
//   이미 통과했으면(쿠키) 비밀번호 칸 없이 바로 간다.
// 이미지 교체: apps/web/public/landing.jpg
// ─────────────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const router = useRouter();
  const [stage, setStage] = useState<"intro" | "password">("intro");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (stage === "password") inputRef.current?.focus();
  }, [stage]);

  async function start() {
    setBusy(true);
    try {
      const res = await fetch("/api/unlock", { cache: "no-store" });
      const { unlocked } = (await res.json()) as { unlocked: boolean };
      if (unlocked) {
        router.push("/portfolio");
        return;
      }
    } catch {
      /* 확인 실패 — 비밀번호 칸으로 */
    } finally {
      setBusy(false);
    }
    setStage("password");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      if (res.ok) {
        router.push("/portfolio");
        return;
      }
      setError(body.error ?? "확인하지 못했습니다.");
      setPassword("");
    } catch {
      setError("서버에 연결하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-black">
      {/* 배경 — 천천히 밝아지며 살짝 당겨지는 줌 */}
      <div
        className="landing-bg absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: "url(/landing.jpg)" }}
      />
      <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-black/20 to-black/60" />

      <div className="relative z-10 flex h-full flex-col items-center justify-center px-6 text-center text-white">
        <h1 className="landing-rise text-4xl font-extrabold tracking-tight drop-shadow-lg sm:text-6xl">
          My Portfolio
        </h1>
        <p className="landing-rise landing-delay-1 mt-3 text-sm font-medium tracking-[0.3em] text-white/80 sm:text-base">
          PERSONAL INVESTING
        </p>

        <div className="landing-rise landing-delay-2 mt-10 h-14">
          {stage === "intro" ? (
            <button
              type="button"
              onClick={start}
              disabled={busy}
              className="group flex items-center gap-2 rounded-full bg-white/90 px-8 py-3.5 text-base font-bold text-slate-900 shadow-xl backdrop-blur transition hover:bg-white disabled:opacity-70"
            >
              시작하기
              <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
            </button>
          ) : (
            <form onSubmit={submit} className="landing-pop flex flex-col items-center gap-2">
              <div className="flex items-center gap-2 rounded-full bg-white/90 py-1.5 pl-5 pr-1.5 shadow-xl backdrop-blur">
                <Lock className="h-4 w-4 text-slate-500" />
                <input
                  ref={inputRef}
                  type="password"
                  inputMode="numeric"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="비밀번호"
                  aria-label="비밀번호"
                  className="w-32 bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400"
                />
                <button
                  type="submit"
                  disabled={busy || !password}
                  aria-label="입장"
                  className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-900 text-white transition hover:bg-slate-700 disabled:opacity-40"
                >
                  <ArrowRight className="h-5 w-5" />
                </button>
              </div>
              {error && <p className="text-sm font-semibold text-rose-200 drop-shadow">{error}</p>}
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
