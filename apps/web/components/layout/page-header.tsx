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
}: {
  children: React.ReactNode;
  // wide=true: 모니터링 화면용 — 폭 제한 없이 메인 영역을 꽉 채운다.
  wide?: boolean;
}) {
  return (
    <div className={wide ? "w-full px-6 py-6" : "mx-auto max-w-5xl px-8 py-10"}>
      {children}
    </div>
  );
}
