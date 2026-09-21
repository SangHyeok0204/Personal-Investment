"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Wallet } from "lucide-react";
import { useSidebar } from "@/components/layout/sidebar-context";
import { navItems, type NavChild } from "@/components/layout/nav-config";
import { cn } from "@/lib/utils";

// 메뉴 항목 목록은 `nav-config.ts` 로 분리했다(2026-09-21) — 개조 중에는 IA 가
// 자주 바뀌는데, 목록과 렌더링이 한 파일에 있으면 매번 컴포넌트를 건드리게 된다.

/** 플라이아웃 항목 오른쪽 끝에 붙는 상태 점. 아직 안 붙은 자리를 눈으로 구분한다. */
function StatusDot({ status }: { status: NavChild["status"] }) {
  if (status === "live") return null; // 동작하는 게 기본 — 표시하지 않는다.
  return (
    <span
      title={status === "placeholder" ? "화면만 있음 (데이터 미연결)" : "준비 중"}
      className={cn(
        "ml-2 h-1.5 w-1.5 shrink-0 rounded-full",
        status === "placeholder" ? "bg-amber-400" : "bg-slate-300",
      )}
    />
  );
}

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
          <Wallet className="h-5 w-5 text-white" strokeWidth={2.2} />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-extrabold tracking-tight text-white">
            My Portfolio
          </div>
          <div className="text-[10px] font-semibold tracking-[0.18em] text-white/70">
            PERSONAL INVESTING
          </div>
        </div>
      </Link>

      {/* ⚠️여기에 overflow-* 를 주면 안 된다 — 하위 메뉴가 `absolute left-full` 로
          이 nav **바깥**에 뜨는데, CSS 상 한 축이 visible 이 아니면 다른 축도
          auto 로 계산되어 가로로 잘린다(플라이아웃이 통째로 안 보인다).
          2026-09-21 에 overflow-y-auto 를 넣었다가 정확히 이걸로 깨뜨렸다. */}
      <nav className="flex flex-1 flex-col gap-1.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          // 하위 경로(`/portfolio/holdings`)에 있어도 상위 그룹이 켜져 보이게 한다.
          const hrefs = [
            item.href,
            ...(item.children ?? []).map((c) => c.href),
          ].filter((h): h is string => h != null);
          const active = hrefs.some(
            (h) => pathname === h || (h !== "/" && pathname.startsWith(`${h}/`)),
          );
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

              {/* 버튼 또는 이 패널에 커서/포커스가 있으면 열린다. pl-2 가 버튼↔패널 hover 간격을 잇는다.
                  ⚠️**열렸을 때만 렌더한다.** 항상 그려 두고 opacity-0 으로 숨기면,
                    `absolute` 라도 조상(nav)의 스크롤 영역은 그대로 늘어난다.
                    실제로 nav 내용은 522px 인데 scrollHeight 가 747px 이 되어
                    보이지도 않는 메뉴 때문에 페이지에 세로 스크롤이 생겼었다
                    (2026-09-21). 등장 효과는 `.flyout-enter` keyframe 이 대신한다. */}
              {item.children && open && (
                <div className="absolute left-full top-0 z-50 pl-2">
                  <div className="flyout-enter min-w-[214px] rounded-2xl bg-white p-3 shadow-[0_16px_36px_rgba(36,59,94,0.26)] ring-1 ring-hairline">
                    <div className="mb-1.5 flex items-center gap-2 px-2 pb-1.5">
                      <Icon className="h-4 w-4 text-ge-point" strokeWidth={2.6} />
                      <span className="text-[11px] font-bold tracking-wide text-ge-point">
                        {item.label}
                      </span>
                    </div>
                    {item.children.map((child, i) => {
                      const childActive =
                        child.href != null && pathname === child.href;
                      const childClass = cn(
                        "flex w-full items-start justify-between gap-2 rounded-lg px-3 py-2 text-left transition-colors",
                        child.href
                          ? "hover:bg-ge-blue-bg"
                          : "cursor-default opacity-55",
                        childActive && "bg-ge-blue-bg",
                      );
                      const childInner = (
                        <>
                          <span className="min-w-0">
                            <span className="flex items-center text-[14px] font-extrabold text-ge-navy">
                              {child.label}
                              <StatusDot status={child.status} />
                            </span>
                            {child.hint && (
                              <span className="mt-0.5 block text-[11px] font-medium leading-tight text-ink-muted">
                                {child.hint}
                              </span>
                            )}
                          </span>
                          {child.href && (
                            <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-ge-point" />
                          )}
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
                        <div key={`${child.label}-${i}`} className={childClass}>
                          {childInner}
                        </div>
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
