"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import { getAiData, type Accelerator, type PackageDownloads } from "@/lib/api";
import { cn } from "@/lib/utils";

// AI Key Data — 가속기와 SDK 채택.
//
// ★이 화면도 collector 프록시라 503 이었다. 공개 데이터로 다시 세웠다 —
//   Epoch AI 의 `ml_hardware.csv` 와 npm 다운로드 API. 둘 다 **키가 없다**.
//
// ★왜 이 두 가지인가. 보유의 47%가 컴퓨팅 인프라(NVDA·AMD·SOXL)다.
//   · 가속기 — 누가 무엇을 얼마나 빠르게 내놓고 있나. NVIDIA 의 비중이 곧 이 시장이다.
//   · SDK 다운로드 — "모델을 실제로 쓰고 있나"의 대리 지표. 매출은 분기에 한 번
//     나오지만 이건 매일 나온다.
//
// ⚠️Epoch 데이터는 가격·성능이 **미공개인 칸이 흔하다**. 비워 둔 채로 둔다 —
//   0 으로 채우면 "무료"나 "성능 0"이라는 틀린 사실이 남는다.

function flops(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e15) return `${(n / 1e15).toFixed(2)} PFLOPS`;
  return `${(n / 1e12).toFixed(0)} TFLOPS`;
}

function perWatt(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n / 1e9).toFixed(0)} GF/W` : "—";
}

function bytes(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e12) return `${(n / 1e12).toFixed(1)} TB`;
  return `${(n / 1e9).toFixed(0)} GB`;
}

function usd(value: string | null): string {
  // ⚠️미공개와 0 달러는 다르다.
  if (value == null) return "미공개";
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}` : "미공개";
}

function pct(value: string | null): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n > 0 ? "+" : ""}${(n * 100).toFixed(1)}%` : "—";
}

export default function AiKeyDataPage() {
  const [picked, setPicked] = useState<Accelerator | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);

  const ai = useQuery({
    queryKey: ["aiData"],
    queryFn: getAiData,
    staleTime: 60 * 60_000,
  });

  const data = ai.data;
  const accelerators = data?.accelerators ?? [];

  const nvidiaShare = useMemo(() => {
    if (!data || data.total_accelerators === 0) return null;
    const nvidia = data.manufacturers.find((m) => m.name === "NVIDIA");
    return nvidia ? nvidia.count / data.total_accelerators : null;
  }, [data]);

  const newest = accelerators[0];
  const topSdk = data?.downloads[0];

  // 성능당 전력이 가장 좋은 것 — 데이터센터가 실제로 따지는 값이다.
  const bestEfficiency = useMemo(() => {
    const scored = accelerators.filter((a) => a.flops_per_watt != null);
    return [...scored].sort(
      (a, b) => Number(b.flops_per_watt) - Number(a.flops_per_watt),
    )[0];
  }, [accelerators]);

  return (
    <>
      <Topbar
        title="AI Key Data"
        subtitle="가속기 · SDK 채택"
        showAccountContext={false}
      />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="AI 가속기"
            value={data ? `${data.total_accelerators}종` : null}
            hint={
              nvidiaShare != null
                ? `NVIDIA ${(nvidiaShare * 100).toFixed(0)}%`
                : "Epoch AI 데이터셋"
            }
            loading={ai.isLoading}
          />
          <StatTile
            label="최신 출시"
            value={newest ? flops(newest.fp16_flops) : null}
            hint={newest ? `${newest.name} · ${newest.release_date}` : "FP16 성능"}
            loading={ai.isLoading}
          />
          <StatTile
            label="최고 전력효율"
            value={bestEfficiency ? perWatt(bestEfficiency.flops_per_watt) : null}
            hint={bestEfficiency ? bestEfficiency.name : "FP16 ÷ TDP"}
            loading={ai.isLoading}
          />
          <StatTile
            label="최다 SDK 다운로드"
            value={topSdk ? `${(topSdk.last_week / 1e6).toFixed(1)}M` : null}
            hint={topSdk ? `${topSdk.label} · 주간 · WoW ${pct(topSdk.week_over_week)}` : "npm 주간"}
            loading={ai.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="AI 가속기"
            subtitle={`최근 출시 ${accelerators.length}종`}
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setSourceOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                출처
              </button>
            }
          >
            {ai.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : accelerators.length === 0 ? (
              <Empty text="가속기 데이터를 받지 못했습니다" />
            ) : (
              <DataTable
                columns={["출시", "제품", "제조사", "FP16", "전력효율"]}
                align={["left", "left", "left", "right", "right"]}
              >
                {accelerators.map((a) => (
                  <tr
                    key={`${a.name}-${a.release_date}`}
                    onClick={() => setPicked(a)}
                    className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                  >
                    <Cell left tone="muted">
                      {a.release_date ?? "—"}
                    </Cell>
                    <Cell left strong>
                      <span className="block max-w-[150px] truncate">{a.name}</span>
                    </Cell>
                    <Cell left tone="muted">
                      {a.manufacturer}
                    </Cell>
                    <Cell strong>{flops(a.fp16_flops)}</Cell>
                    <Cell>{perWatt(a.flops_per_watt)}</Cell>
                  </tr>
                ))}
              </DataTable>
            )}
          </StubCard>

          <StubCard title="AI SDK 채택" subtitle="npm 주간 다운로드" scrollBody>
            {ai.isLoading ? (
              <Empty text="불러오는 중…" />
            ) : (data?.downloads.length ?? 0) === 0 ? (
              <Empty text="다운로드 데이터를 받지 못했습니다" />
            ) : (
              <>
                <p className="mb-2 text-[11px] leading-snug text-ink-muted">
                  절대값보다 추세와 상대 비교로 읽습니다 — CI·미러가 섞입니다.
                </p>
                <SdkBars downloads={data!.downloads} />
              </>
            )}
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.name ?? ""}
        subtitle={
          picked
            ? `${picked.manufacturer}${picked.kind ? ` · ${picked.kind}` : ""}`
            : undefined
        }
      >
        {picked && <AcceleratorDetail item={picked} />}
      </Modal>

      <Modal
        open={sourceOpen}
        onClose={() => setSourceOpen(false)}
        title="출처와 한계"
        subtitle="키 없이 받는 공개 데이터"
      >
        <ul className="space-y-2">
          {(data?.sources ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                {text}
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function SdkBars({ downloads }: { downloads: PackageDownloads[] }) {
  const max = Math.max(...downloads.map((d) => d.last_week), 1);
  return (
    <div className="space-y-2.5">
      {downloads.map((d) => (
        <div key={d.label}>
          <div className="mb-0.5 flex items-baseline justify-between">
            <span className="text-[12px] font-bold text-ge-navy">{d.label}</span>
            <span className="text-[11px] font-bold tabular-nums text-ink-secondary">
              {(d.last_week / 1e6).toFixed(1)}M
              <span
                className={cn(
                  "ml-1.5 font-bold",
                  d.week_over_week == null
                    ? "text-ink-faint"
                    : Number(d.week_over_week) > 0
                      ? "text-bid"
                      : "text-ask",
                )}
              >
                {pct(d.week_over_week)}
              </span>
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft">
            <div
              className="h-full rounded-full bg-ge-point"
              style={{ width: `${(d.last_week / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function AcceleratorDetail({ item }: { item: Accelerator }) {
  const rows: [string, string][] = [
    ["제조사", item.manufacturer],
    ["출시일", item.release_date ?? "—"],
    ["FP16/BF16", flops(item.fp16_flops)],
    ["FP8", flops(item.fp8_flops)],
    ["메모리", bytes(item.memory_bytes)],
    ["메모리 대역폭", item.bandwidth_bytes == null ? "—" : `${bytes(item.bandwidth_bytes)}/s`],
    ["소비전력 (TDP)", item.tdp_watts == null ? "—" : `${Number(item.tdp_watts).toFixed(0)} W`],
    ["전력효율", perWatt(item.flops_per_watt)],
    ["출시가", usd(item.price_usd)],
  ];
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-5 gap-y-0">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between border-b border-hairline py-2"
          >
            <dt className="text-[12px] text-ink-secondary">{label}</dt>
            <dd className="text-[13px] font-bold tabular-nums text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] leading-relaxed text-ink-muted">
        <strong>전력효율</strong>은 FP16 성능 ÷ TDP 입니다 — 데이터센터는 전력과
        면적이 먼저 한계에 걸리므로 절대 성능보다 이 값이 구매 결정을 가릅니다.
        &quot;미공개&quot;는 Epoch 데이터에 값이 없다는 뜻이고, 0 과는 다릅니다.
      </p>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}
