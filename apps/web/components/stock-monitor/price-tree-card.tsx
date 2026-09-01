"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, LineChart, Table2 } from "lucide-react";
import {
  getPriceBoard,
  type PriceBoard,
  type PriceCatKey,
  type PriceTreeNode,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// [지표 리스트] — 종목 모니터 좌측 1칸 × 2행. 참조 화면(주간가격모니터.png)의 왼쪽
// 목록 패널에 해당한다. 상단 자산군 탭 → 계층 트리 → 지수 클릭 = 오른쪽 차트 전환.
//
// 계층(사용자 지시 2026-08-28): 자산군(탭) → layer1(벤치마크·DM·EM) →
//   layer2(DM: 미국·유럽·일본싱가포르·그외 / EM: 한국·중국·홍콩·그외) → 실제 지수.
//   벤치마크처럼 layer2 가 없는 가지는 지수가 바로 붙는다. 환·비트코인은 계층 자체가
//   없어 지수가 최상단에 온다 — 트리는 payload 모양을 그대로 따라 그린다.
// ★기본 펼침은 **layer1 까지**. 42개를 다 펼치면 1칸 폭에서 스크롤만 길어진다.
//
// ★글자 크기는 2026-08-31 사용자 지시로 한 단계씩 키웠다(지수 11→13.5px, DtD 10→12.5px,
//   탭 10.5→12.5px, 제목 12.5→15px). **한 군데만 키우면 위계가 깨지므로 같이 움직인다** —
//   묶음(node)과 지수(leaf)는 같은 크기에 굵기로만 갈리고, 오른쪽 DtD 는 이름보다
//   한 단계 작아야 이름이 먼저 읽힌다. 들여쓰기(9→11px)도 같이 키워야 계층이 안 뭉갠다.
//   행이 22→30px 로 높아져 전부 펼치면 스크롤이 생기는데, 목록은 이미 스크롤 컨테이너다.
//
// ★★2026-08-28 사용자 지시: **묶음도 클릭 대상**이다. 미국·유럽처럼 자식이 전부
//   지수인 노드를 누르면 펼쳐지는 동시에 오른쪽 차트가 그 묶음 전체를 겹쳐 그린다.
//   자식이 또 노드인 DM·EM 은 펼치기만 한다 — 25개를 한 차트에 겹치면 스파게티다.

const POLL_MS = 600_000;

// 차트가 무엇을 그릴지 정하는 선택 상태. 지수 하나(leaf) 또는 묶음(group).
export type PriceSel =
  | { kind: "leaf"; key: string }
  | { kind: "group"; l1: string; l2: string; label: string };

// 오른쪽 큰 칸이 무엇을 그리는가(사용자 지시 2026-09-01). 토글은 이 카드의 자산군 탭
// 오른쪽에 둔다 — 고르는 곳과 보는 곳이 떨어져 있으면 눈이 왕복한다.
//  · chart = 지금까지의 동작. 지수·묶음을 누르면 오른쪽에 그 시계열이 그려진다.
//  · table = 회의자료 리포트의 성과표. 자산군 탭이 곧 표이고, 목록 클릭은 그 행을
//            **물들이기만** 한다(표가 이미 전 시장을 보여 주므로 그릴 것이 없다).
export type PriceView = "chart" | "table";

function tone(v: number | null): string {
  if (v == null || !Number.isFinite(v) || v === 0) return "text-ink-muted";
  return v > 0 ? "text-rose-600" : "text-blue-600";
}

function fmtChg(v: number | null, isYield: boolean): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v > 0 ? "+" : "";
  return isYield ? `${s}${v.toFixed(1)}` : `${s}${v.toFixed(1)}`;
}

function Leaf({
  node,
  depth,
  active,
  isYield,
  onSelect,
}: {
  node: Extract<PriceTreeNode, { type: "leaf" }>;
  depth: number;
  active: boolean;
  isYield: boolean;
  onSelect: (sel: PriceSel) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect({ kind: "leaf", key: node.key })}
      title={`${node.label}${node.sub ? ` · ${node.sub}` : ""} — ${node.price.toLocaleString("en-US")} (${node.asof})`}
      className={cn(
        "flex w-full items-baseline gap-1.5 rounded py-[5px] pr-1.5 text-left transition-colors",
        active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
      )}
      style={{ paddingLeft: 7 + depth * 11 }}
    >
      <span
        className={cn(
          "min-w-0 flex-1 truncate text-[13.5px]",
          active ? "font-extrabold text-ge-point" : "font-semibold text-ink",
        )}
      >
        {node.label}
      </span>
      {/* 목록에는 DtD 하나만 — 나머지 셋은 오른쪽 차트가 시계열로 보여준다. */}
      <span className={cn("shrink-0 text-[12.5px] font-bold tabular-nums", tone(node.dtd))}>
        {fmtChg(node.dtd, isYield)}
      </span>
    </button>
  );
}

function Node({
  node,
  depth,
  open,
  onToggle,
  ...rest
}: {
  node: Extract<PriceTreeNode, { type: "node" }>;
  depth: number;
  open: Set<string>;
  onToggle: (path: string) => void;
  path: string;
  active: PriceSel | null;
  isYield: boolean;
  view: PriceView;
  onSelect: (sel: PriceSel) => void;
}) {
  const path = `${rest.path}/${node.label}`;
  const isOpen = open.has(path);

  // 자식이 전부 지수여야 "묶음"으로 고를 수 있다. DM·EM 처럼 자식이 또 노드면
  // 펼치기 전용 — 하위 묶음 중 어느 것을 그릴지 스스로 정할 수 없다.
  const leafOnly = node.children.every((c) => c.type === "leaf");
  // ★표 모드에서는 **모든 노드**가 고를 수 있다(사용자 지시 2026-09-01). 차트에서
  //   DM·EM 을 막았던 이유는 25개를 한 차트에 겹치면 스파게티가 되기 때문인데,
  //   표에서는 고른다 = 물들인다라서 겹칠 것이 없다. DM 전체를 물들이는 게 오히려
  //   이 모드의 주 용도다.
  const selectable = leafOnly || rest.view === "table";
  const parts = path.split("/").filter(Boolean);
  const l1 = parts[0] ?? "";
  const l2 = parts.length > 1 ? parts[parts.length - 1] : "";
  const active =
    rest.active?.kind === "group" &&
    rest.active.l1 === l1 &&
    rest.active.l2 === l2;

  return (
    <div>
      <button
        type="button"
        onClick={() => {
          // 펼치기와 선택을 한 번에 — 사용자가 기대하는 건 "누르면 열리고 그려진다".
          // ★고르는 첫 클릭은 **반드시 연다**. 그냥 toggle 로 두면 채권·원자재처럼
          //   기본 펼침(layer1)인 묶음은 첫 클릭에 접혀 버려 "열리면서"와 어긋난다.
          //   이미 고른 묶음을 다시 누를 때만 접기/펴기로 동작한다.
          if (selectable) {
            if (!active) {
              if (!isOpen) onToggle(path);
              rest.onSelect({ kind: "group", l1, l2, label: node.label });
            } else {
              onToggle(path);
            }
          } else {
            onToggle(path);
          }
        }}
        title={
          selectable
            ? rest.view === "table"
              ? `${node.label} ${node.children.length}개 시장 표에서 강조`
              : `${node.label} ${node.children.length}개 시장 한눈에 비교`
            : undefined
        }
        className={cn(
          "flex w-full items-center gap-1 rounded py-[5px] pr-1.5 text-left transition-colors",
          active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
        )}
        style={{ paddingLeft: 3 + depth * 11 }}
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform",
            isOpen && "rotate-90",
          )}
        />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-[13.5px] font-extrabold",
            active ? "text-ge-point" : "text-ge-navy",
          )}
        >
          {node.label}
        </span>
        <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
          {node.children.length}
        </span>
      </button>
      {isOpen ? (
        <div>
          {node.children.map((c, i) =>
            c.type === "node" ? (
              <Node
                key={`${path}-${c.label}`}
                node={c}
                depth={depth + 1}
                open={open}
                onToggle={onToggle}
                path={path}
                active={rest.active}
                isYield={rest.isYield}
                view={rest.view}
                onSelect={rest.onSelect}
              />
            ) : (
              <Leaf
                key={c.key ?? i}
                node={c}
                depth={depth + 1}
                active={rest.active?.kind === "leaf" && rest.active.key === c.key}
                isYield={rest.isYield}
                onSelect={rest.onSelect}
              />
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}

export function PriceTreeCard({
  cat,
  onCat,
  selected,
  onSelect,
  view,
  onView,
}: {
  cat: PriceCatKey;
  onCat: (c: PriceCatKey) => void;
  selected: PriceSel | null;
  onSelect: (sel: PriceSel) => void;
  view: PriceView;
  onView: (v: PriceView) => void;
}) {
  const { data, isLoading, isError } = useQuery<PriceBoard>({
    queryKey: ["price-board", cat],
    queryFn: () => getPriceBoard(cat),
    refetchInterval: POLL_MS,
  });
  const tree = data?.tree ?? [];
  const isYield = !!data?.is_yield;
  const cats = data?.categories ?? [];

  // 기본 펼침 = layer1 전부. 자산군이 바뀌면 다시 계산한다.
  const [open, setOpen] = useState<Set<string>>(new Set());
  useEffect(() => {
    setOpen(
      new Set(tree.filter((n) => n.type === "node").map((n) => `/${(n as { label: string }).label}`)),
    );
  }, [cat, tree.length]);

  const toggle = (path: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });

  return (
    // 카드끼리 맞붙는 배치(gap-0)라 테두리는 **오른쪽 한 줄**만 — 사방 테두리면 옆
    // 카드와 선이 겹쳐 2px 가 되고, 둥근 모서리는 이음매에 흰 홈을 만든다.
    <section className="lg:col-start-1 lg:row-span-2 flex min-h-0 flex-col border-r border-hairline bg-canvas">
      {/* 제목 띠 — 강조색(ge-header). 배경이 어두우니 글자·탭을 흰색 계열로 뒤집는다. */}
      <header className="flex shrink-0 flex-col gap-1 bg-ge-header px-2 py-1.5">
        <div className="flex items-baseline gap-1.5">
          <h2 className="shrink-0 text-[15px] font-extrabold text-white">지표 리스트</h2>
          {data?.asof ? (
            <span className="ml-auto shrink-0 text-[11.5px] tabular-nums text-white/60">
              {data.asof.slice(5)}
            </span>
          ) : null}
        </div>
        {/* 자산군 탭 + (차트/표) 토글. 탭은 5개라 좁은 1칸에서 두 줄로 접히므로
            토글은 같은 줄이 아니라 **오른쪽 끝에 세로 가운데**로 붙인다(items-center)
            — 탭이 한 줄이든 두 줄이든 토글 위치가 흔들리지 않는다. */}
        <div className="flex items-center gap-1.5">
          <div className="flex min-w-0 flex-1 flex-wrap gap-0.5">
            {cats.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => onCat(c.key)}
                className={cn(
                  "rounded px-2 py-[3px] text-[12.5px] font-bold transition-colors",
                  cat === c.key
                    ? "bg-white text-ge-header"
                    : "bg-white/15 text-white/75 hover:bg-white/30",
                )}
              >
                {c.label}
              </button>
            ))}
          </div>
          {/* 아이콘 두 개짜리 세그먼트. 글자를 안 쓰는 이유는 폭이다 — 1칸 헤더에
              '차트'·'표' 를 적으면 자산군 탭이 세 줄로 밀린다. */}
          <div className="flex shrink-0 overflow-hidden rounded border border-white/25">
            {(
              [
                { v: "chart" as const, Icon: LineChart, title: "차트 — 고른 지수·묶음의 시계열" },
                { v: "table" as const, Icon: Table2, title: "표 — 자산군 전체 성과표" },
              ]
            ).map(({ v, Icon, title }) => (
              <button
                key={v}
                type="button"
                onClick={() => onView(v)}
                title={title}
                aria-label={title}
                aria-pressed={view === v}
                className={cn(
                  "flex h-[24px] w-[28px] items-center justify-center transition-colors",
                  view === v
                    ? "bg-white text-ge-header"
                    : "bg-white/10 text-white/70 hover:bg-white/25",
                )}
              >
                <Icon className="h-[15px] w-[15px]" strokeWidth={2.4} />
              </button>
            ))}
          </div>
        </div>
      </header>

      {isLoading ? (
        <Center msg="불러오는 중…" />
      ) : isError ? (
        <Center msg="collector 에 못 닿았습니다." tone="text-rose-600" />
      ) : tree.length === 0 ? (
        <Center
          msg={data?.note ?? "price_monitor.xlsx 판독 대기 중입니다."}
          tone={data?.note ? "text-amber-600" : undefined}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
          {tree.map((n, i) =>
            n.type === "node" ? (
              <Node
                key={n.label}
                node={n}
                depth={0}
                open={open}
                onToggle={toggle}
                path=""
                active={selected}
                isYield={isYield}
                view={view}
                onSelect={onSelect}
              />
            ) : (
              <Leaf
                key={n.key ?? i}
                node={n}
                depth={0}
                active={selected?.kind === "leaf" && selected.key === n.key}
                isYield={isYield}
                onSelect={onSelect}
              />
            ),
          )}
        </div>
      )}

      <div className="shrink-0 border-t border-hairline px-2 py-1 text-[10.5px] leading-snug text-slate-400">
        옆 숫자 = DtD ({isYield ? "bp" : "%"}) · 지수 클릭 = 단일 · 묶음 클릭 = 전체 비교
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-3 text-center">
      <span className={cn("text-[12.5px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
