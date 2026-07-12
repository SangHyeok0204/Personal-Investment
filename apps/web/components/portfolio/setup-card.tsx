import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SetupCard() {
  return (
    <Card>
      <CardHeader>
        <span className="eyebrow">시작하기</span>
        <CardTitle>키움 계좌 연결 준비</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-ink-muted">
          아직 동기화된 포트폴리오가 없습니다. 아래 3단계를 완료하면 키움증권 계좌
          자산이 이 화면에 표시됩니다.
        </p>
        <ol className="space-y-3">
          <Step n={1}>
            <Code>.env</Code> 파일에 키움 REST API 키를 입력합니다.
            <Pre>{`KIWOOM_APP_KEY=발급받은_APP_KEY
KIWOOM_SECRET_KEY=발급받은_SECRET_KEY`}</Pre>
          </Step>
          <Step n={2}>
            API·워커 컨테이너를 재기동해 새 키를 반영합니다.
            <Pre>docker compose up -d --force-recreate api worker</Pre>
          </Step>
          <Step n={3}>
            이 화면 상단의{" "}
            <span className="font-medium text-ink-secondary">키움 계좌 동기화</span>{" "}
            버튼을 클릭합니다.
          </Step>
        </ol>
      </CardContent>
    </Card>
  );
}

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-canvas-soft text-xs font-semibold text-ink-secondary">
        {n}
      </span>
      <div className="text-sm leading-relaxed text-ink-secondary">{children}</div>
    </li>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-canvas-soft px-1.5 py-0.5 font-mono text-[13px] text-ink-secondary">
      {children}
    </code>
  );
}

function Pre({ children }: { children: ReactNode }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-md border border-hairline bg-canvas-soft px-3 py-2 font-mono text-[13px] leading-relaxed text-ink-secondary">
      {children}
    </pre>
  );
}
