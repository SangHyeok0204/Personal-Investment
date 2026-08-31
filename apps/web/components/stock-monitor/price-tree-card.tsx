"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
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
// ★★2026-08-28 사용자 지시: **묶음도 클릭 대상**이다. 미국·유럽처럼 자식이 전부
//   지수인 노드를 누르면 펼쳐지는 동시에 오른쪽 차트가 그 묶음 전체를 겹쳐 그린다.
//   자식이 또 노드인 DM·EM 은 펼치기만 한다 — 25개를 한 차트에 겹치면 스파게티다.

const POLL_MS = 600_000;

// 차트가 무엇을 그릴지 정하는 선택 상태. 지수 하나(leaf) 또는 묶음(group).
export type PriceSel =
  | { kind: "leaf"; key: string }
  | { kind: "group"; l1: string; l2: string; label: string };

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
        "flex w-full items-baseline gap-1 rounded py-[3px] pr-1 text-left transition-colors",
        active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
      )}
      style={{ paddingLeft: 6 + depth * 9 }}
    >
      <span
        className={cn(
          "min-w-0 flex-1 truncate text-[11px]",
          active ? "font-extrabold text-ge-point" : "font-semibold text-ink",
        )}
      >
        {node.label}
      </span>
      {/* 목록에는 DtD 하나만 — 나머지 셋은 오른쪽 차트가 시계열로 보여준다. */}
      <span className={cn("shrink-0 text-[10px] font-bold tabular-nums", tone(node.dtd))}>
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
  onSelect: (sel: PriceSel) => void;
}) {
  const path = `${rest.path}/${node.label}`;
  const isOpen = open.has(path);

  // 자식이 전부 지수여야 "묶음"으로 고를 수 있다. DM·EM 처럼 자식이 또 노드면
  // 펼치기 전용 — 하위 묶음 중 어느 것을 그릴지 스스로 정할 수 없다.
  const leafOnly = node.children.every((c) => c.type === "leaf");
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
          if (leafOnly) {
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
        title={leafOnly ? `${node.label} ${node.children.length}개 시장 한눈에 비교` : undefined}
        className={cn(
          "flex w-full items-center gap-0.5 rounded py-[3px] pr-1 text-left transition-colors",
          active ? "bg-ge-blue-bg" : "hover:bg-canvas-soft",
        )}
        style={{ paddingLeft: 2 + depth * 9 }}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 text-ink-muted transition-transform",
            isOpen && "rotate-90",
          )}
        />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-[11px] font-extrabold",
            active ? "text-ge-point" : "text-ge-navy",
          )}
        >
          {node.label}
        </span>
        <span className="shrink-0 text-[9.5px] tabular-nums text-slate-400">
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
}: {
  cat: PriceCatKey;
  onCat: (c: PriceCatKey) => void;
  selected: PriceSel | null;
  onSelect: (sel: PriceSel) => void;
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
          <h2 className="shrink-0 text-[12.5px] font-extrabold text-white">지표 리스트</h2>
          {data?.asof ? (
            <span className="ml-auto shrink-0 text-[10px] tabular-nums text-white/60">
              {data.asof.slice(5)}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-0.5">
          {cats.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => onCat(c.key)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10.5px] font-bold transition-colors",
                cat === c.key
                  ? "bg-white text-ge-header"
                  : "bg-white/15 text-white/75 hover:bg-white/30",
              )}
            >
              {c.label}
            </button>
          ))}
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

      <div className="shrink-0 border-t border-hairline px-2 py-0.5 text-[9.5px] text-slate-400">
        옆 숫자 = DtD ({isYield ? "bp" : "%"}) · 지수 클릭 = 단일 · 묶음 클릭 = 전체 비교
      </div>
    </section>
  );
}

function Center({ msg, tone }: { msg: string; tone?: string }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-3 text-center">
      <span className={cn("text-[11px] font-semibold leading-relaxed text-ink-muted", tone)}>
        {msg}
      </span>
    </div>
  );
}
