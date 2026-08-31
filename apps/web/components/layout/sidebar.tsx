"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ChevronRight,
  History,
  LayoutGrid,
  Newspaper,
  Settings,
  Sigma,
  TrendingUp,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useSidebar } from "@/components/layout/sidebar-context";
import { cn } from "@/lib/utils";

// 5개 분류 체계 (시장 모니터링 / 뉴스 모니터링 / Quant / 기타 / 설정).
// href 가 있는 항목만 실제 라우팅되고, 나머지는 아직 준비 중인 placeholder 다.
type NavItem = {
  label: string;
  icon: LucideIcon;
  href?: string;
  children?: { label: string; href?: string }[];
};

const navItems: NavItem[] = [
  {
    // 메인(/)은 브랜드 로고 클릭으로만 진입 — 이 항목은 플라이아웃 전용.
    label: "시장 모니터링",
    icon: TrendingUp,
    children: [
      { label: "iNAV 모니터", href: "/inav" },
      { label: "WRAP", href: "/wrap" },
      { label: "LP 평가", href: "/lp-eval" },
      { label: "종목 모니터", href: "/stock-monitor" },
      // 하위 페이지 `/ai-key-data/epoch` 는 2026-08-28 사용자 지시로 폐지 —
      // Epoch AI·ADP·FOMC내재확률이 전부 메인 카드(탭)로 편입됐다.
      { label: "AI Key Data", href: "/ai-key-data" },
    ],
  },
  {
    label: "뉴스 모니터링",
    icon: Newspaper,
    children: [
      { label: "기사" },
      { label: "텔레그램", href: "/telegram-news" },
      { label: "placeholder" },
      { label: "placeholder" },
    ],
  },
  {
    label: "Quant",
    icon: Sigma,
    children: [
      { label: "매크로", href: "/macro" },
      { label: "모멘텀" },
      { label: "재무" },
      { label: "기술적 분석" },
      { label: "sentiment" },
    ],
  },
  {
    label: "성과 분석",
    icon: History,
    children: [
      { label: "TORUS/AI테크", href: "/track-record/torus-aicoretech" },
      { label: "FUND3" },
    ],
  },
  {
    label: "기타",
    icon: LayoutGrid,
    children: [
      { label: "AI token usage", href: "/ai-token-usage" },
      { label: "LAN dashboard", href: "/lan-dashboard" },
      { label: "종토방", href: "/stock-discussion" },
      { label: "회의", href: "/meeting" },
    ],
  },
  {
    label: "설정",
    icon: Settings,
    href: "/settings",
    children: [{ label: "placeholder" }, { label: "placeholder" }],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const [openLabel, setOpenLabel] = useState<string | null>(null);
  const { collapsed } = useSidebar();

  return (
    // ★접기는 **음수 마진**으로 한다(2026-08-28). `-ml-[212px]` 면 레이아웃 상 폭이
    //   0이 되어 본문이 그만큼 넓어지고, aside 자신은 화면 왼쪽 밖으로 밀려나
    //   '슬라이드해서 접히는' 모양이 된다. 한 클래스로 두 효과가 같이 난다.
    // ⚠️`w-0 + overflow-hidden` 으로 접으면 안 된다 — 이 aside 안에서 하위 메뉴가
    //   `absolute left-full` 로 **바깥으로** 뜨는데 overflow-hidden 이 그걸 잘라
    //   플라이아웃 메뉴가 통째로 안 보이게 된다.
    // ⚠️`aria-hidden` 도 주지 않는다 — 접힌 상태에서도 링크가 탭 이동 대상이면
    //   포커스가 화면 밖으로 새는데, 그건 접기 UX 와 별개 문제라 여기서 만들지 않는다.
    <aside
      className={cn(
        "relative z-30 flex w-[212px] shrink-0 flex-col rounded-r-[34px] bg-gradient-to-b from-ge-main via-ge-point to-ge-navy py-6 shadow-[6px_0_26px_rgba(70,105,170,0.22)]",
        "transition-[margin-left] duration-300 ease-in-out motion-reduce:transition-none",
        collapsed && "-ml-[212px]",
      )}
    >
      {/* 브랜드 — 클릭 시 메인(/) 이동 */}
      <Link
        href="/"
        className="mb-7 flex items-center gap-2.5 px-6 transition-opacity hover:opacity-85"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/20 backdrop-blur-sm">
          <TrendingUp className="h-5 w-5 text-white" strokeWidth={2.2} />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-extrabold tracking-tight text-white">
            GE Dashboard
          </div>
          <div className="text-[10px] font-semibold tracking-[0.18em] text-white/70">
            INVEST INTELLIGENCE
          </div>
        </div>
      </Link>

      <nav className="flex flex-1 flex-col gap-1.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = item.href != null && pathname === item.href;
          const open = openLabel === item.label;
          const rowClass = cn(
            "flex items-center gap-3 rounded-r-[24px] py-3 pl-6 pr-4 transition-colors",
            active
              ? "bg-white text-ge-point shadow-[0_8px_20px_rgba(36,59,94,0.18)]"
              : "text-white/90 hover:bg-white/10",
          );
          const inner = (
            <>
              <span
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px]",
                  active ? "bg-ge-blue-bg" : "bg-white/25",
                )}
              >
                <Icon
                  className={cn(
                    "h-[19px] w-[19px]",
                    active ? "text-ge-point" : "text-white",
                  )}
                  strokeWidth={2}
                />
              </span>
              <span
                className={cn(
                  "text-[15px]",
                  active ? "font-extrabold" : "font-bold",
                )}
              >
                {item.label}
              </span>
            </>
          );

          return (
            <div
              key={item.label}
              className="relative"
              onMouseEnter={
                item.children ? () => setOpenLabel(item.label) : undefined
              }
              onMouseLeave={
                item.children ? () => setOpenLabel(null) : undefined
              }
              onFocus={
                item.children ? () => setOpenLabel(item.label) : undefined
              }
              onBlur={
                item.children
                  ? (e) => {
                      if (
                        !e.currentTarget.contains(e.relatedTarget as Node | null)
                      ) {
                        setOpenLabel(null);
                      }
                    }
                  : undefined
              }
            >
              {item.href ? (
                <Link href={item.href} className={rowClass}>
                  {inner}
                </Link>
              ) : (
                <button type="button" className={cn(rowClass, "w-full text-left")}>
                  {inner}
                </button>
              )}

              {/* 버튼 또는 이 패널에 커서/포커스가 있으면 열리고(스르륵 슬라이드),
                  둘 다 벗어나면 즉시 닫힌다(닫힘 duration-0). pl-2 가 버튼↔패널 hover 간격을 잇는다. */}
              {item.children && (
                <div
                  className={cn(
                    "absolute left-full top-0 z-50 pl-2 transition-all ease-out",
                    open
                      ? "pointer-events-auto translate-x-0 opacity-100 duration-200"
                      : "pointer-events-none -translate-x-2 opacity-0 duration-0",
                  )}
                >
                  <div className="min-w-[184px] rounded-2xl bg-white p-3 shadow-[0_16px_36px_rgba(36,59,94,0.26)] ring-1 ring-hairline">
                    <div className="mb-1.5 flex items-center gap-2 px-2 pb-1.5">
                      <Icon className="h-4 w-4 text-ge-point" strokeWidth={2.6} />
                      <span className="text-[11px] font-bold tracking-wide text-ge-point">
                        {item.label}
                      </span>
                    </div>
                    {item.children.map((child, i) => {
                      const childClass =
                        "flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-[14px] font-extrabold text-ge-navy transition-colors hover:bg-ge-blue-bg";
                      const childInner = (
                        <>
                          {child.label}
                          <ChevronRight className="h-4 w-4 text-ge-point" />
                        </>
                      );
                      return child.href ? (
                        <Link
                          key={`${child.label}-${i}`}
                          href={child.href}
                          className={childClass}
                        >
                          {childInner}
                        </Link>
                      ) : (
                        <button
                          key={`${child.label}-${i}`}
                          type="button"
                          className={childClass}
                        >
                          {childInner}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
