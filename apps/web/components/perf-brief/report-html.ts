/* [성과보고] 보고서 JSON → 독립 HTML 파일 ([파일로 저장] 버튼).
 *
 * 대시보드로 편입하기 전에 쓰던 리포트 HTML 과 **같은 산출물**을 만든다 — 스타일시트는
 * 원본(위클리_성과보고_*.html)의 것을 그대로 옮겼고, 마크업 구조(chip/score/row/track/
 * path/story/today)도 클래스까지 동일하다. 그래서 인쇄·공유 결과가 기존 보고서와 같다.
 *
 * 브라우저에서 만들어 Blob 으로 내려받는다 — 서버 왕복이 없어 collector 가 꺼져 있어도
 * 화면에 떠 있는 보고서는 저장할 수 있다.
 *
 * 바 길이·경로 높이 계산은 perf-brief.tsx 의 React 컴포넌트와 같은 식을 쓴다:
 *   바 width%   = |값| / (차트 최대 절대값 × 1.05) × 100
 *   경로 height% = |값| / 최대 절대값 × 50
 */

import type { PerfBarRow, PerfBlock, PerfReport, PerfScore, PerfTone } from "@/lib/api";

const PRETENDARD =
  "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css";

/* 원본 리포트 스타일시트 (verbatim). 하우스 스타일이라 손대지 않는다. */
const CSS = `
  :root{
    --ink:#1B2430; --ink-soft:#5A6472; --paper:#F4F5F7; --card:#FFFFFF; --line:#E2E5EA;
    --rise:#D63C4B; --rise-bg:#FBEDEE;   /* 상승·플러스 (국내 관례: 빨강) */
    --fall:#2E64C7; --fall-bg:#EBF1FB;   /* 하락·마이너스 (국내 관례: 파랑) */
    --bronze:#9A7B33;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html{-webkit-text-size-adjust:100%;}
  body{font-family:'Pretendard Variable',Pretendard,-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
    background:var(--paper);color:var(--ink);font-size:14px;line-height:1.55;font-variant-numeric:tabular-nums;}
  .wrap{max-width:1060px;margin:0 auto;padding:36px 28px 56px;}
  header{display:flex;justify-content:space-between;align-items:flex-end;
    border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:14px;}
  .doc-title{font-size:26px;font-weight:800;letter-spacing:-0.02em;}
  .doc-title small{display:block;font-size:12px;font-weight:600;color:var(--bronze);letter-spacing:.18em;margin-bottom:4px;}
  .doc-date{text-align:right;font-size:13px;color:var(--ink-soft);line-height:1.5;}
  .doc-date b{color:var(--ink);font-size:15px;}
  .market{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:34px;}
  .chip{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;}
  .chip b{display:block;font-size:13px;margin-bottom:2px;}
  .chip span{font-size:12px;color:var(--ink-soft);}
  section{margin-bottom:44px;}
  .eyebrow{font-size:11px;font-weight:700;color:var(--bronze);letter-spacing:.22em;margin-bottom:6px;}
  .sec-head{display:flex;align-items:baseline;gap:10px;margin-bottom:16px;}
  .sec-head h2{font-size:21px;font-weight:800;letter-spacing:-0.01em;}
  .sec-head .bm{font-size:12.5px;color:var(--ink-soft);}
  .score{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:18px;}
  .score.four{grid-template-columns:repeat(4,1fr);}
  .score .cell{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px 14px;}
  .score .cell.alpha{border-width:1.5px;}
  .score .cell.alpha.pos{border-color:var(--rise);background:var(--rise-bg);}
  .score .cell.alpha.neg{border-color:var(--fall);background:var(--fall-bg);}
  .score label{display:block;font-size:11.5px;font-weight:600;color:var(--ink-soft);letter-spacing:.06em;margin-bottom:2px;}
  .score .num{font-size:44px;font-weight:800;letter-spacing:-0.03em;line-height:1.1;}
  .score.four .num{font-size:36px;}
  .score .sub{font-size:11.5px;color:var(--ink-soft);margin-top:6px;line-height:1.5;}
  .pos{color:var(--rise);} .neg{color:var(--fall);} .flat{color:var(--ink-soft);}
  .chart{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 22px 14px;margin-bottom:18px;}
  .chart h3{font-size:13px;font-weight:700;margin-bottom:12px;}
  .chart h3 span{font-weight:500;color:var(--ink-soft);font-size:12px;margin-left:6px;}
  .chart .meta{font-size:12.5px;margin-bottom:10px;}
  .row{display:grid;grid-template-columns:150px 1fr 58px;align-items:center;gap:10px;padding:3.5px 0;}
  .row .lab{font-size:12.5px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .row .lab small{color:var(--ink-soft);font-size:11px;margin-left:4px;}
  .track{display:grid;grid-template-columns:1fr 1fr;height:16px;}
  .half{position:relative;}
  .half.l{border-right:1px solid var(--ink);}
  .bar{position:absolute;top:1px;bottom:1px;border-radius:2px;}
  .half.l .bar{right:0;background:var(--fall);}
  .half.r .bar{left:0;background:var(--rise);}
  .row .val{font-size:12.5px;font-weight:700;}
  .row.dual .track{height:22px;}
  .row.dual .bar{top:2px;bottom:auto;height:8px;}
  .row.dual .bar.b2{top:12px;opacity:.38;}
  .row.dual .val{font-size:11px;line-height:1.4;}
  .row.dual .val span{display:block;font-weight:600;color:var(--ink-soft);}
  .chart .cap{font-size:12px;color:var(--ink-soft);margin-top:10px;padding-top:10px;border-top:1px dashed var(--line);}
  .path{display:flex;gap:10px;margin-top:4px;}
  .day{flex:1;text-align:center;}
  .plot{height:116px;position:relative;}
  .plot::before{content:"";position:absolute;top:50%;left:6%;right:6%;border-top:1px solid var(--ink);}
  .vbar{position:absolute;width:15px;border-radius:2px 2px 0 0;}
  .vbar.b2{opacity:.38;}
  .vbar.up{bottom:50%;background:var(--rise);}
  .vbar.dn{top:50%;background:var(--fall);border-radius:0 0 2px 2px;}
  .vbar.p1{left:calc(50% - 17px);}
  .vbar.p2{left:calc(50% + 2px);}
  .day .dlab{font-size:11.5px;font-weight:700;margin-top:6px;}
  .day .dval{font-size:11px;line-height:1.45;}
  .day .dspr{display:inline-block;font-size:10.5px;font-weight:700;margin-top:3px;padding:1px 6px;border-radius:4px;}
  .dspr.pos{background:var(--rise-bg);color:var(--rise);} .dspr.neg{background:var(--fall-bg);color:var(--fall);}
  .legend{font-size:11px;color:var(--ink-soft);margin-bottom:8px;}
  .stories{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px;}
  .stories.three{grid-template-columns:1fr 1fr 1fr;}
  .story{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--ink);
    border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;}
  .story .verdict{font-size:15.5px;font-weight:800;line-height:1.35;margin-bottom:8px;letter-spacing:-0.01em;}
  .story .verdict .tag{font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;vertical-align:2px;margin-left:6px;white-space:nowrap;}
  .tag.pos{background:var(--rise-bg);color:var(--rise);}
  .tag.neg{background:var(--fall-bg);color:var(--fall);}
  .story p{font-size:13px;color:#343E4C;flex:1;}
  .story p b{font-weight:700;}
  .story .watch{margin-top:12px;padding-top:10px;border-top:1px dashed var(--line);font-size:12.5px;}
  .story .watch::before{content:"▸ 체크";font-weight:800;color:var(--bronze);margin-right:8px;}
  .today{background:var(--ink);color:#fff;border-radius:10px;padding:18px 22px;margin-bottom:14px;}
  .today h2{font-size:13px;font-weight:700;letter-spacing:.14em;color:#C8B27A;margin-bottom:10px;}
  .today ol{list-style:none;display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;}
  .today li{font-size:13px;line-height:1.5;}
  .today li b{display:block;font-size:14px;margin-bottom:2px;}
  .today li span{color:#B9C1CD;}
  .warn{background:#FDF6EE;border:1px solid #E6C9A8;border-radius:10px;padding:12px 16px;margin-bottom:18px;}
  .warn b{display:block;font-size:12px;color:#8A5A1F;margin-bottom:4px;}
  .warn li{font-size:12px;color:#6B4A1C;list-style:none;line-height:1.6;}
  footer{font-size:11.5px;color:var(--ink-soft);line-height:1.7;}
  footer b{color:var(--ink);}
  @media (max-width:760px){
    .market{grid-template-columns:1fr 1fr;}
    .score,.score.four{grid-template-columns:1fr;}
    .score .num{font-size:34px;}
    .stories,.stories.three,.today ol{grid-template-columns:1fr;}
    .row{grid-template-columns:96px 1fr 52px;}
    .path{gap:4px;}
  }
  @media print{body{background:#fff;}.wrap{padding:0;}
    .story,.chart,.chip,.score .cell{break-inside:avoid;}}
`;

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** 인라인 마크업 → HTML. **굵게** · {+양수} · {-음수} (escape 후 적용) */
function rich(s: string | null | undefined): string {
  if (!s) return "";
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\{([+-])(.+?)\}/g, (_m, sign: string, body: string) =>
      `<b class="${sign === "+" ? "pos" : "neg"}">${body}</b>`,
    );
}

const toneCls = (t: PerfTone | null | undefined) =>
  t === "pos" ? "pos" : t === "neg" ? "neg" : "flat";
const signCls = (v: number) => (v > 0 ? "pos" : v < 0 ? "neg" : "flat");

function fmtVal(v: number, unit: string): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const abs = Math.abs(v);
  const body = unit === "bp" ? String(Math.round(abs)) : abs.toFixed(unit === "pp" ? 1 : 2);
  if (v === 0) return unit === "bp" ? "0" : body;
  return `${sign}${body}`;
}

function scoresHtml(scores: PerfScore[]): string {
  const cells = scores
    .map((s) => {
      const cls = ["cell"];
      if (s.variant === "alpha") cls.push("alpha", toneCls(s.tone));
      return `<div class="${cls.join(" ")}"><label>${esc(s.label)}</label>` +
        `<div class="num ${toneCls(s.tone)}">${esc(s.value)}</div>` +
        (s.sub ? `<div class="sub">${rich(s.sub)}</div>` : "") +
        `</div>`;
    })
    .join("");
  return `<div class="score${scores.length >= 4 ? " four" : ""}">${cells}</div>`;
}

function barsHtml(rows: PerfBarRow[], dual: boolean, unit: string): string {
  let max = 0;
  for (const r of rows) {
    max = Math.max(max, Math.abs(r.value));
    if (dual && r.value2 != null) max = Math.max(max, Math.abs(r.value2));
  }
  const scale = Math.max(max * 1.05, 1e-9);
  const w = (v: number) => `${Math.min(100, (Math.abs(v) / scale) * 100).toFixed(1)}%`;
  const bar = (v: number, second: boolean) =>
    `<div class="bar${second ? " b2" : ""}" style="width:${w(v)}"></div>`;

  return rows
    .map((r) => {
      const left =
        (r.value < 0 ? bar(r.value, false) : "") +
        (dual && r.value2 != null && r.value2 < 0 ? bar(r.value2, true) : "");
      const right =
        (r.value > 0 ? bar(r.value, false) : "") +
        (dual && r.value2 != null && r.value2 > 0 ? bar(r.value2, true) : "");
      const second =
        dual && r.value2 != null
          ? `<span class="${signCls(r.value2)}">${fmtVal(r.value2, unit)}</span>`
          : "";
      return (
        `<div class="row${dual ? " dual" : ""}">` +
        `<div class="lab">${esc(r.label)}${r.note ? `<small>${esc(r.note)}</small>` : ""}</div>` +
        `<div class="track"><div class="half l">${left}</div><div class="half r">${right}</div></div>` +
        `<div class="val ${signCls(r.value)}">${fmtVal(r.value, unit)}${second}</div></div>`
      );
    })
    .join("");
}

function pathHtml(days: { label: string; self: number; bm: number; spreadBp: number }[]): string {
  let max = 0;
  for (const d of days) max = Math.max(max, Math.abs(d.self), Math.abs(d.bm));
  const scale = Math.max(max, 1e-9);
  const h = (v: number) => `${((Math.abs(v) / scale) * 50).toFixed(1)}%`;
  const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

  return (
    `<div class="path">` +
    days
      .map(
        (d) =>
          `<div class="day"><div class="plot">` +
          `<div class="vbar p1 ${d.self >= 0 ? "up" : "dn"}" style="height:${h(d.self)}"></div>` +
          `<div class="vbar p2 ${d.bm >= 0 ? "up" : "dn"} b2" style="height:${h(d.bm)}"></div>` +
          `</div><div class="dlab">${esc(d.label)}</div>` +
          `<div class="dval ${signCls(d.self)}">${pct(d.self)}</div>` +
          `<div class="dval ${signCls(d.bm)}">${pct(d.bm)}</div>` +
          `<span class="dspr ${signCls(d.spreadBp)}">${fmtVal(d.spreadBp, "bp")}bp</span></div>`,
      )
      .join("") +
    `</div>`
  );
}

function blockHtml(b: PerfBlock): string {
  if (b.type === "stories") {
    const cards = b.items
      .map(
        (s) =>
          `<article class="story"><div class="verdict">${esc(s.verdict)}` +
          (s.tag ? `<span class="tag ${toneCls(s.tagTone)}">${esc(s.tag)}</span>` : "") +
          `</div><p>${rich(s.body)}</p>` +
          (s.watch ? `<div class="watch">${esc(s.watch)}</div>` : "") +
          `</article>`,
      )
      .join("");
    return `<div class="stories${b.items.length >= 3 ? " three" : ""}">${cards}</div>`;
  }

  const head =
    `<h3>${esc(b.title)}${b.unit ? `<span>${esc(b.unit)}</span>` : ""}</h3>`;
  if (b.type === "path") {
    return (
      `<div class="chart">${head}` +
      (b.legend ? `<div class="legend">${esc(b.legend)}</div>` : "") +
      pathHtml(b.days) +
      (b.caption ? `<div class="cap">${rich(b.caption)}</div>` : "") +
      `</div>`
    );
  }
  return (
    `<div class="chart">${head}` +
    (b.meta ? `<div class="meta">${rich(b.meta)}</div>` : "") +
    barsHtml(b.rows, b.type === "dualBars", b.valueUnit ?? "bp") +
    (b.caption ? `<div class="cap">${rich(b.caption)}</div>` : "") +
    `</div>`
  );
}

/** 보고서 JSON → 독립 HTML 문서 + 기존 명명 규칙에 맞춘 파일명. */
export function renderReportHtml(
  report: PerfReport,
  warnings?: string[],
): { html: string; filename: string } {
  const chips = (report.market ?? [])
    .map(
      (c) =>
        `<div class="chip"><b>${esc(c.head)}` +
        (c.value ? ` <span class="${toneCls(c.tone)}" style="font-weight:700">${esc(c.value)}</span>` : "") +
        `</b><span>${esc(c.note)}</span></div>`,
    )
    .join("");

  const sections = report.sections
    .map(
      (s) =>
        `<section><div class="eyebrow">${esc(s.eyebrow)}</div>` +
        `<div class="sec-head"><h2>${esc(s.title)}</h2>` +
        (s.bm ? `<span class="bm">${esc(s.bm)}</span>` : "") +
        `</div>${scoresHtml(s.scores)}${s.blocks.map(blockHtml).join("")}</section>`,
    )
    .join("");

  const cp = report.checkpoints;
  const today = cp
    ? `<div class="today"><h2>${esc(cp.title)}</h2><ol>` +
      cp.items
        .map((i) => `<li><b>${esc(i.head)}</b><span>${esc(i.note)}</span></li>`)
        .join("") +
      `</ol></div>`
    : "";

  const warnBox =
    warnings && warnings.length
      ? `<div class="warn"><b>QA 경고 ${warnings.length}건</b><ul>` +
        warnings.map((w) => `<li>· ${esc(w)}</li>`).join("") +
        `</ul></div>`
      : "";

  const dot = (iso: string) => iso.replace(/-/g, ".");
  const docTitle =
    report.kind === "weekly" && report.period
      ? `위클리 성과 보고 · ${dot(report.period.start)}–${dot(report.period.end).slice(5)}`
      : `데일리 성과 보고 · ${dot(report.asOf)}`;

  const html = `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(docTitle)}</title>
<link rel="stylesheet" href="${PRETENDARD}">
<style>${CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="doc-title"><small>${esc(report.eyebrow)}</small>${esc(report.title)}</div>
    <div class="doc-date"><b>${esc(report.dateLine)}</b>${report.dateNote ? `<br>${esc(report.dateNote)}` : ""}</div>
  </header>
  ${chips ? `<div class="market">${chips}</div>` : ""}
  ${warnBox}
  ${sections}
  ${today}
  ${report.footnote ? `<footer>${rich(report.footnote)}</footer>` : ""}
</div>
</body>
</html>`;

  // 기존 보고서 명명 규칙 그대로 — 같은 폴더에 그대로 떨어뜨릴 수 있게.
  const nd = (iso: string) => iso.replace(/-/g, "");
  const filename =
    report.kind === "weekly" && report.period
      ? `위클리_성과보고_${nd(report.period.start)}_${nd(report.period.end).slice(4)}.html`
      : `데일리_성과보고_${nd(report.asOf)}.html`;

  return { html, filename };
}

/** 브라우저에서 곧바로 내려받기. */
export function downloadReportHtml(report: PerfReport, warnings?: string[]): void {
  const { html, filename } = renderReportHtml(report, warnings);
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
