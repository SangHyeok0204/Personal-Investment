"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { SeriesChart } from "@/components/charts/series-chart";
import { SignedBarChart } from "@/components/charts/signed-bar-chart";
import {
  Cell,
  DataTable,
  HeaderChip,
  ListButton,
  NotConnectedBanner,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import {
  getAccountReturn,
  getPerformance,
  type DailyPerformancePoint,
} from "@/lib/api";
import { formatKrwCompactString, formatKrwSigned, formatKrwString } from "@/lib/format";
import { cn } from "@/lib/utils";

// 수익률 추이.
//
// ★2026-09-21: 키움 usa21670(일별계좌수익률현황)에 배선했다. 스냅샷을 쌓는 배치를
//   만들지 않은 이유 — 증권사가 이미 과거 일별 시계열을 들고 있다(실측 531일).
//   우리가 오늘부터 새로 쌓으면 과거가 영영 비어 있게 된다.
//
// ★2026-09-22: **이 화면이 한 화면에서 서로 반대되는 말을 하고 있었다.**
//   상단 타일은 '입출금 제외 증감 −₩722,749 (−1.86%)', 오른쪽 월별 표의 손익
//   합은 '+₩2,469,456'. 둘 다 맞고, 다른 것을 재고 있었을 뿐이다.
//     · 예탁자산은 **원화 환산액** — 환율이 빠지면 종목이 그대로여도 줄어든다.
//     · 증권사 일별 손익(pl_amt)은 **주가 손익** — 환율이 들어 있지 않다.
//   실측: 이 구간 USD/KRW 1,530.11 → 1,384.86 (−9.49%). 두 숫자 차이
//   ₩3,203,574 ÷ 9.49% ≈ ₩33,757,366 으로 구간 평균 주식평가액과 거의 같다.
//   그래서 나란히 두지 않고 **타일 넷이 왼쪽에서 오른쪽으로 더해지게** 바꿨다:
//   주가 손익 → 환율 등 → 원화 증감.
//
// ⚠️'환율 등'은 **잔차**다. 환율이 대부분인 것은 위 계산으로 확인했지만 배당·
//   수수료·원장 잡음도 여기로 들어온다. 재지 않은 것을 잰 것처럼 부르지 않는다.
//
// ★TWR 은 이제 낸다. 예전 주석에 "일별 현금흐름이 정확해야 해서 못 한다"고
//   적어 두었는데, **연쇄(chain-link)는 그 문제를 피해 간다** — 입금이 있는
//   날도 그날 수익률만 곱하면 되기 때문이다. 다만 이 TWR 은 **주가 기준**이라
//   '성과 분석' 화면의 원화 기준 수익률과 값이 다르다. 기준을 화면에 적는다.
//
// ★2026-09-25 사용자 지시(전체 메뉴 공통 패턴): 오른쪽 월별 **표**를 월별 주가손익
//   **막대**로 바꿨다. 막대를 누르면 그 달의 일별 내역, 헤더 '전체 목록'은 옛 월별
//   표다. 왼쪽 예탁자산·누적손익은 일별 추이라 선 그래프 그대로 둔다.
//
// ★2026-10-04 사용자 지정: 첫 칸과 기본 그래프는 **내 계좌 수익률**(/account-return —
//   시작일 이후 손익 ÷ 투입 원금, 6/01~)이다. 입출금 날은 그래프 아래 세모로 표시한다.
//   연쇄 수익률(TWR)은 '참고: 시간가중(TWR)'으로만 남긴다 — 두 정의를 섞지 않는다.
//   ⚠️옛 '원금 대비 %'(원화 증감 ÷ (시작 + 순입금))는 세 번째 정의라 지웠다.
//
// ★2026-10-05 사용자 지정("5/31 기준으로 통일"): 주가 손익 · 환율 등 · 원화 증감도 첫 칸과
//   **같은 출발점**(05-31 종가 = /account-return 의 A0)에서 센다. 06-01 의 손익도 넣는다.
//   예전엔 06-01 마감을 기준선으로 삼아 그날을 뺐고, 그래서 원화 증감(−69,636)이 첫 칸의
//   원화 실질(−447,590)과 어긋났다. 이제 원화 증감 ÷ 원금 = 첫 칸의 '원화 실질 %' 다.
//   ⚠️그래서 타일·월별 막대는 **기간 칩을 따르지 않는다**(늘 시작일부터) — 칩은 왼쪽 선
//   그래프만 자른다. 칩을 따르게 두면 3개월에서 원화 증감이 첫 칸과 다시 어긋난다.
//   ⚠️끝점은 마지막 일별 행이다. 첫 칸은 미국 휴장이면 그 행 그대로(같은 값), 행 뒤에
//   미국 장이 열렸으면 live 라 행이 올 때까지 그만큼 다를 수 있다.
//   ⚠️주가 손익(키움 일별 손익 합)은 첫 칸 분자(실현 + 평가 − 시작 평가익)와 같은 값이
//   아니다 — 월별 막대·누적손익과 맞추려고 키움 일별 손익 합을 쓴다. 차이는 잔차로 간다.

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function ReturnsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [bridgeOpen, setBridgeOpen] = useState(false);
  const [metric, setMetric] = useState<"return" | "assets" | "cumulative">("return");
  // 막대 → 그 달 일별 내역. 헤더 '전체 목록' → 월별 표.
  const [pickedMonth, setPickedMonth] = useState<string | null>(null);
  const [monthListOpen, setMonthListOpen] = useState(false);

  // ★2026-10-05 늘 시작일부터 받는다(서버가 INVESTMENT_START 아래로 내려가지 않는다).
  //   기간 칩은 아래에서 선 그래프만 자른다.
  const perf = useQuery({
    queryKey: ["performance", accountId, "since-start"],
    queryFn: () => getPerformance(accountId, 3650),
    staleTime: 60_000,
  });

  const account = useQuery({
    queryKey: ["account-return", accountId],
    queryFn: () => getAccountReturn(accountId),
    staleTime: 60_000,
  });

  const data = perf.data;
  const items = useMemo(() => data?.items ?? [], [data]);
  const acct = account.data;
  const accountPct = pctOf(acct?.return_ratio);
  const from = useMemo(
    () => new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10),
    [days],
  );
  // 수익률 그래프도 위 기간 칩을 따른다 — 값은 늘 6/01 부터 센 그대로다.
  const returnPoints = useMemo(
    () => (acct?.items ?? []).filter((p) => p.date >= from),
    [acct, from],
  );
  // 예탁자산 선 그래프도 칩을 따른다(값은 그대로, 앞을 자를 뿐).
  const shownItems = useMemo(() => items.filter((p) => p.base_date >= from), [items, from]);
  const flowMarkers = useMemo(
    () =>
      returnPoints.flatMap((p, index) =>
        p.net_flow_krw == null
          ? []
          : [
              {
                index,
                label: `${Number(p.net_flow_krw) > 0 ? "입금" : "출금"} ${formatKrwSigned(p.net_flow_krw)}`,
                tone: (Number(p.net_flow_krw) > 0 ? "up" : "down") as "up" | "down",
              },
            ],
      ),
    [returnPoints],
  );

  const bridge = data?.bridge ?? null;
  const twrPct =
    bridge?.twr == null
      ? null
      : `${Number(bridge.twr) > 0 ? "+" : ""}${(Number(bridge.twr) * 100).toFixed(2)}%`;

  // ⚠️누적손익은 **증권사 값을 쓰지 않는다.** acum_pl_amt 는 조회 창 경계에서
  //   그날 손익으로 초기화된다(실측: 2025-09-18, 2026-09-14 — 누적이
  //   2,274,791 → −1,836,144 로 뛰는데 그 값이 그날 손익과 정확히 같다).
  //   차트로 그리면 없던 절벽이 생긴다. 일별 손익을 직접 누적한다 —
  //   그러면 끝값이 상단 '주가 손익' 타일과 정확히 같아진다.
  // ★2026-10-05 06-01 손익부터 넣는다(시작 = 05-31 종가). 누적은 시작일부터 세고,
  //   칩은 그 뒤에 앞을 자른다 — 그래야 끝값이 칩과 상관없이 타일과 같다.
  const cumulativePnl = useMemo(() => {
    let sum = 0;
    return items
      .map((p) => {
        sum += Number(p.pnl_krw ?? 0);
        return { date: p.base_date, value: sum };
      })
      .filter((p) => p.date >= from);
  }, [items, from]);

  // 월별 집계 — 월말 예탁자산과 그 달의 **주가** 손익 합.
  // ★2026-10-05 첫날(06-01) 손익도 6월에 넣는다 — 상단 '주가 손익' 타일이 05-31 종가
  //   기준으로 06-01 부터 세므로, 막대 합 = 타일. (예전엔 둘 다 첫날을 뺐다.)
  const monthly = useMemo(() => aggregateMonthly(items), [items]);
  // 막대는 왼쪽이 과거다(표는 최근 달이 위).
  const monthColumns = useMemo(
    () =>
      [...monthly]
        .reverse()
        .map((m) => ({ key: m.month, label: m.month, value: m.pnl })),
    [monthly],
  );
  const monthPicked = monthly.find((m) => m.month === pickedMonth) ?? null;
  const monthDays = useMemo(
    () => items.filter((p) => p.base_date.startsWith(pickedMonth ?? "—")),
    [items, pickedMonth],
  );

  return (
    <>
      <Topbar title="수익률 추이" subtitle="내 계좌 수익률 · 예탁자산 · 누적손익" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="계좌 성과" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {/* ⚠️타일 넷은 **왼쪽에서 오른쪽으로 이어진다.**
              주가 손익 + 환율 등 = 원화 증감. 셋을 따로 읽지 말 것. */}
          {/* ★정본 — 시작일 이후 손익 ÷ 투입 원금(A0 + 순외부입금). */}
          <StatTile
            // ★2026-10-05 이름은 벤치마크 화면과 같게, 기간(MM-DD ~ MM-DD)은 다른 성과 화면처럼 hint 로.
            label="내 계좌 (환율 제외)"
            value={accountPct}
            // ★2026-10-04 "둘 다 표시": 위 값은 환율 제외(키움 손익). 원화 실질(환차 포함,
            //   총자산 − 원금)을 보조로 같이 적는다.
            //   ★2026-10-05 한 줄이면 잘린다(1280px 실측) — 손익 ÷ 원금 / 기간·원화 실질 두 줄로.
            hint={
              acct?.pnl_since_start_krw != null && acct.invested_krw != null
                ? `${Number(acct.pnl_since_start_krw) > 0 ? "+" : ""}${formatKrwCompactString(acct.pnl_since_start_krw)} ÷ 원금 ${formatKrwCompactString(acct.invested_krw)}`
                : "시작일 이후 손익 ÷ 투입 원금"
            }
            subHint={
              [
                acct?.return_date ? `${acct.start.slice(5)} ~ ${acct.return_date.slice(5)}` : null,
                acct?.krw_return_ratio != null ? `원화 실질 ${pctOf(acct.krw_return_ratio)}` : null,
              ]
                .filter(Boolean)
                .join(" · ") || undefined
            }
            accent="auto"
            loading={account.isLoading}
          />
          <StatTile
            label="주가 손익"
            value={formatKrwSigned(bridge?.price_pnl_krw)}
            hint={
              twrPct == null
                ? "환율 제외 · 증권사 일별 손익 합"
                : `환율 제외 · 참고: 시간가중(TWR) ${twrPct}`
            }
            actionHint="눌러서 월별 표 보기"
            onClick={() => {
              setPickedMonth(null);
              setMonthListOpen(true);
            }}
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="환율 등"
            value={formatKrwSigned(bridge?.fx_effect_krw)}
            hint="잔차"
            actionHint="눌러서 상세 보기"
            onClick={() => setBridgeOpen(true)}
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="원화 증감 (합)"
            value={formatKrwSigned(data?.gain_krw)}
            // ★2026-10-05 시작자산 = 05-31 종가(첫 칸의 A0). 이 값 ÷ 원금 = 첫 칸 '원화 실질'.
            hint={`끝자산 − 시작자산(${data?.start_base_date?.slice(5) ?? "—"} 종가) − 순입금`}
            actionHint="눌러서 이어지는 법 보기"
            onClick={() => setBridgeOpen(true)}
            accent="auto"
            loading={perf.isLoading}
          />
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {RANGES.map((r) => (
            <HeaderChip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
              {r.label}
            </HeaderChip>
          ))}
          <span className="mx-1 h-4 w-px bg-hairline" />
          <HeaderChip active={metric === "return"} onClick={() => setMetric("return")}>
            수익률
          </HeaderChip>
          <HeaderChip active={metric === "assets"} onClick={() => setMetric("assets")}>
            예탁자산
          </HeaderChip>
          <HeaderChip active={metric === "cumulative"} onClick={() => setMetric("cumulative")}>
            누적손익
          </HeaderChip>
          {shownItems.length > 0 && (
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {shownItems[0].base_date} ~ {shownItems[shownItems.length - 1].base_date} ({shownItems.length}일)
            </span>
          )}
        </div>

        {/* ★2026-09-22 전체 점검에서 걸렸다: `wide` 로 남아 페이지가 스크롤됐다.
            '여기서 하지 않는 것' 카드는 카드 자리를 차지하는 대신 헤더 버튼 →
            팝업으로 옮겼다(다른 화면과 같은 규약). */}
        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            // ⚠️lg(1024)에서 가르면 오른쪽 월별 표가 좁아 잘린다. xl 부터 가른다.
            "md:grid-cols-2 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] xl:auto-rows-auto",
          )}
        >
          <StubCard
            title={
              metric === "return"
                ? "내 계좌 수익률 추이"
                : metric === "assets"
                  ? "예탁자산 추이"
                  : "누적손익 추이"
            }
            subtitle={
              metric === "return"
                ? "시작일 이후 손익 ÷ 투입 원금 · ▲입금 ▼출금"
                : metric === "assets"
                  ? "현금 + 주식 평가 (원화 환산)"
                  : "일별 주가손익 누적 (환율 제외)"
            }
            className="min-h-0"
            scrollBody
          >
            {metric === "return" ? (
              returnPoints.length > 0 ? (
                <SeriesChart
                  height={300}
                  includeZero
                  markers={flowMarkers}
                  valueFormat={(v) => `${v.toFixed(1)}%`}
                  points={returnPoints.map((p) => ({
                    date: p.date,
                    value: p.return_ratio == null ? null : Number(p.return_ratio) * 100,
                  }))}
                  tooltipFormat={(p) => {
                    const row = returnPoints.find((r) => r.date === p.date);
                    return `${p.value == null ? "—" : `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`} · 손익 ${formatKrwSigned(row?.pnl_since_start_krw)} ÷ 원금 ${formatKrwString(row?.invested_krw)} · 원화 실질 ${pctOf(row?.krw_return_ratio) ?? "—"}`;
                  }}
                />
              ) : (
                <div className="flex h-[300px] items-center justify-center text-[12px] font-semibold text-ink-faint">
                  {account.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
                </div>
              )
            ) : shownItems.length > 0 ? (
              <SeriesChart
                height={300}
                includeZero={metric === "cumulative"}
                points={metric === "assets"
                  ? shownItems.map((p) => ({
                      date: p.base_date,
                      value:
                        p.deposit_assets_krw == null
                          ? null
                          : Number(p.deposit_assets_krw),
                    }))
                  : cumulativePnl}
                tooltipFormat={(p) =>
                  formatKrwString(p.value == null ? null : String(Math.round(p.value)))
                }
              />
            ) : (
              <div className="flex h-[300px] items-center justify-center text-[12px] font-semibold text-ink-faint">
                {perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
              </div>
            )}
          </StubCard>

          {/* ⚠️'월 손익'이 아니라 '월 주가손익'이다. 왼쪽 예탁자산은 원화
              환산액이고 이 칸은 환율이 빠진 주가 손익이라, 이름을 같게 두면
              "왜 자산은 줄었는데 손익은 플러스냐"가 된다. */}
          <StubCard
            title="월별 주가손익"
            subtitle="환율 제외 · 막대를 누르면 그 달 일별 내역"
            className="min-h-0"
            scrollBody
            action={
              <ListButton
                onClick={() => {
                  setPickedMonth(null);
                  setMonthListOpen(true);
                }}
              />
            }
          >
            {perf.isLoading ? (
              <div className="flex h-full items-center justify-center text-[12px] font-semibold text-ink-faint">
                불러오는 중…
              </div>
            ) : (
              <SignedBarChart
                columns={monthColumns}
                height={300}
                formatValue={(v) => formatKrwSigned(String(Math.round(v)))}
                selected={pickedMonth}
                onPick={setPickedMonth}
              />
            )}
          </StubCard>
        </div>
      </PageContainer>

      {/* ── 막대 → 그 달 일별 내역 ───────────────────────────────────────── */}
      <Modal
        open={monthPicked != null}
        onClose={() => setPickedMonth(null)}
        title={monthPicked ? `${monthPicked.month} 일별` : ""}
        subtitle={
          monthPicked
            ? `월 주가손익 ${formatKrwSigned(String(Math.round(monthPicked.pnl)))} · 월말 예탁자산 ${formatKrwString(String(Math.round(monthPicked.assets)))}`
            : undefined
        }
        width={720}
      >
        {monthPicked && <MonthDays days={monthDays} />}
      </Modal>

      {/* ── 헤더 '전체 목록' → 옛 월별 표 ───────────────────────────────── */}
      <Modal
        open={monthListOpen}
        onClose={() => setMonthListOpen(false)}
        title="월별"
        subtitle="월말 자산(원화) · 주가손익(환율 제외) · 행을 누르면 그 달 일별"
        width={620}
      >
        <div className="max-h-[60vh] overflow-y-auto">
          <DataTable
            columns={["월", "월말 예탁자산", "월 주가손익"]}
            align={["left", "right", "right"]}
            empty={perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
          >
            {monthly.map((m) => (
              <tr
                key={m.month}
                onClick={() => {
                  setMonthListOpen(false);
                  setPickedMonth(m.month);
                }}
                className="cursor-pointer border-b border-hairline transition-colors hover:bg-canvas-soft"
              >
                <Cell left strong>
                  {m.month}
                </Cell>
                <Cell>{formatKrwString(String(Math.round(m.assets)))}</Cell>
                <Cell tone={toneOf(String(m.pnl))}>
                  {formatKrwSigned(String(Math.round(m.pnl)))}
                </Cell>
              </tr>
            ))}
          </DataTable>
        </div>
      </Modal>

      <Modal
        open={bridgeOpen}
        onClose={() => setBridgeOpen(false)}
        title="이 숫자들이 어떻게 이어지나"
        subtitle="주가 손익 + 환율 등 = 원화 증감"
      >
        <div className="mb-3 rounded-xl border border-hairline bg-canvas-soft/60 p-3">
          <BridgeRow label="주가 손익" value={bridge?.price_pnl_krw} note="증권사 일별 손익 합" />
          <BridgeRow label="환율 등 (잔차)" value={bridge?.fx_effect_krw} note="남는 차이" />
          <div className="mt-1.5 border-t border-hairline pt-1.5">
            <BridgeRow label="원화 증감" value={bridge?.asset_change_krw} note="끝자산 − 시작자산 − 순입금" strong />
          </div>
        </div>
        {/* ★2026-10-05 출발점·끝점을 적는다 — 첫 칸(내 계좌)과 같은 05-31 종가에서 센다. */}
        {data?.start_base_date && (
          <p className="text-[11px] font-medium leading-snug text-ink-muted">
            시작자산 {data.start_base_date} 종가 {formatKrwString(data.start_assets_krw)} → 끝자산{" "}
            {data.last_date} {formatKrwString(data.end_assets_krw)} · 순입금{" "}
            {formatKrwSigned(data.net_deposit_krw)}. 첫 칸 &apos;원화 실질&apos;과 같은 출발점이다.
          </p>
        )}
      </Modal>
    </>
  );
}

/** 그 달의 일별 행. 막대가 월로 묶어 잃은 '어느 날'을 여기서 돌려준다. */
function MonthDays({ days }: { days: DailyPerformancePoint[] }) {
  return (
    <div className="space-y-2">
      <div className="max-h-[56vh] overflow-y-auto">
        <DataTable
          columns={["날짜", "예탁자산", "주가손익", "입금", "출금"]}
          empty="이 달에는 일별 성과가 없습니다"
        >
          {/* ★2026-10-05 기준선이 05-31 종가로 옮겨 가 06-01 도 세는 날이다 — '기준선' 표시를 뗐다. */}
          {days.map((p) => (
            <tr key={p.base_date} className="border-b border-hairline">
              <Cell left>{p.base_date}</Cell>
              <Cell>{formatKrwString(p.deposit_assets_krw)}</Cell>
              <Cell tone={toneOf(p.pnl_krw)}>
                {formatKrwSigned(p.pnl_krw)}
              </Cell>
              <Cell tone={Number(p.deposit_krw ?? 0) ? "up" : "muted"}>
                {formatKrwString(p.deposit_krw)}
              </Cell>
              <Cell tone={Number(p.withdrawal_krw ?? 0) ? "down" : "muted"}>
                {formatKrwString(p.withdrawal_krw)}
              </Cell>
            </tr>
          ))}
        </DataTable>
      </div>
    </div>
  );
}

/** 비율 문자열(0.0796) → "+7.96%". 모르면 null(타일이 '—' 로 그린다). */
function pctOf(value: string | null | undefined): string | null {
  if (value == null) return null;
  const n = Number(value) * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function BridgeRow({
  label,
  value,
  note,
  strong,
}: {
  label: string;
  value: string | null | undefined;
  note: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between py-0.5">
      <span
        className={cn(
          "text-[12px]",
          strong ? "font-extrabold text-ink" : "font-semibold text-ink-secondary",
        )}
      >
        {label}
        <span className="ml-1.5 text-[10px] font-medium text-ink-faint">{note}</span>
      </span>
      <span
        className={cn(
          "tabular-nums",
          strong ? "text-[15px] font-extrabold" : "text-[13px] font-bold",
          toneOf(value ?? null) === "up"
            ? "text-bid"
            : toneOf(value ?? null) === "down"
              ? "text-ask"
              : "text-ink",
        )}
      >
        {formatKrwSigned(value)}
      </span>
    </div>
  );
}

/** 월말 예탁자산과 그 달 주가손익 합. 최근 달이 위로. */
function aggregateMonthly(items: { base_date: string; deposit_assets_krw: string | null; pnl_krw: string | null }[]) {
  const acc = new Map<string, { month: string; assets: number; pnl: number }>();
  items.forEach((p) => {
    const month = p.base_date.slice(0, 7);
    const entry = acc.get(month) ?? { month, assets: 0, pnl: 0 };
    // 마지막으로 본 값이 월말 값이다(items 는 날짜 오름차순).
    if (p.deposit_assets_krw != null) entry.assets = Number(p.deposit_assets_krw);
    // ★2026-10-05 첫날(06-01)도 센다 — 기준선은 서버가 붙인 05-31 종가다(items 밖).
    entry.pnl += Number(p.pnl_krw ?? 0);
    acc.set(month, entry);
  });
  return [...acc.values()].reverse();
}

