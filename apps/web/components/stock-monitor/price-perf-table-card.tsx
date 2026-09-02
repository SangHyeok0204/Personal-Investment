"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPriceBoard, type PriceBoard, type PriceBoardRow, type PriceCatKey } from "@/lib/api";
import type { PriceSel } from "@/components/stock-monitor/price-tree-card";
import { cn } from "@/lib/utils";

// [시장 성과 표] — 종목 모니터 가운데 4칸. 지표 리스트의 (차트/표) 토글에서 **표**를
// 고르면 차트 대신 여기가 뜬다(사용자 지시 2026-09-01).
//
// ★★형태의 정본은 **회의자료 주간가격모니터 리포트의 `table.perf-table.sortable`**이다
//   (S:\GE\raw\리서치\종합\주간가격모니터\output\dashboard_html_writer.py 의 `_tbody`).
//   열 구성·구분 열 rowspan·색 그라데이션·정렬 3단계까지 그쪽을 그대로 옮겼다.
//   같은 표를 두 곳이 다르게 그리면 회의자료와 대시보드가 어긋난다.
//
// ★★다만 **숫자는 리포트 파일을 읽어 오지 않는다**. 리포트는 실행한 날짜에 고정된
//   산출물이고(최신본이 2026-08-21 자다), 이 화면의 왼쪽 목록·차트는 collector 가
//   price_monitor.xlsx 를 그날그날 읽어 낸 값이다. 표만 리포트에서 떠 오면 같은
//   화면에서 표와 차트의 기준일이 갈린다 — 그래서 **형태만** 가져오고 값은
//   price-board payload(= 목록·차트와 같은 원천, 같은 쿼리)를 쓴다.
//
// 리포트와 다른 점 3가지(의도한 것):
//   1. 암호화폐 Price 를 원화로 환산하지 않는다 — 왼쪽 목록·차트가 달러라 표만
//      원화면 같은 화면에서 두 숫자가 갈린다.
//   2. 글자 크기가 리포트(15.5~15.9px)보다 작다 — 저쪽은 A4 가로 1장 기준이고
//      여기는 화면 4/6칸에 12열을 넣어야 한다.
//   3. 시장명 클릭 모달(3년 종가)이 없다 — 그건 오른쪽 차트가 하는 일이다.

const POLL_MS = 600_000; // 지표 리스트 카드와 같은 주기(같은 쿼리라 실제로는 공유)

// 열 정의 — data-c 는 리포트와 같은 번호다(0=구분, 1=시장, 2=Price, 3~11=수익률).
const VALUE_COLS = [
  { c: 3, key: "dtd", label: "DtoD" },
  { c: 4, key: "wtd", label: "WtD" },
  { c: 5, key: "mtd", label: "MtD" },
  { c: 6, key: "ytd", label: "YtD" },
  { c: 7, key: "r3m", label: "3M" },
  { c: 8, key: "r6m", label: "6M" },
  { c: 9, key: "r1y", label: "1Y" },
  { c: 10, key: "r3y", label: "3Y" },
  { c: 11, key: "r5y", label: "5Y" },
] as const;

type ValueKey = (typeof VALUE_COLS)[number]["key"];

// 구분(Group) 열을 갖는 자산군 — 리포트의 `_fgroups` 와 같다(주식·채권만).
// 원자재는 분류상 layer1(에너지·귀금속…)이 있지만 리포트 표에는 구분 열이 없다.
// 그 묶음은 왼쪽 목록에서 눌러 **하이라이트**로 본다.
const GROUP_HEAD: Partial<Record<PriceCatKey, [string, string]>> = {
  equity: ["Group", "Market"],
  bond: ["구분", "만기"],
};

// ★정렬을 빼는 자산군 — 리포트의 `_NO_SORT_CATS = {"채권"}`. 채권 표는 만기 오름차순
//   자체가 커브라, 수익률로 다시 세우면 커브 모양이 사라진다.
const NO_SORT: PriceCatKey[] = ["bond"];

// ── 제목 띠의 필터 탭 (사용자 지정 2026-09-02) ──────────────────────────────
// ★탭 목록은 **계층이 섞여 있다** — 주식의 벤치마크·DM·EM 은 layer1 이고 한국·중국·
//   미국은 그 아래 layer2 다. 운용역이 실제로 나눠 보는 단위가 그렇게 섞여 있어서
//   (EM 전체도 보고 한국만도 본다), 계층을 맞추려고 목록을 비틀지 않는다.
//   그래서 탭은 "어느 계층인가"가 아니라 **행을 고르는 술어**를 들고 있다.
// ★비트이더는 계층이 아니라 **종목 지정**이다(암호화폐 행은 group 이 전부 빈 문자열).
type FilterTab = { label: string; test?: (r: PriceBoardRow) => boolean };

const ALL: FilterTab = { label: "전체" };
const byGroup = (g: string): FilterTab => ({ label: g, test: (r) => r.group === g });
const bySub = (s: string): FilterTab => ({ label: s, test: (r) => r.sub_group === s });
const byKeys = (label: string, ...ks: string[]): FilterTab => ({
  label,
  test: (r) => ks.includes(r.key),
});

const FILTER_TABS: Record<PriceCatKey, FilterTab[]> = {
  // 벤치마크·DM·EM = layer1 / 한국·중국·미국 = layer2
  equity: [ALL, byGroup("벤치마크"), byGroup("DM"), byGroup("EM"),
           bySub("한국"), bySub("중국"), bySub("미국")],
  bond: [ALL, byGroup("미국"), byGroup("한국"), byGroup("일본"), byGroup("중국")],
  commodity: [ALL, byGroup("에너지"), byGroup("귀금속"), byGroup("산업금속"),
              byGroup("벤치마크")],
  // 환은 5개뿐이라 나눌 것이 없다(사용자 지정) — 띠 모양을 맞추려고 전체 하나만 둔다.
  fx: [ALL],
  crypto: [ALL, byKeys("비트이더", "XBTUSD BGN Curncy", "XETUSD BGN Curncy")],
};

// ── 리포트 `wcolor()` 이식 ──────────────────────────────────────────────────
// |값| 을 10 에서 자르고 연색→진색으로 보간한다. 채권은 값이 bp 라 10bp 만 넘으면
// 곧바로 진한 색이 되는데, 그게 리포트의 동작이다(그대로 둔다).
function wcolor(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "#6B7280"; // C_DGRAY — N/A
  if (v === 0) return "#1F2937"; // C_TEXT
  const t = Math.min(Math.abs(v), 10) / 10;
  const from = v > 0 ? [0xf0, 0xb0, 0xb0] : [0xa8, 0xc0, 0xec];
  const to = v > 0 ? [0xb9, 0x1c, 0x1c] : [0x1d, 0x4e, 0xd8];
  const ch = from.map((f, i) => Math.round(f + (to[i] - f) * t));
  return `#${ch.map((x) => x.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

function fmtPrice(v: number | null, isYield: boolean): string {
  if (v == null || !Number.isFinite(v)) return "N/A";
  const s = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return isYield ? `${s}%` : s;
}

function fmtPct(v: number | null, isYield: boolean): string {
  if (v == null || !Number.isFinite(v)) return "N/A";
  const sign = v > 0 ? "+" : "";
  return isYield ? `${sign}${v.toFixed(1)}bp` : `${sign}${v.toFixed(2)}%`;
}

// 선택된 묶음/지수에 걸리는 행인가. 표 모드에서 왼쪽 목록을 누르면 이 행들만 물든다.
function isHit(r: PriceBoardRow, sel: PriceSel | null): boolean {
  if (!sel) return false;
  if (sel.kind === "leaf") return r.key === sel.key;
  // l2 가 빈 선택(DM·EM 같은 상위 노드)은 그 아래 전부를 문다.
  return r.group === sel.l1 && (sel.l2 === "" || r.sub_group === sel.l2);
}

export function PricePerfTableCard({
  cat,
  sel,
  onPick,
}: {
  cat: PriceCatKey;
  sel: PriceSel | null;
  // 행(시장)을 누르면 그 지수의 차트로 파고든다(사용자 지시 2026-09-02).
  onPick: (key: string) => void;
}) {
  // ★쿼리 키가 지표 리스트·요약 표와 같다 — 셋이 같은 응답을 나눠 쓴다.
  const { data, isLoading, isError } = useQuery<PriceBoard>({
    queryKey: ["price-board", cat],
    queryFn: () => getPriceBoard(cat),
    refetchInterval: POLL_MS,
  });
  const isYield = !!data?.is_yield;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const head = GROUP_HEAD[cat];
  const sortable = !NO_SORT.includes(cat);

  // 정렬 상태 — 리포트와 같은 3단계(오름 → 내림 → 원래 순서). 원래 순서는 분류표
  // 순서(벤치마크→DM→EM, 만기 오름차순)라 되돌릴 값이 있다.
  const [sort, setSort] = useState<{ c: number; dir: 1 | -1 } | null>(null);
  // 제목 띠의 필터 탭 — 인덱스로 들고 있다(0 = 전체).
  const [tab, setTab] = useState(0);
  const tabs = FILTER_TABS[cat] ?? [ALL];
  // ★자산군이 바뀌면 정렬과 필터를 **둘 다** 푼다. 탭 목록이 자산군마다 달라서
  //   인덱스를 그대로 들고 넘어가면 엉뚱한 묶음이 걸린 채로 표가 열린다
  //   (주식 3번 = EM → 채권 3번 = 일본). 정렬도 열 번호는 같아도 뜻이 달라진다.
  const [shownCat, setShownCat] = useState<PriceCatKey>(cat);
  if (shownCat !== cat) {
    setShownCat(cat);
    setSort(null);
    setTab(0);
  }

  const clickHead = (c: number) => {
    if (!sortable) return;
    setSort((prev) =>
      prev?.c !== c ? { c, dir: 1 } : prev.dir === 1 ? { c, dir: -1 } : null,
    );
  };

  // ★순서가 중요하다: **거른 다음 세우고, 그 결과로 병합한다.** 뒤집으면 구분 열
  //   rowspan 이 표에 없는 행까지 세어 병합 수가 어긋난다.
  const shown = useMemo(() => {
    const t = tabs[tab];
    return t?.test ? rows.filter(t.test) : rows;
  }, [rows, tabs, tab]);

  const view = useMemo(() => {
    if (!sort) return shown;
    const val = (r: PriceBoardRow): string | number | null => {
      // ★0열은 자산군에 따라 뜻이 다르다 — 구분 열이 있으면 group, 없으면(원자재·환·
      //   비트코인은 Market 한 칸을 colspan=2 로 쓴다) 화면에 보이는 시장명이다.
      //   group 으로 세우면 표에 없는 값으로 정렬돼 순서가 설명되지 않는다.
      if (sort.c === 0) return (head ? r.group : r.label) || null;
      if (sort.c === 1) return r.label || null;
      if (sort.c === 2) return r.price;
      const col = VALUE_COLS.find((x) => x.c === sort.c);
      return col ? (r[col.key as ValueKey] as number | null) : null;
    };
    return shown.slice().sort((a, b) => {
      const x = val(a);
      const y = val(b);
      // 결측은 방향과 무관하게 항상 뒤로 — 리포트와 같다.
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const d = typeof x === "string" ? x.localeCompare(y as string, "ko") : x - (y as number);
      return sort.dir === 1 ? d : -d;
    });
  }, [shown, sort, head]);

  // 구분 열 rowspan — 같은 group 이 연달아 나오는 만큼 묶는다.
  // ★정렬 중에는 묶지 않는다(리포트의 `unmerge()`). 행 순서가 바뀌면 묶음이 흩어져
  //   rowspan 이 엉뚱한 행을 덮는다.
  const spans = useMemo(() => {
    const m = new Map<number, number | null>();
    if (!head || sort) return m;
    let i = 0;
    while (i < view.length) {
      let n = 1;
      while (i + n < view.length && view[i + n].group === view[i].group) n += 1;
      m.set(i, n);
      for (let k = 1; k < n; k += 1) m.set(i + k, null);
      i += n;
    }
    return m;
  }, [view, head, sort]);

  return (
    // 차트 카드와 같은 칸(2~5번째 열 · 위아래 통) — 토글로 자리를 맞바꾼다.
    <section className="lg:col-span-4 lg:row-span-2 flex min-h-0 flex-col border-r border-hairline bg-canvas">
      {/* ★`items-stretch` + 띠 자체의 세로 padding 제거 — 탭이 띠 높이를 꽉 채워야
          해서다(사용자 지정). 대신 좌우 글자 블록이 각자 py 를 갖는다. 띠에 py 를
          남겨 두면 버튼 위아래로 배경색 띠가 2px 씩 남는다. */}
      <header className="flex shrink-0 items-stretch bg-ge-header">
        <div className="flex shrink-0 items-baseline gap-2 py-1.5 pl-3 pr-2">
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">
            시장 성과 · {data?.cat_label ?? ""}
          </h2>
          <span className="shrink-0 text-[11.5px] font-semibold text-white/70">
            {shown.length === rows.length
              ? `${rows.length}개 시장`
              : `${shown.length} / ${rows.length}개 시장`}
          </span>
        </div>

        {/* 필터 탭 — 버튼끼리 붙이고(gap 0) 사이는 세로 선으로만 가른다.
            폭은 글자수를 따라가되 2글자(전체·DM·EM)가 너무 좁지 않게 바닥을 준다. */}
        <div className="flex shrink-0 items-stretch divide-x divide-white/20 border-x border-white/20">
          {tabs.map((t, i) => (
            <button
              key={t.label}
              type="button"
              onClick={() => setTab(i)}
              aria-pressed={i === tab}
              className={cn(
                "flex min-w-[30px] items-center justify-center px-1.5",
                "text-[11.5px] font-bold leading-none transition-colors",
                i === tab
                  ? "bg-white text-ge-header"
                  : "bg-white/10 text-white/75 hover:bg-white/25",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <span className="ml-auto self-center shrink-0 pr-3 pl-2 text-[11.5px] tabular-nums text-white/60">
          {data?.asof ?? ""} · {isYield ? "bp" : "%"}
        </span>
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : rows.length === 0 ? (
        <Center
          msg={data?.note ?? "price_monitor.xlsx 판독 대기 중입니다."}
          tone={data?.note ? "text-amber-600" : undefined}
        />
      ) : shown.length === 0 ? (
        // 시트에 그 묶음의 열이 아직 하나도 없을 때(신설 직후 등). 빈 표를 그리면
        // "고장났나" 로 읽히므로 왜 비었는지 말한다.
        <Center
          msg={`'${tabs[tab]?.label}' 에 해당하는 시장이 시트에 아직 없습니다.`}
          tone="text-amber-600"
        />
      ) : (
        <div className="pm-perf min-h-0 flex-1 overflow-auto p-2">
          {/* 리포트의 .tbl-wrap — 테두리와 둥근 모서리로 표를 한 덩어리로 묶는다. */}
          <div className="tbl-wrap">
            <table className={cn("perf-table", sortable && "sortable")}>
              <thead>
                <tr>
                  {head ? (
                    <>
                      <Th c={0} label={head[0]} sort={sort} onClick={clickHead} />
                      <Th c={1} label={head[1]} sort={sort} onClick={clickHead} />
                    </>
                  ) : (
                    <Th c={0} label="Market" colSpan={2} sort={sort} onClick={clickHead} />
                  )}
                  <Th c={2} label="Price" sort={sort} onClick={clickHead} />
                  {VALUE_COLS.map((v) => (
                    <Th key={v.c} c={v.c} label={v.label} sort={sort} onClick={clickHead} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {view.map((r, i) => {
                  const hit = isHit(r, sel);
                  const span = spans.get(i);
                  return (
                    <tr
                      key={r.key}
                      data-group={r.group || undefined}
                      className={cn(hit && "is-hit")}
                      onClick={() => onPick(r.key)}
                      title={`${r.label} 추이 차트 열기`}
                    >
                      {head ? (
                        <>
                          {span !== null ? (
                            // ★구분 셀은 클릭에서 뺀다. rowspan 으로 여러 행에 걸쳐
                            //   있어서, 눌리면 '묶음 중 첫 시장'이라는 임의의 행이
                            //   열린다 — 어느 행을 누른 건지 화면상 알 수 없다.
                            <td
                              className="region-cell"
                              data-c="0"
                              rowSpan={span ?? 1}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {r.group}
                            </td>
                          ) : null}
                          <td data-c="1">
                            <span className="mkt-name">{r.label}</span>
                          </td>
                        </>
                      ) : (
                        <td colSpan={2} data-c="0">
                          <span className="mkt-name">{r.label}</span>
                          {r.sub ? <span className="idx-label">{r.sub}</span> : null}
                        </td>
                      )}
                      <td className="price-cell" data-c="2">
                        {fmtPrice(r.price, isYield)}
                      </td>
                      {VALUE_COLS.map((v) => {
                        const val = r[v.key as ValueKey] as number | null;
                        return (
                          <td
                            key={v.c}
                            className="pct-cell"
                            data-c={v.c}
                            style={{ color: wcolor(val) }}
                          >
                            {fmtPct(val, isYield)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-1.5 px-0.5 text-[11px] leading-snug text-slate-400">
            형태는 주간가격모니터 리포트의 성과표 · 값은 왼쪽 목록·차트와 같은
            price_monitor.xlsx 판독분(기준일 {data?.asof ?? "—"})
            {/* 제목 띠에 있던 안내를 여기로 내렸다 — 그 자리를 필터 탭이 가져갔다. */}
            {sortable ? " · 열 제목을 누르면 정렬" : " · 만기 순 고정(정렬 없음)"}
            {" · 행을 누르면 그 시장의 추이 차트"}
            {sel?.kind === "group" ? " · 왼쪽에서 고른 묶음이 강조됩니다" : ""}
          </div>
        </div>
      )}

      {/* 리포트(dashboard_html_writer.py)의 .perf-table 규칙 이식.
          ★`.pm-perf` 로 스코프를 판다 — perf-table·pct-cell 같은 이름이 흔해서
            전역에 풀면 다른 화면의 표에 얹힐 수 있다. */}
      <style>{`
/* ★리포트의 .tbl-wrap 은 overflow:hidden 으로 모서리를 잘라내는데, 여기서는 뺐다 —
   (이 블록은 JS 템플릿 리터럴 안이라 역따옴표를 쓸 수 없다)
   그걸 두면 이 상자가 스크롤 컨테이너가 되어 **thead 의 position:sticky 가 죽는다**
   (sticky 는 가장 가까운 스크롤 조상 기준인데, 그 조상이 스크롤을 안 하므로 그냥
   같이 밀려 올라간다). 리포트는 인쇄물이라 스크롤이 없었고 여기는 44행이 한 칸에서
   스크롤된다 — 열 이름이 붙어 있어야 표를 읽을 수 있다. */
.pm-perf .tbl-wrap{ border:1px solid #DDE2E8; border-radius:12px; background:#FFFFFF; }
.pm-perf .perf-table{ width:100%; border-collapse:collapse; font-size:13px; }
/* ★sticky + border-collapse 는 조합이 나쁘다(고정된 th 의 테두리가 스크롤에 남지
   않는다) → 아래쪽 경계선만 box-shadow 로 한 번 더 긋는다. */
.pm-perf .perf-table th{ background:#EEF2F7; color:#5A6573; font-weight:800; text-align:center;
  border:1px solid #DDE2E8; padding:6px 4px; position:sticky; top:0; z-index:2;
  box-shadow:0 1px 0 #DDE2E8; }
.pm-perf .perf-table td{ border:1px solid #EAEDF1; line-height:1.3; padding:4px 5px; }
.pm-perf .perf-table .region-cell{ font-weight:800; color:#4A7AB5; text-align:center;
  vertical-align:middle; background:#fff; font-size:12px; white-space:nowrap; }
.pm-perf .perf-table .mkt-name{ font-weight:700; }
.pm-perf .perf-table .idx-label{ color:#8A94A6; margin-left:3px; font-size:11px; }
.pm-perf .perf-table .price-cell{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.pm-perf .perf-table .pct-cell{ text-align:right; font-weight:bold; font-variant-numeric:tabular-nums; white-space:nowrap; }
.pm-perf .perf-table.sortable th{ cursor:pointer; user-select:none; }
.pm-perf .perf-table.sortable th:hover{ background:#E2E9F3; }
.pm-perf .perf-table.sortable th[data-sort="asc"]::after{ content:' ▲'; font-size:.8em; }
.pm-perf .perf-table.sortable th[data-sort="desc"]::after{ content:' ▼'; font-size:.8em; }
/* 왼쪽 목록에서 고른 묶음 — 리포트에는 없는 이 화면 전용 표시(사용자 지시 2026-09-01).
   글자색이 값의 부호를 나타내므로 배경만 건드린다. */
.pm-perf .perf-table tr.is-hit td{ background:#E7F0FB; }
.pm-perf .perf-table tr.is-hit .region-cell{ background:#D8E7FA; }
.pm-perf .perf-table tr.is-hit .mkt-name{ color:#243B5E; }
/* 행 hover — 누르면 그 시장의 차트가 열린다는 신호(사용자 지시 2026-09-02).
   ★강조된 행(.is-hit) 위에서도 hover 가 보여야 해서 선택자를 하나 더 쓴다.
     안 그러면 .is-hit 쪽 명시도가 높아 hover 가 통째로 묻힌다. */
.pm-perf .perf-table tbody tr{ cursor:pointer; }
.pm-perf .perf-table tbody tr:hover td,
.pm-perf .perf-table tbody tr.is-hit:hover td{ background:#DCE9FA; }
.pm-perf .perf-table tbody tr:hover .mkt-name{ color:#243B5E; text-decoration:underline; }
/* 구분 셀만 예외 — 여러 행이 공유하므로 한 행에 커서를 올렸다고 같이 물들면 거짓말이다. */
.pm-perf .perf-table tbody tr:hover .region-cell{ background:#fff; cursor:default; }
.pm-perf .perf-table tbody tr.is-hit:hover .region-cell{ background:#D8E7FA; }
`}</style>
    </section>
  );
}

function Th({
  c,
  label,
  colSpan,
  sort,
  onClick,
}: {
  c: number;
  label: string;
  colSpan?: number;
  sort: { c: number; dir: 1 | -1 } | null;
  onClick: (c: number) => void;
}) {
  return (
    <th
      data-c={c}
      colSpan={colSpan}
      data-sort={sort?.c === c ? (sort.dir === 1 ? "asc" : "desc") : undefined}
      onClick={() => onClick(c)}
    >
      {label}
    </th>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
      <span className={cn("text-[12.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
