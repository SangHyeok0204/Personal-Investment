"use client";

import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { SectorHub } from "@/components/valuechain/sector-hub";

// 산업 밸류체인 허브 — 섹터 카드를 골라 `/research/valuechain/{sector}` 로 들어간다.
// 목록: storage/valuechain/catalog.ttl → `GET /api/v1/research/valuechain/catalog`.
// ★그래프 뷰는 만들지 않는다 — 카드로만.

export default function ValueChainHubPage() {
  return (
    <>
      <Topbar
        title="산업 밸류체인"
        showAccountContext={false}
      />
      <PageContainer wide>
        <SectorHub />
      </PageContainer>
    </>
  );
}
