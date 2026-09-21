"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import { getMarketMonitor, type MarketRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// 시장 지표 — DailyPriceAgent 의 주간가격모니터를 흡수한 화면.
//
// ★원본은 블룸버그에서 받았는데 지금 블룸버그를 쓸 수 없어 야후로 다시 세웠다.
//   대상 목록의 정본은 `database/seeds/market_universe.py` 다.
//
// ★**단위가 셋이다.** 전부 "수익률"로 묶으면 화면이 틀린 말을 한다.
//   · price → %      (지수·환율·원자재·크립토)
//   · rate  → bp     (국채금리. 4.96 → 5.06 은 "+2%" 가 아니라 "+10bp")
//   · level → 포인트 (VIX. bp 관례가 없다)
//
// ⚠️출처를 못 찾아 비워 둔 항목은 숨기지 않고 각주로 띄운다 — "왜 이건 없지?"를
//   사용자가 묻기 전에 먼저 답해 둔다.

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

// ★주식은 11개로 가장 많은데 다른 칸과 같은 높이면 6개가 잘려 스크롤에 묻힌다.
//   3열 x 2행 = 6칸인데 분류는 5개라 한 칸이 비기도 했다 — 주식에 2행을 줘서
//   빈칸을 없애고 목록도 다 보이게 한다.
const TALL_CATEGORY = "주식";

export default function MarketPage() {
  const [picked, setPicked] = useState<MarketRow | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);

  const monitor = useQuery({
    queryKey: ["marketMonitor"],
    queryFn: getMarketMonitor,
    // 서버가 5분 캐시를 들고 있다. 화면도 같은 호흡으로 둔다 —
    // 시장 지표는 초 단위로 볼 값이 아니다.
    staleTime: 60_000,
    refetchInterval: 300_000,
  });

  const rows = monitor.data?.rows ?? [];
  const byCategory = useMemo(() => {
    const map = new Map<string, MarketRow[]>();
    for (const r of rows) {
      const list = map.get(r.category) ?? [];
      list.push(r);
      map.set(r.category, list);
    }
    return map;
  }, [rows]);

  // 오늘 가장 크게 움직인 것 — 방향 무관.
  const mover = useMemo(() => {
    const price = rows.filter((r) => r.kind === "price" && r.changes["1D"] != null);
    return [...price].sort(
      (a, b) => Math.abs(Number(b.changes["1D"])) - Math.abs(Number(a.changes["1D"])),
    )[0];
  }, [rows]);

  const find = (name: string) => rows.find((r) => r.name === name);
  const sox = find("필라델피아 반도체");
  const tnx = find("미국 10년 국채");
  const krw = find("USD/KRW");

  return (
    <>
      <Topbar
        title="시장 지표"
        subtitle="지수 · 금리 · 환율 · 원자재 · 크립토"
        showAccountContext={false}
      />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="필라델피아 반도체"
            value={sox ? delta(sox, "1D") : null}
            hint={sox ? `YTD ${delta(sox, "YTD")} · 보유 비중과 직결` : "반도체"}
            accent="auto"
            loading={monitor.isLoading}
          />
          <StatTile
            label="미국 10년 국채"
            value={tnx ? `${Number(tnx.price).toFixed(2)}%` : null}
            hint={tnx ? `1D ${delta(tnx, "1D")} · YTD ${delta(tnx, "YTD")}` : "금리"}
            loading={monitor.isLoading}
          />
          <StatTile
            label="USD/KRW"
            value={krw ? level(krw) : null}
            hint={krw ? `1D ${delta(krw, "1D")} · 해외주식 평가액에 직결` : "환율"}
            accent="auto"
            loading={monitor.isLoading}
          />
          <StatTile
            label="오늘 최대 변동"
            value={mover ? delta(mover, "1D") : null}
            hint={mover ? mover.name : "—"}
            accent="auto"
            loading={monitor.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:grid-cols-3 lg:grid-rows-2 lg:auto-rows-auto",
          )}
        >
          {(monitor.data?.categories ?? []).map((category, index) => {
            const list = byCategory.get(category) ?? [];
            if (list.length === 0) return null;
            return (
              <StubCard
                key={category}
                title={category}
                subtitle={`${list.length}개`}
                scrollBody
                className={cn(category === TALL_CATEGORY && "lg:row-span-2")}
                // 마지막 칸에 각주 버튼을 붙인다 — 별도 카드를 만들 자리가 없다.
                action={
                  index === 0 ? (
                    <button
                      type="button"
                      onClick={() => setNotesOpen(true)}
                      className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
                    >
                      출처 한계
                    </button>
                  ) : undefined
                }
              >
                <DataTable
                  columns={["지표", "현재", "1D", "YTD"]}
                  align={["left", "right", "right", "right"]}
                  empty={monitor.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
                >
                  {list.map((r) => (
                    <tr
                      key={r.symbol}
                      onClick={() => setPicked(r)}
                      className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                    >
                      <Cell left strong>
                        <span className="block max-w-[140px] truncate">{r.name}</span>
                      </Cell>
                      <Cell>{level(r)}</Cell>
                      <Cell tone={tone(r, "1D")}>{delta(r, "1D")}</Cell>
                      <Cell tone={tone(r, "YTD")}>{delta(r, "YTD")}</Cell>
                    </tr>
                  ))}
                </DataTable>
              </StubCard>
            );
          })}
        </div>
      </PageContainer>

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
        subtitle="블룸버그에만 있던 것들 — 억지로 대체하지 않았다"
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
        <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
          이름만 같고 내용이 다른 값을 채워 넣으면 빈칸보다 나쁩니다. 출처를 찾기
          전까지는 비워 둡니다.
          {(monitor.data?.missing.length ?? 0) > 0 && (
            <>
              {" "}
              이번 조회에서 못 받은 지표: {monitor.data?.missing.join(", ")}.
            </>
          )}
        </p>
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
        단위는 <strong>{unit}</strong> 입니다.
        {row.kind === "rate" && (
          <> 금리는 수준이라 퍼센트 수익률로 적으면 의미가 달라집니다 — 4.96 → 5.06 은 &quot;+2%&quot; 가 아니라 &quot;+10bp&quot; 입니다.</>
        )}
        {row.kind === "level" && (
          <> VIX 는 bp 관례가 없어 포인트로 적습니다.</>
        )}
        {row.as_of && <> 최근 데이터 기준일 {row.as_of}.</>}
      </p>
    </div>
  );
}
