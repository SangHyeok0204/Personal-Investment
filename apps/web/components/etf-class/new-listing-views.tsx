"use client";

import type { EtfNewListingPayload } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RollingText } from "@/components/rolling-text";
import { EMDASH, fmtEok, fmtPct, tone } from "./format";

// ★성적표의 실시간 값은 10분마다 새로 받는다(사용자 지시 2026-09-02). 값이 바뀌면
//   기존 숫자가 아래로 빠지고 새 숫자가 내려온다. 길이는 **1.5초** — 전역 CSS(0.35s)를
//   고치면 iNAV·WRAP·전광판이 같이 느려지므로 이 화면에서만 준다.
const ROLL_MS = 1500;

// [국내상장 ETF] 왼쪽 박스 ①②가 가운데에 띄우는 두 화면.
//
// ★★두 화면이 답하는 게 다르다.
//   ① 성적표(확정·사후)  = 이미 상장한 종목이 그날 얼마를 끌어모았나.
//        원천은 daily_analysis/YYYYMMDD_신규상장.txt (장 마감 뒤 워크북 매크로가 굽는다).
//        수익률은 txt 에 없어 워크북 등락률을 이름으로 붙였다.
//   ② 상장 정보(확정+예정) = 오늘 상장하는/할 종목의 총보수·구성종목·실시간 시세.
//        확정 상장일은 **KRX** 만 준다. DART 예비투자설명서는 예상 **범위**라 따로 둔다.
//
// ★★2026-09-02 사용자 지시로 표기를 바꿨다.
//   · "금일 신규 상장된 ETF가 없습니다. 아래는 최근…" **안내 배너를 뺐다**. 대신 종목명
//     옆에 `(09-01 상장)` 을 붙인다 — 날짜가 이름에 붙어 있으면 배너 없이도 오늘 것이
//     아님이 드러난다. 배너는 매번 같은 자리에서 같은 말을 해 자리만 먹었다.
//   · 성적표의 게이지 막대를 뺐다. 숫자 넷(이름·거래대금·순매수·수익률)만 크게 둔다.
//   · 상장 정보는 줄글 대신 **지표 타일**로. 라벨 위 · 값 아래.

function Empty({ text, sub }: { text: string; sub?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1.5 px-6 text-center">
      <p className="text-[17px] font-extrabold text-ink-secondary">{text}</p>
      {sub && <p className="text-[12.5px] text-ink-faint">{sub}</p>}
    </div>
  );
}

/** ★★불러오기 실패를 '없음' 으로 말하면 안 된다.
 *  둘 다 데이터가 비어 있어 화면에서는 똑같아 보이지만, "금일 신규 상장된 ETF가
 *  없습니다" 는 **사실 주장**이다. 서버가 안 붙었을 뿐인데 그 문장을 띄우면
 *  상장이 있었던 날에도 없다고 말하게 된다. */
function Failed({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : "알 수 없는 오류";
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1.5 px-6 text-center">
      <p className="text-[17px] font-extrabold text-amber-800">
        신규상장 데이터를 불러오지 못했습니다
      </p>
      <p className="max-w-md text-[12.5px] leading-relaxed text-ink-faint">
        상장이 없다는 뜻이 아닙니다. 수집기에 닿지 못했습니다. ({msg})
      </p>
    </div>
  );
}

function ViewHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="sticky top-0 z-10 flex items-baseline justify-between gap-3 border-b border-hairline bg-canvas px-4 py-2">
      <span className="text-[14px] font-extrabold text-ge-navy">{title}</span>
      {note && (
        <span className="shrink-0 text-[11.5px] font-semibold text-ink-faint">
          {note}
        </span>
      )}
    </div>
  );
}

/** 'YYYY-MM-DD' → '09-01'. 종목명 옆에 붙는 상장일. */
function mmdd(d: string | null | undefined): string {
  return d && d.length >= 10 ? d.slice(5) : "";
}

/* ── ① 신규 상장 ETF 성적표 ───────────────────────────────────────────────
   ★★2026-09-02 사용자 지시로 **iNAV 모니터의 ETF 카드**와 같은 꼴로 맞췄다. 한 줄에 3장.
     iNAV 카드가 [현재가 크게 + 등락률 칩 + 미니지표 표]인데, 여기는 호가를 못 보여주므로
     **현재가 자리에 개인 순매수**를 놓는다. 이 화면이 묻는 게 "얼마나 붙었나" 라서
     그 숫자가 헤드라인이어야 한다.
   ★★한 카드 안에 시점이 둘 섞인다. 헤드라인 순매수·수익률·거래대금은 **상장일** 값이고
     (워크북이 그날 굽고 끝난다), 등락률 칩·거래대금(현재)·거래량은 **지금** 값이다
     (CHECK, 10초마다 새로 받고 바뀌면 1.5초에 걸쳐 굴러 내려온다).
     그래서 미니지표 라벨에 시점을 박아 둔다 — '거래대금' 이 두 번 나오는데 상장일 18억과
     지금 5억이 라벨 없이 나란히 있으면 모순으로 읽힌다. */

function MiniMetric({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-1.5">
      <dt className="shrink-0 text-[10.5px] font-semibold text-ink-muted">{label}</dt>
      <dd className="truncate text-[11.5px] font-bold tabular-nums text-ink">
        {children}
      </dd>
    </div>
  );
}

/** 등락률 칩 — iNAV 카드와 같은 규칙(상승 빨강 / 하락 파랑). 값이 바뀌면 구른다. */
function ChangeChip({ pct }: { pct: number | null | undefined }) {
  if (pct == null) {
    return <span className="text-[12px] text-ink-faint">{EMDASH}</span>;
  }
  const up = pct > 0;
  const down = pct < 0;
  return (
    <span
      className={cn(
        "rounded-md px-1.5 py-0.5 text-[12px] font-bold tabular-nums",
        up && "bg-status-failed/[0.08] text-status-failed",
        down && "bg-status-running/[0.08] text-status-running",
        !up && !down && "text-ink-secondary",
      )}
    >
      <RollingText
        text={`${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}
        durationMs={ROLL_MS}
      />
    </span>
  );
}

export function ReportView({
  data,
  error,
}: {
  data: EtfNewListingPayload | undefined;
  error?: unknown;
}) {
  if (error && !data) return <Failed error={error} />;
  const rep = data?.report;
  if (!rep || rep.rows.length === 0) {
    return (
      <Empty
        text="금일 신규 상장된 ETF가 없습니다"
        sub="상장은 보통 주 1회(화요일)입니다. 장 마감 뒤 성적표가 만들어집니다."
      />
    );
  }
  const day = mmdd(rep.date);
  const stale = data?.realtime_stale ?? true;
  const rtWhen = data?.realtime_asof ? data.realtime_asof.slice(11, 16) : null;

  return (
    <div className="h-full overflow-y-auto">
      <ViewHead
        title="신규 상장 ETF 성적표"
        note={`${rep.date} · ${rep.rows.length}종목${
          stale ? ` · 시세 ${rtWhen ?? "?"} 기준(실시간 아님)` : " · 10초 갱신"
        }`}
      />
      <div className="grid grid-cols-3 gap-2.5 p-2.5">
        {rep.rows.map((r) => {
          const rt = r.realtime;
          return (
            <div
              key={`${r.rank}-${r.name}`}
              className="flex flex-col gap-2 rounded-2xl border-2 border-hairline bg-canvas p-3 text-left shadow-card"
            >
              <div className="min-w-0">
                <div className="truncate text-[13px] font-extrabold text-ge-navy">
                  {r.name}
                </div>
                <div className="text-[11px] font-semibold tabular-nums text-ink-muted">
                  {r.ticker || EMDASH}
                  {day && (
                    <span className="ml-1 font-medium text-ink-faint">
                      · {day} 상장
                    </span>
                  )}
                </div>
              </div>

              {/* iNAV 카드의 현재가 자리 = 개인 순매수(상장일). 오른쪽은 지금 등락률. */}
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "text-[21px] font-extrabold leading-none tabular-nums",
                    tone(r.net_buy),
                  )}
                >
                  {fmtEok(r.net_buy)}
                </span>
                <ChangeChip pct={rt?.change} />
              </div>
              <div className="-mt-1 text-[10px] font-semibold text-ink-faint">
                개인 순매수 · {day} 상장일
              </div>

              <dl className="grid gap-y-1 border-t border-hairline pt-2">
                <MiniMetric label={`수익률 ${day}`}>
                  <span className={tone(r.ret)}>{fmtPct(r.ret, 1)}</span>
                </MiniMetric>
                <MiniMetric label={`거래대금 ${day}`}>
                  {fmtEok(r.trade_value, false)}
                </MiniMetric>
                <MiniMetric label="보수율">
                  {r.fee == null ? EMDASH : `${Number(r.fee.toFixed(3))}%`}
                </MiniMetric>
                <MiniMetric label="거래대금 현재">
                  <RollingText
                    text={fmtEok(rt?.trade_value, false)}
                    durationMs={ROLL_MS}
                  />
                </MiniMetric>
                <MiniMetric label="거래량 현재">
                  <RollingText
                    text={
                      rt?.volume == null
                        ? EMDASH
                        : `${Math.round(rt.volume).toLocaleString("en-US")}주`
                    }
                    durationMs={ROLL_MS}
                  />
                </MiniMetric>
              </dl>

              {!rt && (
                <p className="text-[10.5px] font-semibold text-ink-faint">
                  실시간 시세 없음. CHECK 관심목록 밖입니다.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── 지표 타일 — 라벨 위, 값 아래 ────────────────────────────────────────── */
function Stat({
  label,
  value,
  toneClass,
  note,
  live,
}: {
  label: string;
  value: string;
  toneClass?: string;
  note?: string;
  /** true 면 값이 바뀔 때 굴러 내려온다(10분마다 새로 받는 값). */
  live?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col items-center justify-center rounded-lg border border-hairline bg-canvas-soft px-2 py-2">
      <span className="text-[12.5px] font-bold leading-none text-ink-secondary">
        {label}
      </span>
      <span
        className={cn(
          "mt-1.5 truncate text-[19px] font-extrabold leading-none tabular-nums",
          toneClass ?? "text-ge-navy",
        )}
      >
        {live ? <RollingText text={value} durationMs={ROLL_MS} /> : value}
      </span>
      {note && (
        <span className="mt-1 text-[10px] font-semibold leading-none text-ink-faint">
          {note}
        </span>
      )}
    </div>
  );
}

/* ── ② 신규 상장 임박 ETF 상세 정보 ─────────────────────────────────────── */
export function ListingView({
  data,
  error,
}: {
  data: EtfNewListingPayload | undefined;
  error?: unknown;
}) {
  if (error && !data) return <Failed error={error} />;
  const listing = data?.listing;
  const upcoming = data?.upcoming ?? [];
  // ★★이 화면은 **아직 상장 안 한** 종목만 다룬다(사용자 지시 2026-09-02). 서버는 오늘
  //   상장이 없으면 가장 최근 상장일로 되돌려 주는데(성적표 카드가 보수율·시세를 잇는 데
  //   그 목록이 필요하다), 여기서는 그 폴백을 쓰면 안 된다 — 어제 상장한 종목이
  //   '상장 임박' 으로 올라온다.
  const todayRows = listing?.is_today ? listing.rows : [];
  const has = todayRows.length > 0;
  // ★낡은 envelope 을 "실시간" 이라 부르지 않는다. 장 마감 뒤·CHECK PC 정지 뒤의 마지막
  //   값이 그대로 남는데, 그걸 실시간이라 쓰면 그 자체가 틀린 말이 된다.
  const stale = data?.realtime_stale ?? true;
  const rtWhen = data?.realtime_asof ? data.realtime_asof.slice(11, 16) : null;
  const day = mmdd(listing?.date);

  if (!has && upcoming.length === 0) {
    return (
      <Empty
        text="상장 예정인 ETF가 없습니다"
        sub="금일 상장도, DART 예비투자설명서에 잡힌 예정 건도 없습니다."
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <ViewHead
        title={has ? "금일 상장 ETF" : "상장 예정 ETF"}
        note={
          has
            ? `${listing!.date} · ${todayRows.length}종목${
                stale ? ` · 시세 ${rtWhen ?? "?"} 기준(실시간 아님)` : " · 실시간"
              }`
            : `상장 예정 ${upcoming.length}건`
        }
      />

      <div className={has ? "space-y-2.5 p-3" : "hidden"}>
        {todayRows.map((e) => {
          const rt = e.realtime;
          return (
            <div
              key={e.ticker || e.name}
              className="rounded-xl border border-hairline bg-canvas p-3 shadow-card"
            >
              {/* 이름 + 상장일 · 오른쪽에 종목코드를 독립적으로 크게 */}
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="min-w-0 truncate text-[17px] font-extrabold text-ink">
                      {e.name}
                    </span>
                    {day && (
                      <span className="shrink-0 text-[12px] font-semibold text-ink-faint">
                        ({day} 상장)
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 truncate text-[12px] font-semibold text-ink-muted">
                    {e.company}
                    {e.asset_class ? ` · ${e.asset_class}` : ""}
                  </div>
                </div>
                <div className="shrink-0 rounded-lg bg-ge-navy px-3 py-1.5 text-center">
                  <div className="text-[9.5px] font-bold leading-none text-white/60">
                    종목코드
                  </div>
                  <div className="mt-1 text-[18px] font-extrabold leading-none tracking-wide text-white tabular-nums">
                    {e.ticker || EMDASH}
                  </div>
                </div>
              </div>

              {/* 지표 타일 넷 */}
              <div className="mt-2.5 grid grid-cols-4 gap-2">
                <Stat
                  label="총 보수율"
                  value={e.fee == null ? EMDASH : `${Number(e.fee.toFixed(3))}%`}
                />
                <Stat
                  label="등락률"
                  value={
                    rt?.change == null
                      ? EMDASH
                      : `${rt.change > 0 ? "+" : ""}${rt.change.toFixed(2)}%`
                  }
                  toneClass={tone(rt?.change)}
                  note={stale && rt ? "실시간 아님" : undefined}
                  live
                />
                <Stat
                  label="거래대금"
                  value={fmtEok(rt?.trade_value, false)}
                  note={stale && rt ? `${rtWhen ?? ""} 기준` : undefined}
                  live
                />
                <Stat
                  label="거래량"
                  value={
                    rt?.volume == null
                      ? EMDASH
                      : `${Math.round(rt.volume).toLocaleString("en-US")}주`
                  }
                  live
                />
              </div>

              {!rt && (
                <p className="mt-2 text-[11.5px] font-semibold text-ink-faint">
                  실시간 시세 없음. CHECK 관심목록 밖의 종목입니다.
                </p>
              )}

              <div className="mt-2 flex items-baseline gap-2">
                <span className="shrink-0 text-[11.5px] font-bold text-ink-secondary">
                  주요 구성종목
                </span>
                {e.holdings.length === 0 ? (
                  <span className="text-[12px] text-ink-faint">아직 공개 전</span>
                ) : (
                  <span className="flex min-w-0 flex-wrap gap-x-2 gap-y-1">
                    {e.holdings.slice(0, 3).map((h) => (
                      <span
                        key={h.name}
                        className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[12px] font-bold text-ge-point"
                      >
                        {h.name}{" "}
                        <span className="tabular-nums">
                          {h.weight == null ? EMDASH : `${h.weight}%`}
                        </span>
                      </span>
                    ))}
                  </span>
                )}
              </div>

              {e.benchmark && (
                <div className="mt-1.5 truncate text-[11px] text-ink-faint">
                  기초지수 {e.benchmark}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {upcoming.length > 0 && (
        <>
          <div className="sticky top-[37px] z-10 flex items-baseline justify-between border-y border-hairline bg-ge-th px-4 py-1.5">
            <span className="text-[12.5px] font-extrabold text-ink-secondary">
              상장 예정
            </span>
            <span className="text-[10.5px] font-semibold text-ink-faint">
              DART 예비투자설명서 · 날짜는 범위 · 이미 상장한 건은 제외
            </span>
          </div>
          <div className="space-y-2 p-3">
            {upcoming.map((u) => (
              <div
                key={u.rcept_no}
                className="rounded-lg border border-hairline bg-canvas px-3 py-2"
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-extrabold text-ink">
                      {u.name}
                    </div>
                    <div className="mt-0.5 truncate text-[11.5px] font-semibold text-ink-muted">
                      {u.company}
                    </div>
                  </div>
                  <div className="shrink-0 rounded-md bg-ge-blue-bg px-2.5 py-1 text-center">
                    <div className="text-[9.5px] font-bold leading-none text-ge-point/70">
                      예상 상장
                    </div>
                    <div className="mt-1 text-[13px] font-extrabold leading-none tabular-nums text-ge-point">
                      {mmdd(u.est_from)}~{mmdd(u.est_to)}
                    </div>
                  </div>
                </div>
                {u.holdings.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-1">
                    {u.holdings.slice(0, 4).map((h) => (
                      <span
                        key={h.name}
                        className="rounded bg-canvas-soft px-1.5 py-0.5 text-[11px] font-semibold text-ink-secondary"
                      >
                        {h.name}{" "}
                        <span className="tabular-nums">
                          {h.weight == null ? EMDASH : `${h.weight}%`}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

    </div>
  );
}
