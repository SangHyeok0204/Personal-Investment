"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { SidebarProvider } from "@/components/layout/sidebar-context";

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
      <SidebarProvider>{children}</SidebarProvider>
    </QueryClientProvider>
  );
}
