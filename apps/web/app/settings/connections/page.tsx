"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Landmark, LineChart } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StubCard } from "@/components/stub";
import { getPortfolioConnections, type PortfolioConnection } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useConnectDialog } from "@/components/brokerage/connect-context";
import { cn } from "@/lib/utils";

// 연동 상태 화면.
//
// ★2026-09-21 정정(사용자): **토스는 계좌가 아니다.** 키움 계좌의 보유 종목에 대해
//   실시간 가격을 받아오는 **시세 소스**다. 이전 판에서 토스를 계좌 목록에 섞어
//   두었는데, 그러면 존재하지 않는 "토스 계좌 잔고"를 화면이 약속하게 된다.
//   그래서 이 화면을 두 갈래로 나눈다:
//     · 계좌 연동  — 내가 무엇을 얼마나 들고 있나 (증권사 계좌)
//     · 시세 소스  — 그게 지금 얼마인가 (가격 피드)
//
// ★2026-09-21: 키 입력을 팝업(ConnectDialog)으로 붙였다. 키는 브라우저 → 서버로
//   한 번만 흐르고, 서버는 검증 성공 후에만 .env(0600)에 저장하며 어떤 응답에도
//   키를 싣지 않는다(지문과 꼬리 4자리뿐).

const PRICE_SOURCES = [
  {
    id: "toss",
    name: "토스증권 Open API",
    role: "국내 종목 현재가",
    note: "보유 종목의 실시간 가격. 계좌 조회가 아니다.",
    caveats: [
      "클라이언트당 유효 토큰 1개 — 같은 키를 쓰는 다른 수집기와 동시 가동 금지",
      "IP 허용목록 필요 (WTS 설정 → Open API)",
    ],
  },
  {
    id: "kiwoom-quote",
    name: "키움 잔고 응답",
    role: "폴백 현재가",
    note: "잔고 TR 이 주는 조회 시점 가격. 무거워 자주 부를 수 없다.",
    caveats: [],
  },
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
  const { open: openConnect } = useConnectDialog();
  const connections = useQuery({
    queryKey: ["portfolioConnections"],
    queryFn: getPortfolioConnections,
    staleTime: 30_000,
  });

  // 계좌 연동은 증권사만. 시세 소스는 여기 섞이지 않는다.
  const items = connections.data ?? [];

  return (
    <>
      <Topbar title="계좌 연동" subtitle="증권사 계좌 · 시세 소스" showAccountContext={false} />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard
            title="계좌 연동"
            subtitle={
              connections.isLoading
                ? "불러오는 중…"
                : items.length > 0
                  ? `${items.length}건`
                  : "아직 등록된 연동 없음"
            }
          >
            <button
              type="button"
              onClick={openConnect}
              className="mb-3 w-full rounded-xl bg-ge-point px-4 py-2.5 text-[13px] font-extrabold text-white transition-colors hover:bg-ge-point/90"
            >
              API 키 등록 · 동기화
            </button>
            <div className="space-y-2.5">
              {items.map((c) => (
                <ConnectionRow key={c.id} connection={c} />
              ))}

              {!connections.isLoading && items.length === 0 && (
                <div className="flex items-center gap-4 rounded-xl border border-dashed border-hairline px-4 py-3 opacity-80">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-canvas-soft">
                    <Landmark className="h-4 w-4 text-ink-muted" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-extrabold text-ge-navy">
                      키움증권
                    </div>
                    <p className="mt-0.5 text-[11px] font-medium text-ink-faint">
                      {connections.isError
                        ? "API 서버에 연결하지 못했습니다."
                        : "REST OpenAPI"}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-extrabold text-ink-muted">
                    미등록
                  </span>
                </div>
              )}
            </div>
          </StubCard>

          <StubCard title="연동 순서">
            <PlannedList
              items={[
                "키움 OpenAPI 신청 → appkey / secretkey 발급",
                "⚠️서버 공인 IP 를 허용목록에 등록 — 안 하면 키가 맞아도 8050 으로 거부된다",
                "서버 .env 에 키 저장 (브라우저로 내려보내지 않는다)",
                "동기화 1회 실행 → 계좌·잔고·보유종목이 DB 에 적재된다",
                "대시보드는 DB만 읽는다 — 증권사 API 를 화면이 직접 때리지 않는다",
              ]}
            />
          </StubCard>

          {/* 시세 소스 — 계좌와 다른 관심사다. */}
          <StubCard
            title="시세 소스"
            className="xl:col-span-2"
          >
            <div className="grid gap-2.5 xl:grid-cols-2">
              {PRICE_SOURCES.map((s) => (
                <div
                  key={s.id}
                  className="rounded-xl border border-hairline px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ge-blue-bg">
                      <LineChart className="h-4 w-4 text-ge-point" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[14px] font-extrabold text-ge-navy">
                          {s.name}
                        </span>
                        <span className="rounded bg-canvas-soft px-1.5 py-0.5 text-[10px] font-bold text-ink-muted">
                          {s.role}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] font-medium text-ink-faint">
                        {s.note}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-extrabold text-ink-muted">
                      미등록
                    </span>
                  </div>
                  {s.caveats.length > 0 && (
                    <ul className="mt-2.5 space-y-1 border-t border-hairline pt-2.5">
                      {s.caveats.map((c) => (
                        <li
                          key={c}
                          className="text-[11px] font-medium leading-snug text-ink-faint"
                        >
                          · {c}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
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
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ge-blue-bg">
          <Landmark className="h-4 w-4 text-ge-point" />
        </span>
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
