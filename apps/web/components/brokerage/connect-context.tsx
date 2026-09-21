"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ConnectDialog } from "@/components/brokerage/connect-dialog";

// 연동 팝업은 여러 곳(배너·연동 화면·상단 바)에서 열린다. 각자 모달을 들고 있으면
// 상태가 갈리므로 루트에 하나만 두고 여는 함수만 나눠 준다.

type ConnectCtx = { open: () => void };

const Ctx = createContext<ConnectCtx | null>(null);

export function ConnectProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <ConnectDialog open={isOpen} onClose={() => setIsOpen(false)} />
    </Ctx.Provider>
  );
}

export function useConnectDialog(): ConnectCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useConnectDialog 는 ConnectProvider 안에서만 쓸 수 있다");
  }
  return ctx;
}
