"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { PlannedList, StubCard } from "@/components/stub";
import { cn } from "@/lib/utils";

// 연동 상태를 한눈에 보는 화면. 실제 키 입력 폼은 API(POST /connections)가
// 준비된 뒤에 붙인다 — 지금 폼만 만들어 두면 제출할 곳이 없어 반쪽이 된다.
const CONNECTIONS = [
  {
    broker: "키움증권",
    name: "주계좌",
    env: "실전",
    state: "미연동",
    note: "REST OpenAPI — appkey/secret 발급 후 등록",
  },
  {
    broker: "키움증권",
    name: "ISA / 연금저축",
    env: "실전",
    state: "미연동",
    note: "동일 앱키로 계좌만 추가",
  },
  {
    broker: "토스증권",
    name: "토스 계좌",
    env: "실전",
    state: "미연동",
    note: "DailyPriceAgent 의 toss 수집기 재사용 예정",
  },
];

function StateChip({ state }: { state: string }) {
  const live = state === "연동됨";
  return (
    <span
      className={cn(
        "rounded-full px-2.5 py-1 text-[11px] font-extrabold",
        live
          ? "bg-status-success/10 text-status-success"
          : "bg-slate-100 text-ink-muted",
      )}
    >
      {state}
    </span>
  );
}

export default function ConnectionsPage() {
  return (
    <>
      <Topbar title="계좌 연동" subtitle="증권사 API 키 등록" showAccountContext={false} />
      <PageContainer wide>
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard title="연동 목록" subtitle="증권사별 API 연결 상태">
            <div className="space-y-2.5">
              {CONNECTIONS.map((c) => (
                <div
                  key={`${c.broker}-${c.name}`}
                  className="flex items-center gap-4 rounded-xl border border-hairline px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-extrabold text-ge-navy">
                        {c.broker}
                      </span>
                      <span className="text-[12px] font-semibold text-ink-muted">
                        {c.name}
                      </span>
                      <span className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[10px] font-bold text-ge-point">
                        {c.env}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] font-medium text-ink-faint">
                      {c.note}
                    </p>
                  </div>
                  <StateChip state={c.state} />
                  <button
                    type="button"
                    disabled
                    className="shrink-0 rounded-lg border border-hairline bg-white px-3 py-1.5 text-[12px] font-bold text-ink-muted disabled:opacity-60"
                  >
                    키 등록
                  </button>
                </div>
              ))}
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
