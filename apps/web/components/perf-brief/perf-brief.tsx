"use client";

/* [성과보고] 데일리·위클리 성과 브리프 — 네이티브 렌더 (2026-07-28).
 *
 * performance-brief 스킬이 만들던 독립 HTML 리포트를 대시보드 컴포넌트로 옮긴 것.
 * 원본 디자인 시스템의 컴포넌트(스코어카드 · 다이버징 바 · 듀얼 바 · 일별 경로 ·
 * 스토리 카드 · 관전 포인트)를 그대로 옮기되, 색·서피스는 GE 대시보드 토큰을 쓴다.
 * 바 폭·경로 높이는 JSON 에 담지 않고 여기서 계산한다(원본 스킬의 스케일 공식과 동일):
 *   바 width% = |값| / (차트 최대 절대값 × 1.05) × 100
 *   경로 height% = |수익률| / 최대 절대값 × 50
 */

import * as React from "react";
import type {
  PerfBarRow,
  PerfBlock,
  PerfMarketChip,
  PerfPathDay,
  PerfReport,
  PerfScore,
  PerfSection,
  PerfStory,
  PerfTone,
} from "@/lib/api";

// 부호색 — 대시보드 컨벤션(＋빨강 / −파랑). torus-aicoretech 페이지와 동일.
const POS = "#e74c3c";
const NEG = "#4a7ab5";

function toneColor(tone: PerfTone | null | undefined): string {
  if (tone === "pos") return POS;
  if (tone === "neg") return NEG;
  return "#8a94a6"; // ink-muted
}
function signColor(v: number): string {
  if (v === 0) return "#8a94a6";
  return v > 0 ? POS : NEG;
}

/* ── 인라인 마크업 ────────────────────────────────────────────────────
 * **굵게** · {+양수 강조} · {-음수 강조}
 * 원본 리포트가 캡션·본문에서 쓰던 <b>/<span class="pos"> 을 대체한다 —
 * JSON 에 HTML 을 담지 않으므로 dangerouslySetInnerHTML 이 필요 없다. */
const RICH_RE = /\*\*(.+?)\*\*|\{([+-])(.+?)\}/g;

export function RichText({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  const re = new RegExp(RICH_RE.source, "g");
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) {
      out.push(
        <b key={key++} className="font-bold text-ge-navy">
          {m[1]}
        </b>,
      );
    } else {
      out.push(
        <b key={key++} className="font-bold" style={{ color: m[2] === "+" ? POS : NEG }}>
          {m[3]}
        </b>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

/* ── 시장 스트립 (4칩) ────────────────────────────────────────────── */

function MarketStrip({ chips }: { chips: PerfMarketChip[] }) {
  if (!chips.length) return null;
  return (
    <div className="mb-6 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {chips.map((c, i) => (
        <div key={i} className="rounded-lg border border-hairline bg-canvas-soft px-3 py-2.5">
          <div className="text-[13px] font-bold text-ink">
            {c.head}
            {c.value && (
              <span className="ml-1.5 font-extrabold" style={{ color: toneColor(c.tone) }}>
                {c.value}
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[12px] leading-snug text-ink-muted">{c.note}</div>
        </div>
      ))}
    </div>
  );
}

/* ── 스코어카드 ──────────────────────────────────────────────────── */

function ScoreCards({ scores }: { scores: PerfScore[] }) {
  const cols = scores.length >= 4 ? "xl:grid-cols-4" : "xl:grid-cols-3";
  return (
    <div className={`mb-4 grid gap-2.5 sm:grid-cols-2 ${cols}`}>
      {scores.map((s, i) => {
        const alpha = s.variant === "alpha";
        const ytd = s.variant === "ytd";
        const accent = toneColor(s.tone);
        return (
          <div
            key={i}
            className="rounded-xl border bg-canvas px-5 pb-3.5 pt-4"
            style={{
              borderColor: alpha ? accent : ytd ? "#4a7ab5" : "#dde2e8",
              borderWidth: alpha || ytd ? 1.5 : 1,
              background: alpha ? (s.tone === "pos" ? "#fdefec" : "#eef4fb") : undefined,
            }}
          >
            <div className="mb-0.5 text-[11.5px] font-semibold tracking-wide text-ink-muted">
              {s.label}
            </div>
            <div
              className="text-[38px] font-extrabold leading-[1.1] tracking-tight tabular-nums"
              style={{ color: accent }}
            >
              {s.value}
            </div>
            {s.sub && (
              <div className="mt-1.5 text-[11.5px] leading-relaxed text-ink-muted">
                <RichText text={s.sub} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── 차트 껍데기 (제목 + 단위 + 캡션) ───────────────────────────────── */

function ChartCard({
  title,
  unit,
  legend,
  meta,
  caption,
  children,
}: {
  title: string;
  unit?: string | null;
  legend?: string | null;
  meta?: string | null;
  caption?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3 rounded-xl border border-hairline bg-canvas px-5 pb-3.5 pt-4">
      <h4 className="mb-3 text-[13px] font-bold text-ge-navy">
        {title}
        {unit && <span className="ml-1.5 text-[12px] font-medium text-ink-muted">{unit}</span>}
      </h4>
      {meta && (
        <div className="mb-2.5 text-[12.5px] text-ink">
          <RichText text={meta} />
        </div>
      )}
      {legend && <div className="mb-2 text-[11px] text-ink-muted">{legend}</div>}
      {children}
      {caption && (
        <div className="mt-2.5 border-t border-dashed border-hairline pt-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <RichText text={caption} />
        </div>
      )}
    </div>
  );
}

/* ── 다이버징 바 (0 기준 좌우) · 듀얼(당사+BM) 겸용 ──────────────────── */

function fmtVal(v: number, unit: string): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const abs = Math.abs(v);
  const body = unit === "bp" ? String(Math.round(abs)) : abs.toFixed(unit === "pp" ? 1 : 2);
  if (v === 0) return unit === "bp" ? "0" : body;
  return `${sign}${body}`;
}

function BarsChart({
  rows,
  dual,
  valueUnit,
}: {
  rows: PerfBarRow[];
  dual: boolean;
  valueUnit: string;
}) {
  // 스케일 = 차트 내 최대 절대값 × 1.05 (원본 스킬 공식). 0 나눗셈 방지로 하한 1.
  const scale = React.useMemo(() => {
    let mx = 0;
    for (const r of rows) {
      mx = Math.max(mx, Math.abs(r.value));
      if (dual && r.value2 != null) mx = Math.max(mx, Math.abs(r.value2));
    }
    return Math.max(mx * 1.05, 1e-9);
  }, [rows, dual]);

  const w = (v: number) => `${Math.min(100, (Math.abs(v) / scale) * 100)}%`;

  return (
    <div>
      {rows.map((r, i) => (
        <div
          key={i}
          className="grid items-center gap-2.5 py-[3px]"
          style={{ gridTemplateColumns: "minmax(96px, 150px) 1fr 62px" }}
        >
          <div className="truncate text-right text-[12.5px] text-ink">
            {r.label}
            {r.note && <span className="ml-1 text-[11px] text-ink-muted">{r.note}</span>}
          </div>

          <div className={`grid grid-cols-2 ${dual ? "h-[22px]" : "h-4"}`}>
            {/* 좌: 음수 (오른쪽 정렬) */}
            <div className="relative border-r border-ink">
              {r.value < 0 && (
                <div
                  className="absolute rounded-sm"
                  style={{
                    right: 0,
                    width: w(r.value),
                    background: NEG,
                    ...(dual
                      ? { top: 2, height: 8 }
                      : { top: 1, bottom: 1 }),
                  }}
                />
              )}
              {dual && r.value2 != null && r.value2 < 0 && (
                <div
                  className="absolute rounded-sm"
                  style={{ right: 0, width: w(r.value2), background: NEG, top: 12, height: 8, opacity: 0.38 }}
                />
              )}
            </div>
            {/* 우: 양수 (왼쪽 정렬) */}
            <div className="relative">
              {r.value > 0 && (
                <div
                  className="absolute rounded-sm"
                  style={{
                    left: 0,
                    width: w(r.value),
                    background: POS,
                    ...(dual ? { top: 2, height: 8 } : { top: 1, bottom: 1 }),
                  }}
                />
              )}
              {dual && r.value2 != null && r.value2 > 0 && (
                <div
                  className="absolute rounded-sm"
                  style={{ left: 0, width: w(r.value2), background: POS, top: 12, height: 8, opacity: 0.38 }}
                />
              )}
            </div>
          </div>

          <div className="text-[12.5px] font-bold tabular-nums" style={{ color: signColor(r.value) }}>
            {fmtVal(r.value, valueUnit)}
            {dual && r.value2 != null && (
              <span
                className="block text-[11px] font-semibold"
                style={{ color: signColor(r.value2) }}
              >
                {fmtVal(r.value2, valueUnit)}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── 일별(주차별) 경로 — 중앙축 위/아래 세로 막대 ────────────────────── */

function PathChart({ days }: { days: PerfPathDay[] }) {
  const scale = React.useMemo(() => {
    let mx = 0;
    for (const d of days) mx = Math.max(mx, Math.abs(d.self), Math.abs(d.bm));
    return Math.max(mx, 1e-9);
  }, [days]);
  const h = (v: number) => `${(Math.abs(v) / scale) * 50}%`;

  return (
    <div className="flex gap-1 sm:gap-2.5">
      {days.map((d, i) => (
        <div key={i} className="flex-1 text-center">
          <div className="relative h-[112px] border-b border-dashed border-hairline">
            {/* 0% 기준선 */}
            <div className="absolute left-0 right-0 top-1/2 border-t border-hairline" />
            {[
              { v: d.self, cls: "left-[calc(50%-17px)]", dim: false },
              { v: d.bm, cls: "left-[calc(50%+2px)]", dim: true },
            ].map((b, j) => (
              <div
                key={j}
                className={`absolute w-[15px] ${b.cls}`}
                style={{
                  height: h(b.v),
                  background: b.v >= 0 ? POS : NEG,
                  opacity: b.dim ? 0.38 : 1,
                  ...(b.v >= 0
                    ? { bottom: "50%", borderRadius: "2px 2px 0 0" }
                    : { top: "50%", borderRadius: "0 0 2px 2px" }),
                }}
              />
            ))}
          </div>
          <div className="mt-1.5 text-[11.5px] font-bold text-ink">{d.label}</div>
          <div className="text-[11px] leading-snug tabular-nums" style={{ color: signColor(d.self) }}>
            {d.self > 0 ? "+" : ""}
            {d.self.toFixed(2)}%
          </div>
          <div
            className="text-[11px] leading-snug tabular-nums"
            style={{ color: signColor(d.bm) }}
          >
            {d.bm > 0 ? "+" : ""}
            {d.bm.toFixed(2)}%
          </div>
          <span
            className="mt-1 inline-block rounded px-1.5 py-px text-[10.5px] font-bold tabular-nums"
            style={{
              color: signColor(d.spreadBp),
              background: d.spreadBp >= 0 ? "#fdefec" : "#eef4fb",
            }}
          >
            {fmtVal(d.spreadBp, "bp")}bp
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── 스토리 카드 ─────────────────────────────────────────────────── */

function StoryCards({ items }: { items: PerfStory[] }) {
  const cols = items.length >= 3 ? "xl:grid-cols-3" : "xl:grid-cols-2";
  return (
    <div className={`mb-3 grid gap-3 ${cols}`}>
      {items.map((s, i) => (
        <article
          key={i}
          className="flex flex-col rounded-xl border border-hairline border-l-[3px] border-l-ge-navy bg-canvas px-[18px] py-4"
        >
          <div className="mb-2 text-[15.5px] font-extrabold leading-snug tracking-tight text-ge-navy">
            {s.verdict}
            {s.tag && (
              <span
                className="ml-1.5 inline-block whitespace-nowrap rounded px-1.5 py-0.5 align-[2px] text-[11px] font-bold"
                style={{
                  color: toneColor(s.tagTone),
                  background: s.tagTone === "pos" ? "#fdefec" : "#eef4fb",
                }}
              >
                {s.tag}
              </span>
            )}
          </div>
          <p className="flex-1 text-[13px] leading-relaxed text-ink">
            <RichText text={s.body} />
          </p>
          {s.watch && (
            <div className="mt-3 border-t border-dashed border-hairline pt-2.5 text-[12.5px] text-ink">
              <span className="mr-2 font-extrabold text-ge-point">▸ 체크</span>
              {s.watch}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

/* ── 블록 디스패치 ───────────────────────────────────────────────── */

function Block({ block }: { block: PerfBlock }) {
  if (block.type === "stories") return <StoryCards items={block.items} />;
  if (block.type === "path") {
    return (
      <ChartCard
        title={block.title}
        unit={block.unit}
        legend={block.legend}
        caption={block.caption}
      >
        <PathChart days={block.days} />
      </ChartCard>
    );
  }
  return (
    <ChartCard
      title={block.title}
      unit={block.unit}
      meta={block.meta}
      caption={block.caption}
    >
      <BarsChart
        rows={block.rows}
        dual={block.type === "dualBars"}
        valueUnit={block.valueUnit ?? "bp"}
      />
    </ChartCard>
  );
}

/* ── 섹션 (01 랩 / 02 펀드) ──────────────────────────────────────── */

function Section({ section }: { section: PerfSection }) {
  return (
    <section className="mb-8 last:mb-0">
      <div className="mb-1 text-[11px] font-bold tracking-[0.22em] text-ge-point">
        {section.eyebrow}
      </div>
      <div className="mb-4 flex flex-wrap items-baseline gap-2.5">
        <h3 className="text-[21px] font-extrabold tracking-tight text-ge-navy">{section.title}</h3>
        {section.bm && <span className="text-[12.5px] text-ink-muted">{section.bm}</span>}
      </div>
      <ScoreCards scores={section.scores} />
      {section.blocks.map((b, i) => (
        <Block key={i} block={b} />
      ))}
    </section>
  );
}

/* ── 관전 포인트 (딥 네이비 카드) ───────────────────────────────────── */

function Checkpoints({
  title,
  items,
}: {
  title: string;
  items: { head: string; note: string }[];
}) {
  return (
    <div className="mb-4 rounded-xl bg-ge-navy px-[22px] py-[18px]">
      <h3 className="mb-2.5 text-[13px] font-bold tracking-[0.14em] text-ge-blue-bg">{title}</h3>
      <ol className="grid gap-4 xl:grid-cols-3">
        {items.map((it, i) => (
          <li key={i} className="text-[13px] leading-snug text-white">
            <b className="mb-0.5 block text-[14px] font-bold">{it.head}</b>
            <span className="text-[#b9c1cd]">{it.note}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ── 보고서 본문 ─────────────────────────────────────────────────── */

export function PerfBriefReport({ report }: { report: PerfReport }) {
  return (
    // 문서형 콘텐츠라 폭을 제한한다 — 대시보드 전체폭에 풀어두면 바 길이·행 간격이
    // 늘어나 원본 리포트의 비율(max-width 1060px 기준)이 무너진다.
    <div className="mx-auto max-w-[1180px]">
      <header className="mb-3.5 flex flex-wrap items-end justify-between gap-3 border-b-[3px] border-ge-navy pb-3.5">
        <div>
          <div className="mb-1 text-[12px] font-semibold tracking-[0.18em] text-ge-point">
            {report.eyebrow}
          </div>
          <div className="text-[24px] font-extrabold tracking-tight text-ge-navy">
            {report.title}
          </div>
        </div>
        <div className="text-right text-[13px] leading-snug text-ink-muted">
          <div className="text-ink">{report.dateLine}</div>
          {report.dateNote && <div>{report.dateNote}</div>}
        </div>
      </header>

      <MarketStrip chips={report.market} />

      {report.sections.map((s) => (
        <Section key={s.id} section={s} />
      ))}

      {report.checkpoints && (
        <Checkpoints title={report.checkpoints.title} items={report.checkpoints.items} />
      )}

      {report.footnote && (
        <footer className="text-[11.5px] leading-[1.7] text-ink-muted">
          <RichText text={report.footnote} />
        </footer>
      )}
    </div>
  );
}
