"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { StockMarket, StockMonitor, StockMonitorRow } from "@/lib/api";
import { AxisEditorModal } from "@/components/stock-monitor/axis-editor-modal";
import {
  EMDASH,
  fmtInt,
  fmtPct,
  fmtSigma,
  fmtUsd,
  fmtUsdValue,
  fmtWon,
  moveColor,
  sigmaTone,
} from "@/components/stock-monitor/format";
import { cn } from "@/lib/utils";

// [실시간 차트 표 팝업] — 카드 헤더 클릭으로 뜬다(2026-08-25 사용자 지시: 표를
// 페이지에서 빼고 LP평가의 ETF 카드 팝업처럼). 표 자체는 종전 페이지 표 그대로다.
// 행 클릭 = 그 종목의 5대 축 편집 팝업 — 표가 팝업 뒤로 가면서 축 편집 진입점도
// 여기로 옮겨 왔다(구 차트 스크리닝 헤더 버튼은 기능 은퇴로 함께 사라짐).

// ── 컬럼 헤더 클릭 정렬 ──────────────────────────────────────────────────────
// 값이 있는 컬럼만 클릭을 받는다. 시가총액·산업·실시간 이슈는 원천이 없어 전부 빈 칸이라
// 정렬해도 아무 일이 안 일어난다 — 눌리는데 안 바뀌는 헤더가 제일 헷갈리므로 클릭 자체를
// 안 받는다. 소스가 붙으면 그때 SortTh 로 바꾸면 된다.
type ColKey =
  | "rank"
  | "name"
  | "price"
  | "change_pct"
  | "value"
  | "change_sigma"
  | "volume_z";

type ColSort = { key: ColKey; dir: "asc" | "desc" };

const COL_LABEL: Record<ColKey, string> = {
  rank: "순위",
  name: "종목",
  price: "현재가",
  change_pct: "등락률",
  value: "거래대금",
  change_sigma: "등락 σ",
  volume_z: "거래량 z",
};

// 첫 클릭 방향 — 수치는 큰 값부터(내림차순)가 보고 싶은 것이고, 순위·종목명은 반대다.
const FIRST_DIR: Record<ColKey, "asc" | "desc"> = {
  rank: "asc",
  name: "asc",
  price: "desc",
  change_pct: "desc",
  value: "desc",
  change_sigma: "desc",
  volume_z: "desc",
};

function sortRows(rows: StockMonitorRow[], cs: ColSort | null): StockMonitorRow[] {
  if (!cs) return rows; // 정렬 안 걸림 → 서버가 준 순서(톱바 프리셋) 그대로
  const sign = cs.dir === "asc" ? 1 : -1;
  // ★값이 없는 행은 방향과 상관없이 **항상 뒤**로 보낸다. 오름차순에서 null 을 앞에
  //   세우면 빈 칸만 잔뜩 보이고 정렬한 뜻이 사라진다.
  return [...rows].sort((a, b) => {
    const av = a[cs.key];
    const bv = b[cs.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return sign * (av - bv);
    return sign * String(av).localeCompare(String(bv), "ko");
  });
}

// 클릭 가능한 헤더 한 칸. 화살표 자리는 비활성일 때도 남겨 둬야(opacity-0) 정렬을
// 바꿀 때마다 헤더 폭이 출렁이지 않는다.
function SortTh({
  col,
  label,
  align = "right",
  title,
  colSort,
  onSort,
}: {
  col: ColKey;
  label: string;
  align?: "left" | "right";
  title?: string;
  colSort: ColSort | null;
  onSort: (c: ColKey) => void;
}) {
  const active = colSort?.key === col;
  return (
    <th
      title={title}
      onClick={() => onSort(col)}
      className={cn(
        "cursor-pointer select-none px-2 py-1.5 transition-colors hover:bg-ge-blue-bg",
        align === "right" ? "text-right" : "text-left",
        active && "text-ge-point",
      )}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        <span className={cn("text-[9px]", active ? "opacity-100" : "opacity-0")}>
          {colSort?.dir === "asc" ? "▲" : "▼"}
        </span>
      </span>
    </th>
  );
}

export function StockTableModal({
  data,
  market,
  isLoading,
  isError,
  onClose,
}: {
  data: StockMonitor | undefined;
  market: StockMarket;
  isLoading: boolean;
  isError: boolean;
  onClose: () => void;
}) {
  const [colSort, setColSort] = useState<ColSort | null>(null);
  // 행 클릭 → 그 종목의 5대 축 편집 팝업. ★한국 전용 — 축 파일 키가 한글 이름이라
  // 미장(name=symbol)에는 대응 파일이 없다. 미장 행은 클릭을 아예 안 받는다.
  const [sel, setSel] = useState<{ name: string; symbol: string } | null>(null);
  const isUs = market === "us";

  const rows = sortRows(data?.rows ?? [], colSort);

  // 같은 컬럼을 다시 누르면 방향만 뒤집는다.
  const onSort = (col: ColKey) =>
    setColSort((cur) =>
      cur?.key === col
        ? { key: col, dir: cur.dir === "asc" ? "desc" : "asc" }
        : { key: col, dir: FIRST_DIR[col] },
    );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      {/* ★5대 축 편집 팝업은 이 카드 **안**에 렌더한다 — 카드의 stopPropagation 이
          그 팝업의 배경 클릭까지 삼켜, 축 팝업을 닫는 클릭이 표 팝업까지 같이 닫는
          이중 닫힘을 막는다. fixed 라 화면 배치는 카드 밖과 동일하다. */}
      <div
        className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-canvas shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-extrabold text-ge-navy">
              실시간 급등락 종목 · {isUs ? "미장 실시간 체결" : "KOSPI200 분봉"}
            </h2>
            <div className="mt-0.5 text-[12px] tabular-nums text-ink-muted">
              {data?.asof ?? EMDASH} 기준 · 유니버스 {data?.universe ?? EMDASH}종목 ·
              30초 폴링 · {isUs ? `거래일(ET) ${data?.day ?? EMDASH}` : "행 클릭 = 5대 축 편집"} ·{" "}
              {/* 서버 기본 정렬은 거래대금순(토스 화면과 같다) — 톱바 프리셋 버튼은
                  2026-08-25 제거됐고, 정렬 수단은 컬럼 헤더 클릭 하나다. */}
              {colSort
                ? `${COL_LABEL[colSort.key]} ${colSort.dir === "asc" ? "오름차순" : "내림차순"}`
                : "거래대금순 — 컬럼 헤더 클릭으로 정렬"}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {data?.value_basis ? (
              <span
                title={[data.value_basis, data.change_basis && `등락률: ${data.change_basis}`]
                  .filter(Boolean)
                  .join("\n")}
                className="cursor-help text-[10px] text-slate-400"
              >
                {data.change_basis ? "거래대금·등락률 정의 ⓘ" : "거래대금 정의 ⓘ"}
              </span>
            ) : null}
            <button
              type="button"
              aria-label="닫기"
              onClick={onClose}
              className="rounded-lg p-1.5 text-ink-muted transition hover:bg-canvas-soft hover:text-ink"
            >
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>
        </div>

        <div className="min-h-0 overflow-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead className="sticky top-0 z-10 bg-canvas-soft">
              <tr className="text-[11px] font-semibold text-ink-muted">
                <SortTh col="rank" label="순위" align="left" colSort={colSort} onSort={onSort} />
                <SortTh col="name" label="종목" align="left" colSort={colSort} onSort={onSort} />
                <SortTh col="price" label="현재가" colSort={colSort} onSort={onSort} />
                <SortTh col="change_pct" label="등락률" colSort={colSort} onSort={onSort} />
                <SortTh col="value" label="거래대금" colSort={colSort} onSort={onSort} />
                {/* 원천이 없어 전부 빈 칸인 세 컬럼은 클릭을 안 받는다. */}
                <th className="px-2 py-1.5 text-right">시가총액</th>
                <th className="px-2 py-1.5 text-left">산업</th>
                <th className="px-2 py-1.5 text-left">실시간 이슈</th>
                {/* 이상탐지 재료 — 토스 화면에는 없다. 이 탭의 존재 이유다. */}
                <SortTh
                  col="change_sigma"
                  label="등락 σ"
                  title="등락률 ÷ 그 종목의 일간 σ"
                  colSort={colSort}
                  onSort={onSort}
                />
                <SortTh
                  col="volume_z"
                  label="거래량 z"
                  title="(당일 누적거래량 − 평균) ÷ 표준편차"
                  colSort={colSort}
                  onSort={onSort}
                />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-ink-muted">
                    불러오는 중…
                  </td>
                </tr>
              ) : isError ? (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-rose-600">
                    collector 에 못 닿았습니다.
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-ink-muted">
                    {data?.note ?? "표시할 종목이 없습니다."}
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={isUs ? undefined : () => setSel({ name: r.name, symbol: r.symbol })}
                    className={cn(
                      "border-t border-hairline/60 hover:bg-canvas-soft",
                      !isUs && "cursor-pointer",
                    )}
                  >
                    <td className="px-2 py-1.5 tabular-nums text-ink-muted">{r.rank}</td>
                    <td className="px-2 py-1.5">
                      <span className="font-semibold text-ink">{r.name}</span>
                      {/* 미장은 name=symbol 이라 같은 글자를 두 번 안 적는다 */}
                      {r.name !== r.symbol ? (
                        <span className="ml-1.5 text-[10px] tabular-nums text-slate-400">
                          {r.symbol}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-ink">
                      {isUs ? fmtUsd(r.price) : `${fmtInt(r.price)}원`}
                    </td>
                    <td
                      className={cn(
                        "px-2 py-1.5 text-right font-semibold tabular-nums",
                        moveColor(r.change_pct),
                      )}
                    >
                      {fmtPct(r.change_pct)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-ink">
                      {isUs ? fmtUsdValue(r.value) : fmtWon(r.value)}
                    </td>
                    {/* 원천 없음 — 자리만 둔다 */}
                    <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                      {fmtWon(r.market_cap)}
                    </td>
                    <td className="px-2 py-1.5 text-slate-300">{r.industry ?? EMDASH}</td>
                    <td className="px-2 py-1.5 text-slate-300">{r.issue ?? EMDASH}</td>
                    <td
                      className={cn(
                        "px-2 py-1.5 text-right tabular-nums",
                        sigmaTone(r.change_sigma),
                      )}
                    >
                      {fmtSigma(r.change_sigma)}
                    </td>
                    <td
                      className={cn(
                        "px-2 py-1.5 text-right tabular-nums",
                        sigmaTone(r.volume_z),
                      )}
                    >
                      {fmtSigma(r.volume_z)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {sel ? (
          <AxisEditorModal
            name={sel.name}
            symbol={sel.symbol}
            onClose={() => setSel(null)}
          />
        ) : null}
      </div>
    </div>
  );
}
