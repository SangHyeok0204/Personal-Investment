"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import {
  Cell,
  DataTable,
  HeaderChip,
  SourceDownBanner,
  StubCard,
} from "@/components/stub";
import { getMarketMonitor, type MarketRow } from "@/lib/api";

// 시장 리서치 · 시장지표 탭 — DailyPriceAgent 의 주간가격모니터를 흡수한 화면.
//
// ★2026-09-27 계획 S3(§3.2): 분류 카드 그리드 → **분류 서브탭 + 컴팩트 표**.
//   행을 누르면 기간별 변화 팝업(예전 그대로). '출처 한계'는 탭 줄 끝 작은 아이콘.
//   VIX 는 seed(`database/seeds/market_universe.py`)에서 "주식"으로 옮겼다.
//
// ★원본은 블룸버그에서 받았는데 지금 블룸버그를 쓸 수 없어 야후로 다시 세웠다.
//   대상 목록의 정본은 `database/seeds/market_universe.py` 다.
//
// ★**단위가 셋이다.** 전부 "수익률"로 묶으면 화면이 틀린 말을 한다.
//   · price → %      (지수·환율·원자재·크립토)
//   · rate  → bp     (국채금리. 4.96 → 5.06 은 "+2%" 가 아니라 "+10bp")
//   · level → 포인트 (VIX. bp 관례가 없다)

/** 서버 분류명 → 탭 이름. 없는 건 분류명 그대로. */
const CATEGORY_LABEL: Record<string, string> = { 금리: "금리·채권" };

/** 표의 기간 순서. 서버가 주는 기간 중 여기 있는 것만, 이 순서로. */
const PERIOD_ORDER = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"];

/** kind 에 맞는 단위로 변화를 적는다. 여기가 이 화면의 핵심이다. */
function delta(row: MarketRow, period: string): string {
  const raw = row.changes[period];
  if (raw == null) return "—";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  if (row.kind === "rate") return `${sign}${n.toFixed(1)}bp`;
  if (row.kind === "level") return `${sign}${n.toFixed(2)}p`;
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function tone(row: MarketRow, period: string): "up" | "down" | undefined {
  const raw = row.changes[period];
  if (raw == null) return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n) || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

function level(row: MarketRow): string {
  if (row.price == null) return "—";
  const n = Number(row.price);
  if (!Number.isFinite(n)) return "—";
  // 금리·VIX 는 소수 둘째 자리까지. 지수는 자릿수가 커서 정수부만으로 충분하다.
  const digits = row.kind === "price" ? (n < 10 ? 4 : 2) : 2;
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function MarketTab() {
  const [picked, setPicked] = useState<MarketRow | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [category, setCategory] = useState<string | null>(null);

  const monitor = useQuery({
    queryKey: ["marketMonitor"],
    queryFn: getMarketMonitor,
    // 서버가 5분 캐시를 들고 있다. 화면도 같은 호흡으로 둔다.
    staleTime: 60_000,
    refetchInterval: 300_000,
  });

  const rows = useMemo(() => monitor.data?.rows ?? [], [monitor.data]);
  // 한 줄도 못 받았는데 '못 받은 목록'만 가득하면 원천이 죽은 것이다.
  const sourceDown =
    !monitor.isLoading &&
    rows.length === 0 &&
    (monitor.isError || (monitor.data?.missing.length ?? 0) > 0);

  const categories = (monitor.data?.categories ?? []).filter((c) =>
    rows.some((r) => r.category === c),
  );
  const active = category && categories.includes(category) ? category : categories[0];
  const activeRows = rows.filter((r) => r.category === active);
  const available = monitor.data?.periods ?? [];
  const periods = PERIOD_ORDER.filter((p) => available.includes(p));
  const missingCount = monitor.data?.missing_sources.length ?? 0;

  return (
    <>
      {sourceDown && (
        <SourceDownBanner
          source="야후 파이낸스"
          detail="지수·환율·원자재 시세 원천입니다."
        />
      )}

      <StubCard
        title="시장 지표"
        subtitle={active ? `${activeRows.length}개 · 행을 누르면 기간별 변화` : undefined}
        className="flex-1"
        scrollBody
        action={
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {categories.map((c) => (
                <HeaderChip key={c} active={c === active} onClick={() => setCategory(c)}>
                  {CATEGORY_LABEL[c] ?? c}
                </HeaderChip>
              ))}
            </div>
            {categories.length > 0 && (
              <>
                <span className="h-3 w-px bg-white/25" />
                <button
                  type="button"
                  onClick={() => setNotesOpen(true)}
                  title={[
                    "출처 한계 — 블룸버그에만 있던 것들(억지로 대체하지 않았다)",
                    ...(monitor.data?.missing_sources ?? []).map((t) => `· ${t}`),
                  ].join("\n")}
                  className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[10px] font-bold text-white/60 transition-colors hover:bg-white/15 hover:text-white"
                >
                  <Info className="h-3 w-3" strokeWidth={2.5} />
                  출처 한계 {missingCount}
                </button>
              </>
            )}
          </div>
        }
      >
        <DataTable
          columns={["지표", "현재", ...periods]}
          align={["left", "right", ...periods.map(() => "right" as const)]}
          empty={monitor.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
        >
          {activeRows.map((r) => (
            <tr
              key={r.symbol}
              onClick={() => setPicked(r)}
              className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
            >
              <Cell left strong className="py-1.5">
                <span className="block max-w-[200px] truncate" title={r.note ?? undefined}>
                  {r.name}
                </span>
              </Cell>
              <Cell strong className="py-1.5">
                {level(r)}
              </Cell>
              {periods.map((p) => (
                <Cell key={p} tone={tone(r, p)} className="py-1.5">
                  {delta(r, p)}
                </Cell>
              ))}
            </tr>
          ))}
        </DataTable>
        <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">
          단위: 지수·환율·원자재·크립토 <strong>%</strong> · 국채금리{" "}
          <strong>bp</strong> · VIX <strong>포인트</strong>
          {(monitor.data?.missing.length ?? 0) > 0 && (
            <> · 못 받은 지표: {monitor.data?.missing.join(", ")}</>
          )}
        </p>
      </StubCard>

      <Modal
        open={picked != null}
        onClose={() => setPicked(null)}
        title={picked?.name ?? ""}
        subtitle={picked ? `${picked.symbol}${picked.note ? ` · ${picked.note}` : ""}` : undefined}
      >
        {picked && <RowDetail row={picked} periods={monitor.data?.periods ?? []} />}
      </Modal>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="출처 한계"
        subtitle="블룸버그에만 있던 것들"
      >
        <ul className="space-y-2">
          {(monitor.data?.missing_sources ?? []).map((text) => (
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

function RowDetail({ row, periods }: { row: MarketRow; periods: string[] }) {
  const unit =
    row.kind === "rate" ? "bp (금리 수준의 차이)" : row.kind === "level" ? "포인트" : "%";
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">현재</span>
        <span className="text-[20px] font-extrabold tabular-nums text-ink">
          {level(row)}
          {row.currency && row.kind === "price" && (
            <span className="ml-1.5 text-[12px] font-bold text-ink-muted">
              {row.currency}
            </span>
          )}
        </span>
      </div>

      <DataTable columns={["기간", "변화"]} align={["left", "right"]}>
        {periods.map((p) => (
          <tr key={p} className="border-b border-hairline">
            <Cell left strong>
              {p}
            </Cell>
            <Cell tone={tone(row, p)}>{delta(row, p)}</Cell>
          </tr>
        ))}
      </DataTable>

      <p className="text-[11px] leading-relaxed text-ink-muted">
        단위 <strong>{unit}</strong>
        {row.kind === "rate" && (
          <> · 변화 bp</>
        )}
        {row.kind === "level" && (
          <> · 변화 포인트</>
        )}
        {row.as_of && <> 최근 데이터 기준일 {row.as_of}.</>}
      </p>
    </div>
  );
}
