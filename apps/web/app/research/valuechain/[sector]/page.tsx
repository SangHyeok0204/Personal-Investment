"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { SectorView, useSectorDetail } from "@/components/valuechain/sector-view";

// 산업 밸류체인 섹터 상세 — 대분류 → 중분류 → 기업 카드(계획 S7, §5.3).
// 데이터: storage/valuechain/{sector}.ttl → `GET /api/v1/research/valuechain/{sector}`.

export default function ValueChainSectorPage() {
  const { sector } = useParams<{ sector: string }>();
  const code = decodeURIComponent(sector);
  const detail = useSectorDetail(code);
  const d = detail.data?.sector.code === code ? detail.data : undefined;
  const nSub = d ? d.categories.reduce((n, c) => n + c.children.length, 0) : 0;

  return (
    <>
      <Topbar
        title={d ? `산업 밸류체인 · ${d.sector.name}` : "산업 밸류체인"}
        subtitle={
          d
            ? `대분류 ${d.categories.length} · 중분류 ${nSub} · 기업 ${Object.keys(d.companies).length}${d.sector.desc ? ` — ${d.sector.desc}` : ""}`
            : undefined
        }
        showAccountContext={false}
      />
      <PageContainer wide>
        <Link
          href="/research/valuechain"
          className="mb-3 inline-flex items-center gap-0.5 rounded-md py-0.5 pr-1.5 text-[12.5px] font-bold text-ink-muted transition-colors hover:text-ge-point"
        >
          <ChevronLeft className="h-4 w-4" />
          전체 섹터
        </Link>
        <SectorView code={code} detail={detail} />
      </PageContainer>
    </>
  );
}
