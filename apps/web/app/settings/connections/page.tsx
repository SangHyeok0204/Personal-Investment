"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StubCard } from "@/components/stub";
import { getPortfolioConnections, type PortfolioConnection } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// 연동 상태를 한눈에 보는 화면.
//
// ★2026-09-21 2차: 목록을 /api/v1/portfolio/connections 에 물렸다. 아직 등록된
//   연동이 없으면 **앞으로 붙일 대상**을 회색으로 보여 준다 — 빈 목록은 "없다"만
//   말하고 다음 행동을 알려주지 않는다.
//
// 키 입력 폼은 아직 만들지 않는다. POST 엔드포인트가 없어 제출할 곳이 없고,
// 반쪽짜리 폼은 "눌렀는데 아무 일도 안 난다"가 되어 없느니만 못하다.
// 키는 서버 .env 에 두고 브라우저로 내려보내지 않는 게 원칙이다.

const PLANNED_TARGETS = [
  { broker: "키움증권", name: "주계좌", note: "REST OpenAPI — appkey/secret 발급 후 등록" },
  { broker: "키움증권", name: "ISA / 연금저축", note: "동일 앱키로 계좌만 추가" },
  { broker: "토스증권", name: "토스 계좌", note: "DailyPriceAgent 의 toss 수집기 재사용 예정" },
];

function StateChip({ status }: { status: string }) {
  const tone =
    status === "CONNECTED"
      ? "bg-status-success/10 text-status-success"
      : status === "ERROR"
        ? "bg-status-failed/10 text-status-failed"
        : "bg-slate-100 text-ink-muted";
  const label =
    status === "CONNECTED" ? "연동됨" : status === "ERROR" ? "오류" : "설정됨";
  return (
    <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-extrabold", tone)}>
      {label}
    </span>
  );
}

export default function ConnectionsPage() {
  const connections = useQuery({
    queryKey: ["portfolioConnections"],
    queryFn: getPortfolioConnections,
    staleTime: 30_000,
  });

  const items = connections.data ?? [];

  return (
    <>
      <Topbar title="계좌 연동" subtitle="증권사 API 연결 상태" showAccountContext={false} />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard
            title="연동 목록"
            subtitle={
              connections.isLoading
                ? "불러오는 중…"
                : items.length > 0
                  ? `${items.length}건 등록됨`
                  : "아직 등록된 연동 없음"
            }
          >
            <div className="space-y-2.5">
              {items.map((c) => (
                <ConnectionRow key={c.id} connection={c} />
              ))}

              {!connections.isLoading && items.length === 0 && (
                <>
                  <p className="mb-1 text-[12px] font-semibold text-ink-muted">
                    {connections.isError
                      ? "API 서버에 연결하지 못했습니다 — 아래는 연동 예정 대상입니다."
                      : "아직 등록된 연동이 없습니다. 아래가 붙일 대상입니다."}
                  </p>
                  {PLANNED_TARGETS.map((t) => (
                    <div
                      key={`${t.broker}-${t.name}`}
                      className="flex items-center gap-4 rounded-xl border border-dashed border-hairline px-4 py-3 opacity-70"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[14px] font-extrabold text-ge-navy">
                            {t.broker}
                          </span>
                          <span className="text-[12px] font-semibold text-ink-muted">
                            {t.name}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] font-medium text-ink-faint">
                          {t.note}
                        </p>
                      </div>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-extrabold text-ink-muted">
                        미등록
                      </span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </StubCard>

          <StubCard title="연동 순서">
            <PlannedList
              items={[
                "키움 OpenAPI 신청 → appkey / secretkey 발급",
                "서버 .env 에 키 저장 (브라우저로 내려보내지 않는다)",
                "접근토큰 발급 → 계좌 목록 조회로 연결 확인",
                "잔고 · 체결 · 입출금을 주기 수집해 DB 적재",
                "대시보드는 DB만 읽는다 — 증권사 API 를 화면이 직접 때리지 않는다",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}

function ConnectionRow({ connection: c }: { connection: PortfolioConnection }) {
  return (
    <div className="rounded-xl border border-hairline px-4 py-3">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[14px] font-extrabold text-ge-navy">
              {c.broker_name}
            </span>
            <span className="text-[12px] font-semibold text-ink-muted">
              {c.connection_name}
            </span>
            <span className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[10px] font-bold text-ge-point">
              {c.environment}
            </span>
          </div>
          <p className="mt-1 text-[11px] font-medium text-ink-faint">
            마지막 동기화 {formatDateTime(c.last_synced_at)}
          </p>
        </div>
        <StateChip status={c.status} />
      </div>

      {/* 오류는 접어 두지 않는다 — 연동이 조용히 죽어 있으면 화면의 숫자가 낡는다. */}
      {c.last_error && (
        <div className="mt-2.5 flex items-start gap-2 rounded-lg bg-status-failed/5 px-3 py-2">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-status-failed" />
          <p className="text-[11px] font-semibold leading-snug text-status-failed">
            {c.last_error}
          </p>
        </div>
      )}
    </div>
  );
}
