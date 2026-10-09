"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";

// 랜딩(/)은 사이드바 없이 전체 화면, 나머지는 사이드바 + 본문.
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/") return <>{children}</>;
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      {/* 각 페이지가 자체 헤더/툴바를 렌더링한다. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
