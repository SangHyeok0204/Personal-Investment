"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { SidebarProvider } from "@/components/layout/sidebar-context";
import { AccountProvider } from "@/components/layout/account-context";
import { ConnectProvider } from "@/components/brokerage/connect-context";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000,
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      {/* 사이드바 접힘 상태 — Sidebar(aside)와 각 페이지 Topbar 가 형제라 여기서 공유한다. */}
      <SidebarProvider>
        {/* 선택된 계좌 — 상단 바가 고르고 각 화면이 읽는다(계좌 목록도 여기서 한 번만). */}
        <AccountProvider>
          {/* 계좌 연동 팝업 — 여러 화면에서 열리므로 루트에 하나만 둔다. */}
          <ConnectProvider>{children}</ConnectProvider>
        </AccountProvider>
      </SidebarProvider>
    </QueryClientProvider>
  );
}
