import * as React from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-sm text-ink-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageContainer({
  children,
  wide = false,
  fit = false,
}: {
  children: React.ReactNode;
  // wide=true: 모니터링 화면용 — 폭 제한 없이 메인 영역을 꽉 채운다.
  wide?: boolean;
  // fit=true: **한 화면에 담는다**. 페이지가 스크롤되지 않고, 내용이 남는 높이를
  //   나눠 갖는다. 세부는 hover/click 으로 팝업에서 본다.
  //   ★2026-09-21 사용자 요청: "스크롤 내려서 보는 형태가 아니라 1페이지에 압축".
  //   ⚠️상단 바(h-16=64px)를 뺀 높이를 쓴다. 뷰포트 전체로 잡으면 딱 그만큼 넘쳐
  //     결국 스크롤이 생긴다.
  fit?: boolean;
}) {
  if (fit) {
    return (
      <div className="flex h-[calc(100vh-64px)] w-full flex-col gap-3 overflow-hidden px-5 py-4">
        {children}
      </div>
    );
  }
  return (
    <div className={wide ? "w-full px-6 py-6" : "mx-auto max-w-5xl px-8 py-10"}>
      {children}
    </div>
  );
}
