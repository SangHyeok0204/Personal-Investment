"use client";

import type { CSSProperties, ReactNode } from "react";
import { CloudOff, PlugZap } from "lucide-react";
import { useConnectDialog } from "@/components/brokerage/connect-context";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// 개조 중 자리잡기용 공통 조각(2026-09-21).
//
// 키움/토스 계좌 API 가 붙기 전까지 화면의 **모양과 정보 밀도**를 먼저 확정하려고
// 만들었다. 숫자는 전부 "—" 로 둔다 — 그럴듯한 더미 숫자를 넣으면 나중에 실데이터와
// 섞였을 때 어느 쪽이 진짜인지 구분이 안 된다.
//
// ★StatTile 은 이제 `value` 를 받는다(2026-09-21 2차). 실데이터가 붙은 화면은 값을
//   넘기고, 아직 안 붙은 화면은 안 넘겨서 "—" 로 둔다 — 한 컴포넌트로 두 상태를
//   같은 모양으로 그린다.
// ─────────────────────────────────────────────────────────────────────────────

/** 아직 계좌 API 가 없다는 사실을 화면 맨 위에 못박는 띠. */
export function NotConnectedBanner({
  what,
  message,
}: {
  what: string;
  /** 기본 문구 대신 쓸 설명(예: API 서버 자체가 안 떠 있는 경우). */
  message?: string;
}) {
  return (
    <div className="mb-5 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <PlugZap className="h-4 w-4 shrink-0 text-amber-600" />
      <p className="text-[13px] font-semibold text-amber-900">
        {message ?? `${what} 미연동`}
      </p>
      <ConnectButton />
    </div>
  );
}

/** 어디서 눌러도 같은 연동 팝업을 연다. */
function ConnectButton() {
  const { open } = useConnectDialog();
  return (
    <button
      type="button"
      onClick={open}
      className="ml-auto shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-[12px] font-bold text-amber-800 transition-colors hover:bg-amber-100"
    >
      계좌 연동하기
    </button>
  );
}

/** 외부 데이터 원천에 닿지 못했을 때 띄우는 띠.
 *
 * ★"데이터가 없습니다"와 **"원천이 죽었습니다"는 다른 상태**다. 둘을 같은 문구로
 *   보여 주면 사용자가 "정말 없는 건가?"를 판단할 수 없다. 실제로 어닝 화면은
 *   Nasdaq 이 죽어도 "향후 60일 안에 예정된 발표가 없습니다"라고 말하고 있었다 —
 *   맞는 말처럼 보이지만 거짓이다.
 *
 * ⚠️재시도하라고 시키지 않는다. 서버가 캐시 TTL 뒤에 자동으로 다시 받아 온다 —
 *   사용자가 할 수 있는 일이 없는데 버튼을 두면 눌러도 안 되는 버튼이 된다.
 */
export function SourceDownBanner({
  source,
  detail,
}: {
  /** 어느 원천인지. 사용자가 직접 확인해 볼 수 있어야 한다. */
  source: string;
  detail?: string;
}) {
  return (
    <div className="mb-2 flex shrink-0 items-center gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5">
      <CloudOff className="h-4 w-4 shrink-0 text-amber-600" />
      <p className="text-[12px] font-semibold leading-snug text-amber-900">
        {/* ⚠️JSX 인접 표현식 사이에는 공백이 들어가지 않는다 — 그냥 이어 쓰면
            "아닙니다.미국 경제지표..." 처럼 붙어 버린다(실제로 그랬다).
            각 조각을 span 으로 감싸고 앞에 여백을 준다. */}
        <b>{source}</b> 응답 없음
        {detail && <span className="ml-1.5 font-medium">{detail}</span>}
      </p>
    </div>
  );
}

/** 상단 요약 숫자 한 칸. `value` 가 없으면 "—". */
export function StatTile({
  label,
  value,
  hint,
  subHint,
  hintStrong,
  accent,
  loading,
  onClick,
  actionHint,
}: {
  label: string;
  value?: string | null;
  hint?: string;
  /** ★2026-10-05 설명 둘째 줄(선택). 한 줄에 다 넣으면 좁은 칸에서 잘린다(성과 화면 1280px 실측). */
  subHint?: string;
  /** ★2026-11-15 사용자 지시: 설명 줄을 숫자(수익률)로 쓸 때 — 보통 캡션보다 진한 회색. */
  hintStrong?: boolean;
  /** "auto" 면 값의 부호를 보고 상승/하락 색을 고른다. */
  accent?: "up" | "down" | "neutral" | "auto";
  loading?: boolean;
  /** 누르면 상세를 연다. 주면 카드가 버튼이 된다. */
  onClick?: () => void;
  /** 호버할 때 카드 오른쪽 위에 뜨는 안내(예: "눌러서 추이 보기"). */
  actionHint?: string;
}) {
  const shown = loading ? "…" : (value ?? "—");
  const resolved =
    accent === "auto"
      ? shown.startsWith("-")
        ? "down"
        : shown.startsWith("+")
          ? "up"
          : "neutral"
      : accent;

  const interactive = onClick != null;
  return (
    <div
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className={cn(
        "group relative rounded-2xl border border-hairline bg-canvas px-3.5 py-3 shadow-card",
        interactive &&
          "cursor-pointer transition-all hover:border-ge-point/40 hover:shadow-panel focus:outline-none focus-visible:border-ge-point",
      )}
    >
      <div className="text-[11px] font-bold tracking-wide text-ink-muted">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-[22px] font-extrabold",
          // 국내 관행: 상승/이익 = 빨강, 하락/손실 = 파랑.
          resolved === "up" && "text-bid",
          resolved === "down" && "text-ask",
          (resolved == null || resolved === "neutral") && "text-ge-navy",
        )}
      >
        {/* 값이 바뀌면 자릿수가 굴러 올라간다(5초 갱신이 눈에 보이게).
            "…"·"—" 처럼 굴릴 자리가 없는 값은 그냥 그린다. */}
        {shown === "…" || shown === "—" ? (
          <span className="tabular-nums leading-none">{shown}</span>
        ) : (
          <AnimatedNumber value={shown} lineHeight={26} />
        )}
      </div>
      {hint && (
        <div
          className={cn(
            "mt-1 truncate text-[11px]",
            hintStrong ? "font-semibold tabular-nums text-ink-secondary" : "font-medium text-ink-muted",
          )}
        >
          {hint}
        </div>
      )}
      {subHint && (
        <div className="truncate text-[11px] font-medium text-ink-muted">{subHint}</div>
      )}
      {/* 누를 수 있다는 걸 호버에서만 알린다 — 평소엔 숫자가 주인공이다.
          ★2026-09-25 사용자 지시: 오른쪽 위 구석으로. 아래에 두면 설명 줄(hint)과
            겹쳐서 둘 다 안 읽혔다. */}
      {interactive && actionHint && (
        <div className="pointer-events-none absolute right-3.5 top-3 max-w-[55%] truncate text-right text-[10px] font-bold text-ge-point opacity-0 transition-opacity group-hover:opacity-100">
          {actionHint}
        </div>
      )}
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return (
    <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{children}</div>
  );
}

/** 제목 띠(ge-header) 달린 카드 — 대시보드 카드의 기본형. */
export function StubCard({
  title,
  subtitle,
  children,
  className,
  /** 헤더 오른쪽에 붙는 컨트롤(축 전환 칩 등). 제목 줄을 낭비하지 않는다. */
  action,
  /** 본문이 넘치면 카드 안에서만 스크롤한다(페이지는 그대로). */
  scrollBody = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  scrollBody?: boolean;
}) {
  return (
    <section
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card",
        className,
      )}
    >
      <header className="flex shrink-0 items-center gap-2 bg-ge-header px-4 py-2">
        <h2 className="shrink-0 text-[13px] font-extrabold tracking-tight text-white">
          {title}
        </h2>
        {subtitle && (
          <span className="truncate text-[11px] font-medium text-white/60">
            {subtitle}
          </span>
        )}
        {action && <div className="ml-auto shrink-0">{action}</div>}
      </header>
      <div
        className={cn(
          "min-h-0 flex-1 p-3.5",
          scrollBody && "overflow-y-auto",
        )}
      >
        {children}
      </div>
    </section>
  );
}

/** 차트가 들어올 자리 — 축만 그려 두어 어떤 그림이 올지 읽히게 한다. */
export function StubChart({
  height = 200,
  note = "데이터 연동 대기",
}: {
  height?: number;
  note?: string;
}) {
  return (
    <div
      style={{ height }}
      className="relative w-full rounded-xl border border-dashed border-ge-line-soft bg-canvas-soft/60"
    >
      <div className="absolute inset-x-3 inset-y-3 flex flex-col justify-between">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-px w-full bg-ge-line-soft/70" />
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="rounded-full bg-white/80 px-3 py-1 text-[11px] font-bold text-ink-faint">
          {note}
        </span>
      </div>
    </div>
  );
}

/** 표가 들어올 자리 — 컬럼 이름은 확정해 두고 행만 비운다. */
export function StubTable({
  columns,
  rows = 5,
}: {
  columns: string[];
  rows?: number;
}) {
  return (
    <div className="overflow-hidden">
      <table className="w-full border-collapse border-t border-ink text-left">
        <thead>
          <tr className="border-b border-hairline bg-ge-th">
            {columns.map((c) => (
              <th
                key={c}
                className="whitespace-nowrap px-2.5 py-2 text-[11px] font-bold text-ink"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r} className="border-t border-hairline">
              {columns.map((c) => (
                <td
                  key={c}
                  className="px-3 py-2.5 text-[12px] font-semibold tabular-nums text-ink-faint"
                >
                  —
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 실데이터 표 — 같은 껍데기를 쓰되 행은 호출자가 그린다. */
export function DataTable({
  columns,
  children,
  empty,
  align,
  sort,
}: {
  columns: string[];
  children: ReactNode;
  /** 행이 하나도 없을 때 표 자리에 띄울 문구. */
  empty?: string;
  /** 컬럼별 정렬 — 생략하면 첫 컬럼만 좌측, 나머지는 우측(숫자 표 기본형). */
  align?: ("left" | "right")[];
  /** 주면 제목 칸을 눌러 정렬한다. 행 순서는 부르는 쪽이 바꾼다(이 표는 그리기만). */
  sort?: {
    column: number;
    dir: "asc" | "desc";
    onSort: (column: number) => void;
  };
}) {
  const hasRows = Array.isArray(children)
    ? children.flat().filter(Boolean).length > 0
    : Boolean(children);

  return (
    // 가이드 §7.1 — 표는 **좌우 테두리가 없다**. 위는 검정 실선, 나머지는 옅은 회색.
    //   바깥 박스로 감싸면 좌우 선이 생기므로 border 를 주지 않는다.
    <div className="overflow-x-auto">
      <table className="w-full border-collapse border-t border-ink text-left">
        <thead>
          <tr className="border-b border-hairline bg-ge-th">
            {columns.map((c, i) => (
              <th
                key={c}
                className={cn(
                  // 가이드 §7.2 — 표 제목 11p Bold Black.
                  "whitespace-nowrap px-3 py-2 text-[11px] font-bold text-ink",
                  (align?.[i] ?? (i === 0 ? "left" : "right")) === "right" &&
                    "text-right",
                )}
                aria-sort={
                  sort?.column === i
                    ? sort.dir === "asc"
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {sort ? (
                  <button
                    type="button"
                    onClick={() => sort.onSort(i)}
                    className={cn(
                      "group -mx-1 inline-flex items-center gap-1 rounded px-1 transition-colors hover:bg-white/70",
                      (align?.[i] ?? (i === 0 ? "left" : "right")) === "right" &&
                        "flex-row-reverse",
                    )}
                  >
                    {c}
                    {/* 정렬 중인 칸은 늘 화살표, 나머지는 호버할 때만 흐리게 —
                        누를 수 있다는 걸 누르기 전에 알려 준다. */}
                    <span
                      className={cn(
                        "text-[9px] leading-none",
                        sort.column === i
                          ? "text-ge-point"
                          : "text-ink-faint opacity-0 group-hover:opacity-100",
                      )}
                    >
                      {sort.column === i && sort.dir === "asc" ? "▲" : "▼"}
                    </span>
                  </button>
                ) : (
                  c
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hasRows ? (
            children
          ) : (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-10 text-center text-[12px] font-semibold text-ink-faint"
              >
                {empty ?? "표시할 내용이 없습니다"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** DataTable 의 셀 — 기본 우측 정렬(숫자), `left` 로 좌측. */
export function Cell({
  children,
  left,
  strong,
  tone,
  className,
  style,
}: {
  children: ReactNode;
  left?: boolean;
  strong?: boolean;
  tone?: "up" | "down" | "muted";
  className?: string;
  /** 데이터에서 온 색(밸류체인 L1 등)처럼 클래스로 못 쓰는 값만. */
  style?: CSSProperties;
}) {
  return (
    <td
      style={style}
      className={cn(
        // 가이드 §7.2 — 표 본문 9p Regular #595959. 강조 행만 Bold Black.
        "whitespace-nowrap px-2.5 py-2.5 text-[12px] tabular-nums",
        left ? "text-left" : "text-right",
        strong ? "font-bold text-ink" : "font-normal text-ink-secondary",
        tone === "up" && "text-bid",
        tone === "down" && "text-ask",
        tone === "muted" && "text-ink-faint",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** 문자열 금액의 부호로 상승/하락 색을 고른다. */
export function toneOf(value: string | null | undefined): "up" | "down" | undefined {
  if (value == null || value === "") return undefined;
  if (value.startsWith("-")) return "down";
  if (/^-?0*(\.0*)?$/.test(value)) return undefined;
  return "up";
}

/** 앞으로 이 화면에 무엇이 들어올지 적어 두는 목록. 설계 메모가 화면에 남는다. */
/**
 * 서버·화면 문구의 `**강조**` 만 굵게 그린다.
 *
 * ⚠️**한 군데에 둔다.** 화면 일곱 곳이 똑같은 함수를 각자 복사해 두고 있었고,
 *   정작 공용인 `PlannedList` 는 이걸 안 써서 `**금액**` 같은 별표가 **화면에
 *   그대로 찍히고 있었다**(수익률 추이·리서치 등). 문구에 강조를 적는 습관이
 *   있으면, 그 문구를 그리는 곳이 전부 이걸 써야 한다.
 *
 * ⚠️`dangerouslySetInnerHTML` 을 쓰지 않는다. 지금 들어오는 문구는 서버 상수라
 *   안전하지만, 나중에 증권사 메시지나 사용자 입력이 섞이면 그때는 늦는다.
 */
export function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
        // split 의 홀수 인덱스가 캡처 그룹(강조 대상)이다.
        i % 2 === 1 ? (
          <strong key={i} className="text-ink">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** 카드 본문이 비었을 때(불러오는 중·데이터 없음) 가운데 한 줄.
 *  ★2026-09-25 여러 화면의 같은 `Empty` 복사본을 여기로 모았다. */
export function CardEmpty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center">
      <span className="text-[12px] font-semibold text-ink-faint">{text}</span>
    </div>
  );
}

/** 카드 헤더(짙은 갈색) 위의 기간·축 전환 칩. 흰 계열로 맞춘다. */
export function HeaderChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-bold transition-colors",
        active
          ? "bg-white/90 text-ge-header"
          : "text-white/60 hover:bg-white/15 hover:text-white",
      )}
    >
      {children}
    </button>
  );
}

/** 팝업 안의 라벨 + 큰 숫자 한 칸. tone 이 있으면 상승/하락 색. */
export function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <dt className="text-[11px] font-bold text-ink-muted">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 text-[15px] font-extrabold tabular-nums",
          tone === "up" && "text-bid",
          tone === "down" && "text-ask",
          !tone && "text-ge-navy",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/** 카드 헤더(짙은 갈색)의 '전체 목록' 버튼 — 목록을 팝업으로 여는 공통 자리.
 *  ★2026-09-25 여러 화면이 각자 복사해 두던 것을 여기로 모았다. */
export function ListButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
    >
      전체 목록
    </button>
  );
}

export function PlannedList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2.5">
          <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
          <span className="text-[13px] font-semibold leading-snug text-ink-secondary">
            <Emphasized text={t} />
          </span>
        </li>
      ))}
    </ul>
  );
}
