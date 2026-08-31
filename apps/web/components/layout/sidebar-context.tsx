"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

// 사이드바 접힘 상태 — 톱바의 햄버거 버튼이 토글하고 Sidebar 가 읽는다.
// 두 컴포넌트가 형제라 상태를 위로 올려야 하는데, 그 '위'가 루트 레이아웃이라
// 컨텍스트로 둔다. Providers 가 루트에 있어 **클라이언트 라우팅 중에는 유지**되고
// (페이지를 옮겨도 접힌 채로 남는다) 새로고침하면 펼친 상태로 돌아온다.
// ★localStorage 로 영속화하지 않는다 — SSR 첫 렌더와 어긋나 하이드레이션 경고가
//   나고, 그걸 피하려면 깜빡임을 감수해야 한다. 요구된 적 없는 복잡도라 뺐다.

type SidebarCtx = {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (v: boolean) => void;
};

const Ctx = createContext<SidebarCtx | null>(null);

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const toggle = useCallback(() => setCollapsed((v) => !v), []);
  const value = useMemo(
    () => ({ collapsed, toggle, setCollapsed }),
    [collapsed, toggle],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSidebar(): SidebarCtx {
  const c = useContext(Ctx);
  if (!c) {
    throw new Error("useSidebar 는 SidebarProvider 안에서만 쓸 수 있다 (app/providers.tsx)");
  }
  return c;
}
