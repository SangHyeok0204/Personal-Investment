"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import {
  DataTable,
  PlannedList,
  StatRow,
  StatTile,
  StubCard,
} from "@/components/stub";

// 영상 분석 — YouTube 에서 자막을 받아 요약·태깅하는 창구.
//
// ★설계 결정: **영상을 보지 않고 읽는다.** 시장 코멘터리 영상은 20분짜리에 핵심이
//   2분인 경우가 대부분이라, 자막을 받아 요약하고 종목/산업 태그만 뽑아 두면
//   "무엇을 말했는지"를 몇 초에 훑을 수 있다. 원본 링크는 항상 같이 둔다.
//
// ⚠️YouTube Data API v3 는 자막 **목록**은 주지만 자막 **본문**은 영상 소유자
//   OAuth 가 있어야 준다. 남의 영상 자막은 별도 경로(타임드텍스트 등)가 필요하고
//   서비스 약관을 확인해야 한다 — 이 화면을 실제로 채우기 전에 정할 문제다.
//   그래서 지금은 수집 경로를 하나로 못박지 않고 화면 골격만 잡는다.

const SOURCES = [
  { label: "구독 채널", desc: "정기적으로 보는 시장·산업 채널", status: "미등록" },
  { label: "키워드 감시", desc: "반도체 · HBM · AI 데이터센터", status: "미등록" },
  { label: "보유 종목", desc: "내 포지션을 언급한 영상", status: "미등록" },
];

export default function VideoResearchPage() {
  return (
    <>
      <Topbar
        title="영상 분석"
        subtitle="YouTube 자막 수집 · 요약 · 태깅"
        showAccountContext={false}
      />
      <PageContainer wide>
        <StatRow>
          <StatTile label="수집 영상" hint="요약 완료 기준" />
          <StatTile label="이번 주" />
          <StatTile label="내 종목 언급" hint="보유 종목이 나온 영상" />
          <StatTile label="미처리" hint="자막은 받았으나 요약 전" />
        </StatRow>

        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <StubCard title="최근 영상" subtitle="요약 · 언급 종목 · 감정">
            <DataTable
              columns={["영상", "채널", "길이", "언급 종목", "논조", "날짜"]}
              align={["left", "left", "right", "left", "right", "right"]}
              empty="수집 경로가 아직 연결되지 않았습니다"
            >
              {null}
            </DataTable>
          </StubCard>

          <StubCard title="수집 대상" subtitle="무엇을 가져올지">
            <div className="space-y-2.5">
              {SOURCES.map((s) => (
                <div
                  key={s.label}
                  className="flex items-center gap-3 rounded-xl border border-dashed border-hairline px-3.5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-extrabold text-ge-navy">
                      {s.label}
                    </div>
                    <p className="mt-0.5 text-[11px] font-medium text-ink-faint">
                      {s.desc}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-extrabold text-ink-muted">
                    {s.status}
                  </span>
                </div>
              ))}
            </div>
          </StubCard>

          <StubCard title="붙이기 전에 정할 것" className="xl:col-span-2">
            <PlannedList
              items={[
                "자막 확보 경로 — YouTube Data API v3 는 남의 영상 자막 본문을 주지 않는다. 대안과 약관을 먼저 확인",
                "API 키는 서버에만 둔다 — 브라우저에서 YouTube 를 직접 호출하면 키가 노출되고 쿼터가 샌다",
                "쿼터 설계 — Data API 기본 일일 10,000 유닛. search.list 는 1회 100 유닛이라 검색 남용이 빠르게 한도를 태운다",
                "요약은 원문 링크와 타임스탬프를 같이 남긴다 — 요약만 남으면 근거를 되짚을 수 없다",
                "논조(강세/약세)는 판단이지 사실이 아니다 — 근거 문장을 같이 보관",
              ]}
            />
          </StubCard>
        </div>
      </PageContainer>
    </>
  );
}
