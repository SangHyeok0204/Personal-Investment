"use client";

import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPortfolioAccounts, type PortfolioAccount } from "@/lib/api";

// 선택된 계좌 — 상단 바가 고르고 각 페이지가 읽는다. 사이드바 접힘과 같은 이유로
// (Topbar 와 페이지 본문이 형제) 컨텍스트에 둔다.
//
// "all" = 전체 계좌 합산. 서버에는 account_id 를 보내지 않는 것으로 표현한다.
//
// ★계좌 목록 자체도 여기서 한 번만 가져온다 — 화면마다 따로 부르면 상단 바와
//   본문이 서로 다른 계좌 목록을 들고 있는 순간이 생긴다.

export const ALL_ACCOUNTS = "all";

type AccountCtx = {
  accountId: string;
  setAccountId: (id: string) => void;
  accounts: PortfolioAccount[];
  /** 계좌가 하나도 없음 = 아직 증권사 연동 전. 0원과 구분해야 한다. */
  connected: boolean;
  isLoading: boolean;
  /** API 자체에 닿지 못한 상태(백엔드가 안 떠 있음 등). */
  isError: boolean;
  selected: PortfolioAccount | null;
};

const Ctx = createContext<AccountCtx | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [accountId, setAccountId] = useState<string>(ALL_ACCOUNTS);

  const query = useQuery({
    queryKey: ["portfolioAccounts"],
    queryFn: getPortfolioAccounts,
    staleTime: 60_000,
  });

  const value = useMemo<AccountCtx>(() => {
    const accounts = query.data?.items ?? [];
    return {
      accountId,
      setAccountId,
      accounts,
      connected: query.data?.connected ?? false,
      isLoading: query.isLoading,
      isError: query.isError,
      selected: accounts.find((a) => a.id === accountId) ?? null,
    };
  }, [accountId, query.data, query.isLoading, query.isError]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAccount(): AccountCtx {
  const c = useContext(Ctx);
  if (!c) {
    throw new Error("useAccount 는 AccountProvider 안에서만 쓸 수 있다 (app/providers.tsx)");
  }
  return c;
}
