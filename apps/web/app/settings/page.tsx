"use client";

import { API_BASE_URL, APP_VERSION } from "@/lib/api";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function SettingsPage() {
  const rows = [
    { label: "API base URL", value: API_BASE_URL, mono: true },
    { label: "App version", value: APP_VERSION, mono: false },
    { label: "Environment", value: "Local development", mono: false },
  ];

  return (
    <>
      <Topbar
        title="설정"
        subtitle="Read-only system information for this phase."
      />
      <PageContainer>
        <Card>
          <CardHeader>
            <span className="eyebrow">System</span>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="divide-y divide-hairline">
              {rows.map((r) => (
                <div
                  key={r.label}
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <dt className="text-sm text-ink-muted">{r.label}</dt>
                  <dd
                    className={
                      r.mono
                        ? "font-mono text-xs text-ink-secondary"
                        : "text-sm font-medium text-ink-secondary"
                    }
                  >
                    {r.value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 text-xs text-ink-faint">
              Settings are read-only in this phase. Configuration is managed
              through environment variables.
            </p>
          </CardContent>
        </Card>
      </PageContainer>
    </>
  );
}
