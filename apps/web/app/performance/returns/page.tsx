"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { useAccount } from "@/components/layout/account-context";
import { Modal } from "@/components/ui/modal";
import { SeriesChart } from "@/components/charts/series-chart";
import {
  Cell,
  DataTable,
  NotConnectedBanner,
  PlannedList,
  StatTile,
  StubCard,
  toneOf,
} from "@/components/stub";
import { getPerformance } from "@/lib/api";
import { formatKrwSigned, formatKrwString } from "@/lib/format";
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

const RANGES = [
  { id: 90, label: "3개월" },
  { id: 180, label: "6개월" },
  { id: 365, label: "1년" },
  { id: 1000, label: "전체" },
];

export default function ReturnsPage() {
  const { accountId, connected } = useAccount();
  const [days, setDays] = useState(365);
  const [notesOpen, setNotesOpen] = useState(false);
  const [bridgeOpen, setBridgeOpen] = useState(false);
  const [metric, setMetric] = useState<"assets" | "cumulative">("assets");

  const perf = useQuery({
    queryKey: ["performance", accountId, days],
    queryFn: () => getPerformance(accountId, days),
    staleTime: 60_000,
  });

  const data = perf.data;
  const items = data?.items ?? [];

  // 원금(순입금) 대비 증감률. 분모가 0이면 계산하지 않는다.
  const netDeposit = Number(data?.net_deposit_krw ?? 0);
  const start = Number(data?.start_assets_krw ?? 0);
  const base = start + netDeposit;
  const gain = data?.gain_krw == null ? null : Number(data.gain_krw);
  const gainRate = gain != null && base > 0 ? (gain / base) * 100 : null;

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
  const cumulativePnl = useMemo(() => {
    let sum = 0;
    return items.map((p, index) => {
      if (index > 0) sum += Number(p.pnl_krw ?? 0);
      return { date: p.base_date, value: sum };
    });
  }, [items]);

  // 월별 집계 — 월말 예탁자산과 그 달의 **주가** 손익 합.
  // ⚠️첫날 손익은 뺀다. 상단 '주가 손익' 타일도 빼고 세므로, 넣으면 표의 합과
  //   타일이 어긋난다(실측 차이 ₩11,369 = 2026-06-04 의 손익).
  const monthly = aggregateMonthly(items);

  return (
    <>
      <Topbar title="수익률 추이" subtitle="예탁자산 · 누적손익" />
      <PageContainer fit>
        {!connected && <NotConnectedBanner what="계좌 성과" />}

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          {/* ⚠️타일 넷은 **왼쪽에서 오른쪽으로 이어진다.**
              주가 손익 + 환율 등 = 원화 증감. 셋을 따로 읽지 말 것. */}
          <StatTile
            label="현재 예탁자산"
            value={formatKrwString(data?.end_assets_krw)}
            hint={
              data?.net_deposit_krw
                ? `${data.last_date} · 구간 순입금 ${formatKrwString(data.net_deposit_krw)}`
                : (data?.last_date ?? undefined)
            }
            loading={perf.isLoading}
          />
          <StatTile
            label="주가 손익"
            value={formatKrwSigned(bridge?.price_pnl_krw)}
            hint={
              twrPct == null
                ? "환율 제외 · 증권사 일별 손익 합"
                : `환율 제외 · 연쇄 수익률 ${twrPct} (${bridge?.twr_days}일)`
            }
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="환율 등"
            value={formatKrwSigned(bridge?.fx_effect_krw)}
            hint="잔차 · 눌러서 설명"
            actionHint="눌러서 읽는 법 보기"
            onClick={() => setBridgeOpen(true)}
            accent="auto"
            loading={perf.isLoading}
          />
          <StatTile
            label="원화 증감 (합)"
            value={formatKrwSigned(data?.gain_krw)}
            hint={
              gainRate == null
                ? "끝자산 − 시작자산 − 순입금"
                : `${gainRate > 0 ? "+" : ""}${gainRate.toFixed(2)}% · 원금 대비`
            }
            accent="auto"
            loading={perf.isLoading}
          />
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {RANGES.map((r) => (
            <Chip key={r.id} active={days === r.id} onClick={() => setDays(r.id)}>
              {r.label}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-hairline" />
          <Chip active={metric === "assets"} onClick={() => setMetric("assets")}>
            예탁자산
          </Chip>
          <Chip active={metric === "cumulative"} onClick={() => setMetric("cumulative")}>
            누적손익
          </Chip>
          {data?.first_date && (
            <span className="ml-auto text-[11px] font-semibold text-ink-faint">
              {data.first_date} ~ {data.last_date} ({items.length}일)
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
            title={metric === "assets" ? "예탁자산 추이" : "누적손익 추이"}
            subtitle={
              metric === "assets"
                ? "현금 + 주식 평가 (원화 환산)"
                : "일별 주가손익 누적 (환율 제외)"
            }
            className="min-h-0"
            scrollBody
            action={
              <button
                type="button"
                onClick={() => setNotesOpen(true)}
                className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold text-white transition-colors hover:bg-white/25"
              >
                이 화면의 범위
              </button>
            }
          >
            {items.length > 0 ? (
              <SeriesChart
                height={300}
                includeZero={metric === "cumulative"}
                points={metric === "assets"
                  ? items.map((p) => ({
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
            title="월별"
            subtitle="월말 자산(원화) · 주가손익"
            className="min-h-0"
            scrollBody
          >
            <DataTable
              columns={["월", "월말 예탁자산", "월 주가손익"]}
              align={["left", "right", "right"]}
              empty={perf.isLoading ? "불러오는 중…" : "데이터가 없습니다"}
            >
              {monthly.map((m) => (
                <tr
                  key={m.month}
                  className="border-t border-hairline transition-colors hover:bg-canvas-soft/60"
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
          </StubCard>

        </div>
      </PageContainer>

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

        <ul className="space-y-2.5 text-[12px] leading-relaxed text-ink-secondary">
          <li>
            <strong>같은 계좌인데 왜 부호가 다른가.</strong> 예탁자산은{" "}
            <strong>원화 환산액</strong>이고, 증권사가 주는 일별 손익은{" "}
            <strong>주가 손익</strong>입니다. 환율이 빠지면 종목이 그대로여도 원화
            자산은 줄어듭니다. 둘 다 맞는 말이고, 재는 것이 다를 뿐입니다.
          </li>
          <li>
            <strong>&apos;환율 등&apos;은 잔차입니다.</strong> 환율이라고 단정하지
            않았습니다 — 배당·수수료·원장 잡음도 여기로 들어옵니다. 다만 대부분이
            환율인 것은 확인했습니다: 이 구간 USD/KRW 가 1,530.11 → 1,384.86 으로
            9.49% 빠졌고, 잔차를 9.49% 로 나누면 구간 평균 주식평가액과 거의
            같습니다.
          </li>
          <li>
            <strong>연쇄 수익률(TWR)은 주가 기준입니다.</strong> 하루치 수익률을
            차례로 곱해 구하므로 입금이 있는 날도 왜곡되지 않습니다.
            {bridge?.twr_days ? ` ${bridge.twr_days}일을 곱했습니다.` : ""}
            {bridge?.unmeasured_days
              ? ` 전일 자산이 없어 못 센 날이 ${bridge.unmeasured_days}일 있습니다.`
              : ""}
            {bridge?.missing_pnl_days
              ? ` 손익 칸이 비어 있던 날이 ${bridge.missing_pnl_days}일 있습니다(0 으로 치지 않았습니다).`
              : ""}{" "}
            &apos;성과 분석&apos; 화면의 수익률은 <strong>원화 기준</strong>이라
            숫자가 다릅니다.
          </li>
          <li>
            <strong>첫날은 기준선입니다.</strong> 첫날의 손익도, 첫날의 입금도
            세지 않습니다 — 둘 다 첫날 마감 자산에 이미 들어 있어서 또 더하면 두 번
            세는 것이 됩니다.
          </li>
          <li>
            <strong>누적손익 차트는 증권사 누적값을 쓰지 않습니다.</strong>{" "}
            증권사의 누적손익은 조회 창 경계에서 그날 손익으로 초기화됩니다 —
            실측으로 2026-09-14 에 2,274,791 에서 −1,836,144 로 뛰는데 그 값이
            그날 손익과 정확히 같았습니다. 그대로 그리면 없던 절벽이 생기므로,
            일별 손익을 직접 누적했습니다. 그래서 차트의 끝값이 위 &apos;주가
            손익&apos;과 정확히 같습니다.
          </li>
        </ul>
      </Modal>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면의 범위"
        subtitle="여기서 하지 않는 것과, 그걸 하는 화면"
      >
        {/* ⚠️2026-09-22 정정: 예전엔 "TWR·벤치마크·리스크 지표는 하지 않는다"고
            적혀 있었는데 **그 뒤에 전부 만들었다.** 화면이 사실과 다른 말을
            하고 있었다. 안 하는 이유가 아니라 **어디서 하는지**를 적는다. */}
        <PlannedList
          items={[
            "여기는 **금액**을 본다 — 예탁자산과 주가손익의 추이. 입출금이 섞이면 금액은 늘지만 잘 굴린 것은 아니라서, 입출금을 빼고 낸다",
            "상단의 연쇄 수익률은 **주가 기준(환율 제외)** 이다. 변동성·MDD·샤프와 기간 수익률은 '성과 분석' 화면에서 보는데 그쪽은 **원화 기준**이라 숫자가 다르다 — 기준이 다르면 값도 다르다",
            "S&P 500·필라델피아 반도체 대비는 '벤치마크 비교' 화면에서 본다 (원화 환산 기준)",
            "월·분기·연도를 잘라 보는 것은 '기간 리포트' 화면이다",
            "환차손익을 종목별로 보는 것은 '환노출' 화면이다 — 여기 '환율 등'은 계좌 전체의 잔차다",
          ]}
        />
      </Modal>
    </>
  );
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
  items.forEach((p, index) => {
    const month = p.base_date.slice(0, 7);
    const entry = acc.get(month) ?? { month, assets: 0, pnl: 0 };
    // 마지막으로 본 값이 월말 값이다(items 는 날짜 오름차순).
    if (p.deposit_assets_krw != null) entry.assets = Number(p.deposit_assets_krw);
    // ⚠️첫날은 기준선이다 — 그날 손익은 이미 첫날 마감 자산에 들어 있다.
    if (index > 0) entry.pnl += Number(p.pnl_krw ?? 0);
    acc.set(month, entry);
  });
  return [...acc.values()].reverse();
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-lg border px-2.5 py-1 text-[11px] font-bold transition-colors",
        active
          ? "border-ge-point bg-ge-blue-bg text-ge-point"
          : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {children}
    </button>
  );
}
