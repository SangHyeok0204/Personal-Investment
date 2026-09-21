"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, StatTile, StubCard } from "@/components/stub";
import { getMacro, type MacroRow } from "@/lib/api";
import { cn } from "@/lib/utils";

// 매크로 지표 — 물가 · 고용 · 금리 · 성장.
//
// ★이 화면은 원래 원본 GE 의 collector 를 프록시했는데 이 환경에는 collector 가
//   없어 503 이었다. FRED 로 다시 세웠다 — 외부 의존이 FRED 뿐이라 그 자체로 산다.
//
// ★**FRED 를 키 없이 쓴다.** API(api.stlouisfed.org)는 api_key 가 없으면 400 이지만,
//   그래프 CSV 내보내기(fred.stlouisfed.org/graph/fredgraph.csv)는 키 없이 200 이다.
//
// ★지표마다 **읽는 방식이 다르다.** 전부 같은 방식으로 보여 주면 틀린 말이 된다.
//   · level    값 자체        실업률 4.1%
//   · yoy      전년 대비 변화율  CPI 332.8 이 아니라 "+3.35%"
//   · mom_diff 전월 대비 증감   비농업고용 158,913 이 아니라 "+16.2만명"
//
// ⚠️CPI·고용은 발표가 한 달 이상 늦다. 각 줄에 **기준일**을 붙인다 — 안 붙이면
//   "오늘 물가"로 오인된다.

/** 지표의 본래 값을 그 지표의 단위로 적는다. */
function value(r: MacroRow): string {
  if (r.value == null) return "—";
  const n = Number(r.value);
  if (!Number.isFinite(n)) return "—";
  if (r.transform === "yoy") return `${n > 0 ? "+" : ""}${(n * 100).toFixed(2)}%`;
  if (r.transform === "mom_diff") {
    // 천명 단위는 만명으로 바꿔 적는다 — "+162천명"보다 "+16.2만명"이 읽힌다.
    if (r.unit === "천명") return `${n > 0 ? "+" : ""}${(n / 10).toFixed(1)}만명`;
    return `${n > 0 ? "+" : ""}${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  const digits = r.unit === "건" ? 0 : 2;
  return `${n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}${r.unit === "건" ? "건" : r.unit}`;
}

/** 기간 변화. yoy 는 %p, 퍼센트 수준은 bp, 나머지는 원 단위 차이. */
function delta(r: MacroRow, period: string): string {
  const raw = r.changes[period];
  if (raw == null) return "—";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  if (r.transform === "yoy") return `${sign}${(n * 100).toFixed(2)}%p`;
  if (r.transform === "mom_diff") {
    if (r.unit === "천명") return `${sign}${(n / 10).toFixed(1)}만`;
    return `${sign}${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  if (r.unit === "%" || r.unit === "%p") return `${sign}${(n * 100).toFixed(0)}bp`;
  return `${sign}${n.toLocaleString("en-US", { maximumFractionDigits: 1 })}`;
}

function tone(r: MacroRow, period: string): "up" | "down" | undefined {
  const raw = r.changes[period];
  if (raw == null) return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n) || n === 0) return undefined;
  // ⚠️여기서 '좋다/나쁘다'를 칠하지 않는다. 물가 상승은 빨강이 맞지만 고용
  //   증가도 빨강이 되면 색이 의미를 잃는다. 방향만 표시한다.
  return n > 0 ? "up" : "down";
}

export default function MacroPage() {
  const [picked, setPicked] = useState<MacroRow | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);

  const macro = useQuery({
    queryKey: ["macro"],
    queryFn: getMacro,
    // 월간 발표가 대부분이다. 서버도 1시간 캐시를 들고 있다.
    staleTime: 10 * 60_000,
    refetchInterval: 60 * 60_000,
  });

  const rows = macro.data?.rows ?? [];
  const byCategory = useMemo(() => {
    const map = new Map<string, MacroRow[]>();
    for (const r of rows) {
      const list = map.get(r.category) ?? [];
      list.push(r);
      map.set(r.category, list);
    }
    return map;
  }, [rows]);

  const find = (id: string) => rows.find((r) => r.series_id === id);
  const cpi = find("CPIAUCSL");
  const unrate = find("UNRATE");
  const spread = find("T10Y2Y");
  const payems = find("PAYEMS");

  return (
    <>
      <Topbar
        title="매크로"
        subtitle="물가 · 고용 · 금리 · 성장 (FRED)"
        showAccountContext={false}
      />
      <PageContainer fit>
        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="소비자물가 (전년 대비)"
            value={cpi ? value(cpi) : null}
            hint={cpi ? `1Y ${delta(cpi, "1Y")} · ${cpi.as_of} 기준` : "CPI"}
            accent="auto"
            loading={macro.isLoading}
          />
          <StatTile
            label="실업률"
            value={unrate ? value(unrate) : null}
            hint={unrate ? `1Y ${delta(unrate, "1Y")} · ${unrate.as_of} 기준` : "고용"}
            loading={macro.isLoading}
          />
          <StatTile
            label="비농업 고용"
            value={payems ? value(payems) : null}
            hint={payems ? `전월 대비 · ${payems.as_of} 기준` : "고용"}
            accent="auto"
            loading={macro.isLoading}
          />
          <StatTile
            label="장단기 금리차 (10Y-2Y)"
            value={spread ? value(spread) : null}
            hint={
              spread
                ? `${Number(spread.value) < 0 ? "역전 상태" : "정상"} · ${spread.as_of} 기준`
                : "금리"
            }
            accent="auto"
            loading={macro.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:grid-cols-4 lg:auto-rows-auto",
          )}
        >
          {(macro.data?.categories ?? []).map((category, index) => {
            const list = byCategory.get(category) ?? [];
            if (list.length === 0) return null;
            return (
              <StubCard
                key={category}
                title={category}
                subtitle={`${list.length}개`}
                scrollBody
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
                  columns={["지표", "값", "1Y"]}
                  align={["left", "right", "right"]}
                  empty={macro.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
                >
                  {list.map((r) => (
                    <tr
                      key={r.series_id}
                      onClick={() => setPicked(r)}
                      className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
                    >
                      <Cell left strong>
                        <span className="block max-w-[120px] truncate">{r.name}</span>
                        {/* 발표 지연이 있는 지표가 많다 — 기준일을 줄마다 붙인다. */}
                        <span className="block text-[10px] font-medium text-ink-faint">
                          {r.as_of}
                        </span>
                      </Cell>
                      <Cell strong>{value(r)}</Cell>
                      <Cell tone={tone(r, "1Y")}>{delta(r, "1Y")}</Cell>
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
        subtitle={
          picked
            ? `${picked.series_id}${picked.note ? ` · ${picked.note}` : ""}`
            : undefined
        }
      >
        {picked && <RowDetail row={picked} periods={macro.data?.periods ?? []} />}
      </Modal>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="출처 한계"
        subtitle="FRED 로 받을 수 없거나 넣지 않은 것"
      >
        <ul className="space-y-2">
          {(macro.data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                {text}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
          FRED 는 <strong>키 없이</strong> 받습니다 — API 는 api_key 를 요구하지만
          그래프 CSV 내보내기는 그렇지 않습니다.
          {(macro.data?.missing.length ?? 0) > 0 && (
            <> 이번 조회에서 못 받은 지표: {macro.data?.missing.join(", ")}.</>
          )}
        </p>
      </Modal>
    </>
  );
}

function RowDetail({ row, periods }: { row: MacroRow; periods: string[] }) {
  const how =
    row.transform === "yoy"
      ? "전년 대비 변화율"
      : row.transform === "mom_diff"
        ? "전월 대비 증감"
        : "값 자체";
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-[12px] text-ink-secondary">{how}</span>
        <span className="text-[20px] font-extrabold tabular-nums text-ink">
          {value(row)}
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
        이 지표는 <strong>{how}</strong>로 읽습니다.
        {row.transform === "yoy" && (
          <> 지수 자체(예: CPI 332.8)는 의미가 없고 전년 대비가 의미입니다. 표의 변화는 그 상승률이 몇 %p 움직였는지입니다 — 물가가 몇 % 올랐는지가 아닙니다.</>
        )}
        {row.transform === "mom_diff" && (
          <> 누적 수치라 총량이 아니라 증감이 뉴스가 됩니다.</>
        )}
        {row.as_of && (
          <>
            {" "}
            최신 관측 기준일은 <strong>{row.as_of}</strong> 입니다 — 물가·고용은
            발표가 한 달 이상 늦습니다.
          </>
        )}
      </p>
    </div>
  );
}
