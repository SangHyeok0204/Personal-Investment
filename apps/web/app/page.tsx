"use client";

import { useEffect, useState } from "react";
import { ImageIcon } from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// 메인 화면(/) — 그림 한 장짜리 랜딩.
//
// ★2026-10-09 사용자 요청: 왼쪽 위 브랜드(홈) 버튼을 누르면 그림 하나만 있는 화면.
//   예전 "오늘" 요약 카드는 내렸다 — 숫자는 자산 현황(/portfolio)에 있다.
//
// 이미지 교체: `apps/web/public/landing.jpg` 에 파일을 두면 된다(다른 이름·형식이면
// 아래 LANDING_SRC 만 바꾼다). 파일이 없거나 못 읽으면 자리 표시(placeholder)가 보인다.
// ─────────────────────────────────────────────────────────────────────────────

const LANDING_SRC = "/landing.jpg";

export default function HomePage() {
  // ⚠️서버가 그린 <img> 는 hydration 전에 실패해 onError 를 놓친다 — 마운트 뒤 직접 불러 보고 결정한다.
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const probe = new Image();
    probe.onload = () => setLoaded(true);
    probe.src = LANDING_SRC;
  }, []);

  return (
    <div className="flex h-screen items-center justify-center p-6">
      {!loaded ? (
        <div className="flex h-full w-full flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed border-slate-300 bg-slate-50 text-slate-400">
          <ImageIcon className="h-12 w-12" strokeWidth={1.5} />
          <p className="text-sm font-semibold">랜딩 이미지 자리</p>
          <p className="text-xs">
            apps/web/public/landing.jpg 에 이미지를 넣으면 여기에 표시됩니다
          </p>
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- 크기를 모르는 사용자 이미지를 그대로 맞춘다
        <img
          src={LANDING_SRC}
          alt="랜딩 이미지"
          className="h-full w-full rounded-3xl object-cover"
        />
      )}
    </div>
  );
}
