"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Modal } from "@/components/ui/modal";
import { Cell, DataTable, Emphasized, StatTile, StubCard } from "@/components/stub";
import {
  createAlert,
  deleteAlert,
  getAlerts,
  updateAlert,
  type AlertKind,
  type AlertRule,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 알림 — 조건을 세워 두고 지금 충족하는지 본다.
//
// ★**아직 보내지 않는다.** 텔레그램 등 전달 경로가 연결돼야 실제로 알림이 간다.
//   그래도 규칙을 세우고 판정하는 부분은 지금 데이터로 전부 되므로, 전달이
//   붙으면 이 판정 결과를 보내기만 하면 된다 — 규칙을 다시 만들 필요가 없다.
//   화면은 어디에서도 "보냈다"고 말하지 않는다.
//
// ⚠️상태가 셋이다 — 충족 / 미충족 / **판정 불가**. 시세를 못 받았거나 보유하지
//   않은 종목이면 '미충족'이 아니라 판정 불가다. 잴 수 없는데 괜찮다고 하면
//   그게 더 나쁘다.

const STATE_STYLE: Record<string, { label: string; cls: string }> = {
  TRIGGERED: { label: "충족", cls: "bg-ask-soft text-ask" },
  OK: { label: "미충족", cls: "bg-canvas-soft text-ink-faint" },
  UNKNOWN: { label: "판정 불가", cls: "bg-ge-point/12 text-ge-point" },
};

/** 임계값 입력은 단위마다 뜻이 다르다. 화면에서는 %로 받고 저장은 소수로 한다. */
function toStored(unit: string | null, raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  return unit === "percent" ? String(n / 100) : String(n);
}

function toDisplay(unit: string | null, stored: string | null): string {
  if (stored == null) return "";
  const n = Number(stored);
  if (!Number.isFinite(n)) return stored;
  return unit === "percent" ? String(Number((n * 100).toFixed(4))) : String(n);
}

function unitSuffix(unit: string | null): string {
  if (unit === "percent") return "%";
  if (unit === "days") return "일";
  if (unit === "price") return "$";
  return "";
}

export default function AlertsPage() {
  const qc = useQueryClient();
  const [notesOpen, setNotesOpen] = useState(false);
  const [kind, setKind] = useState<string>("PRICE_ABOVE");
  const [ticker, setTicker] = useState("");
  const [threshold, setThreshold] = useState("");
  const [memo, setMemo] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: getAlerts,
    // 판정은 볼 때마다 지금 시세로 다시 한다. 서버가 계산하므로 자주 묻지 않는다.
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const data = alerts.data;
  const kinds = data?.kinds ?? [];
  const spec: AlertKind | undefined = useMemo(
    () => kinds.find((k) => k.key === kind),
    [kinds, kind],
  );

  const invalidate = () => qc.invalidateQueries({ queryKey: ["alerts"] });
  const create = useMutation({
    mutationFn: createAlert,
    onSuccess: () => {
      setTicker("");
      setThreshold("");
      setMemo("");
      setFormError(null);
      invalidate();
    },
    onError: (e: unknown) =>
      setFormError(e instanceof Error ? e.message : "규칙을 만들지 못했습니다."),
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateAlert(id, { enabled }),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: deleteAlert, onSuccess: invalidate });

  const rules = data?.rules ?? [];
  const triggered = rules.filter((r) => r.state === "TRIGGERED");

  return (
    <>
      <Topbar title="알림" subtitle="조건을 세워 두고 지금 충족하는지 본다" showAccountContext={false} />
      <PageContainer fit>
        {/* ⚠️맨 위에 둔다 — 이걸 모르면 "알림이 오는 줄" 알게 된다.
            ⚠️2026-09-23 정정: "이 화면에서만 판정한다"는 이제 **사실이 아니다.**
              상단 바의 종이 어느 화면에서든 걸린 개수를 보여 준다. 화면이
              스스로에 대해 틀린 말을 하고 있었다 — 기능을 만들면 그걸 설명하는
              문구도 같이 고쳐야 한다. */}
        <div className="flex shrink-0 items-center gap-2 rounded-xl border border-ge-point/25 bg-ge-point/5 px-3 py-2">
          <span className="rounded bg-ge-point/15 px-1.5 py-0.5 text-[10px] font-extrabold text-ge-point">
            앱 안에서만
          </span>
          <span className="text-[11px] font-semibold leading-snug text-ink-secondary">
            <strong>밖으로는 아직 보내지 않습니다.</strong> 텔레그램 같은 전달
            경로가 연결돼야 앱을 안 켜 놓은 동안에도 알림이 갑니다. 지금은 상단 바의{" "}
            <strong>종</strong>이 유일한 전달 경로입니다 — 어느 화면에 있든 걸린
            개수가 배지로 뜹니다.
          </span>
          <button
            type="button"
            onClick={() => setNotesOpen(true)}
            className="ml-auto shrink-0 rounded-full bg-ge-point/10 px-2.5 py-1 text-[11px] font-bold text-ge-point transition-colors hover:bg-ge-point/20"
          >
            읽는 법
          </button>
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-2.5 lg:grid-cols-4">
          <StatTile
            label="지금 충족"
            value={data ? `${data.triggered_count}건` : null}
            hint={data ? `규칙 ${rules.length}개 중` : "조건을 만족하는 규칙"}
            accent={data && data.triggered_count > 0 ? "down" : undefined}
            loading={alerts.isLoading}
          />
          <StatTile
            label="판정 불가"
            value={data ? `${data.unknown_count}건` : null}
            hint="시세 결측 · 미보유 등"
            actionHint="눌러서 왜인지 보기"
            onClick={() => setNotesOpen(true)}
            loading={alerts.isLoading}
          />
          <StatTile
            label="꺼둔 규칙"
            value={data ? `${data.disabled_count}개` : null}
            hint="지우지 않고 잠시 끈 것"
            loading={alerts.isLoading}
          />
          <StatTile
            label="전달 설정"
            value={data ? (data.delivery_configured ? "연결됨" : "없음") : null}
            hint="텔레그램 등 — 아직 없음"
            loading={alerts.isLoading}
          />
        </div>

        <div
          className={cn(
            "grid min-h-0 flex-1 gap-3",
            "grid-cols-1 auto-rows-[minmax(0,1fr)]",
            "md:grid-cols-2 lg:auto-rows-auto",
            "lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]",
          )}
        >
          <StubCard
            title="규칙"
            subtitle={`${rules.length}개 · 충족 ${triggered.length}`}
            scrollBody
          >
            <DataTable
              columns={["상태", "종목", "조건", "지금", ""]}
              align={["left", "left", "left", "left", "right"]}
              empty={
                alerts.isLoading
                  ? "불러오는 중…"
                  : "오른쪽에서 첫 규칙을 만들어 보세요"
              }
            >
              {rules.map((r) => (
                <RuleRow
                  key={r.id}
                  rule={r}
                  onToggle={() =>
                    toggle.mutate({ id: r.id, enabled: !r.enabled })
                  }
                  onDelete={() => remove.mutate(r.id)}
                  busy={toggle.isPending || remove.isPending}
                />
              ))}
            </DataTable>
          </StubCard>

          <StubCard title="규칙 만들기" subtitle="조건을 세운다" scrollBody>
            <form
              className="space-y-2.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!spec) return;
                setFormError(null);
                create.mutate({
                  kind,
                  ticker: spec.needs_ticker ? ticker.trim().toUpperCase() : null,
                  threshold:
                    spec.unit == null ? null : toStored(spec.unit, threshold),
                  memo: memo.trim() || null,
                });
              }}
            >
              <label className="block">
                <span className="mb-1 block text-[11px] font-bold text-ge-navy">
                  종류
                </span>
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  className="w-full rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ink"
                >
                  {kinds.map((k) => (
                    <option key={k.key} value={k.key}>
                      {k.label}
                    </option>
                  ))}
                </select>
                {spec && (
                  <span className="mt-1 block text-[11px] leading-snug text-ink-muted">
                    {spec.hint}
                  </span>
                )}
              </label>

              {spec?.needs_ticker && (
                <label className="block">
                  <span className="mb-1 block text-[11px] font-bold text-ge-navy">
                    종목
                  </span>
                  <input
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value)}
                    placeholder="NVDA"
                    className="w-full rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold uppercase text-ink placeholder:font-normal placeholder:normal-case placeholder:text-ink-faint"
                  />
                </label>
              )}

              {spec?.unit && (
                <label className="block">
                  <span className="mb-1 block text-[11px] font-bold text-ge-navy">
                    기준값 ({unitSuffix(spec.unit)})
                  </span>
                  <input
                    value={threshold}
                    onChange={(e) => setThreshold(e.target.value)}
                    inputMode="decimal"
                    placeholder={
                      spec.unit === "percent"
                        ? "5"
                        : spec.unit === "days"
                          ? "7"
                          : "200"
                    }
                    className="w-full rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] font-semibold tabular-nums text-ink placeholder:font-normal placeholder:text-ink-faint"
                  />
                  {spec.unit === "percent" && (
                    // ⚠️백분율로 받고 소수로 저장한다. 안 적으면 0.05 를 5% 로
                    //   쓰려다 0.05% 규칙을 만들게 된다.
                    <span className="mt-1 block text-[11px] text-ink-muted">
                      퍼센트로 적으세요 — 5 는 5% 입니다. 손실 기준은 −10 처럼
                      음수로.
                    </span>
                  )}
                </label>
              )}

              <label className="block">
                <span className="mb-1 block text-[11px] font-bold text-ge-navy">
                  메모
                </span>
                <input
                  value={memo}
                  onChange={(e) => setMemo(e.target.value)}
                  placeholder="왜 이 조건을 걸었나"
                  className="w-full rounded-lg border border-hairline bg-canvas px-2.5 py-1.5 text-[12px] text-ink placeholder:text-ink-faint"
                />
              </label>

              {formError && (
                <p className="rounded-lg bg-ask-soft px-2.5 py-2 text-[11px] font-semibold text-ask">
                  {formError}
                </p>
              )}

              <button
                type="submit"
                disabled={create.isPending}
                className="w-full rounded-lg bg-ge-navy px-3 py-2 text-[12px] font-bold text-white transition-colors hover:bg-ge-navy/90 disabled:opacity-50"
              >
                {create.isPending ? "만드는 중…" : "규칙 추가"}
              </button>
            </form>
          </StubCard>
        </div>
      </PageContainer>

      <Modal
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        title="이 화면 읽는 법"
        subtitle="무엇이 되고 무엇이 아직 안 되나"
      >
        <ul className="space-y-2">
          {(data?.notes ?? []).map((text) => (
            <li key={text} className="flex items-start gap-2.5">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ge-point/50" />
              <span className="text-[12px] font-medium leading-snug text-ink-secondary">
                <Emphasized text={text} />
              </span>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

function RuleRow({
  rule,
  onToggle,
  onDelete,
  busy,
}: {
  rule: AlertRule;
  onToggle: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const style = STATE_STYLE[rule.state] ?? STATE_STYLE.UNKNOWN;
  return (
    <tr className={cn("border-b border-hairline", !rule.enabled && "opacity-55")}>
      <Cell left strong>
        <span
          className={cn(
            "inline-block shrink-0 rounded px-1.5 py-0.5 text-[10px] font-extrabold",
            rule.enabled ? style.cls : "bg-canvas-soft text-ink-faint",
          )}
        >
          {rule.enabled ? style.label : "꺼짐"}
        </span>
      </Cell>
      <Cell left strong>
        {rule.ticker ? (
          <span className="flex items-center gap-1.5">
            <span className="max-w-[90px] truncate">{rule.name ?? rule.ticker}</span>
            <span className="shrink-0 text-[10px] font-bold text-ink-faint">
              {rule.ticker}
            </span>
          </span>
        ) : (
          <span className="text-ink-faint">전체</span>
        )}
      </Cell>
      <Cell left>
        <span className="block text-[11px] font-bold text-ink">{rule.kind_label}</span>
        {rule.memo && (
          <span className="block max-w-[150px] truncate text-[10px] text-ink-faint">
            {rule.memo}
          </span>
        )}
      </Cell>
      <Cell left tone="muted">
        <span className="block max-w-[260px] truncate text-[11px]" title={rule.message}>
          {rule.message}
        </span>
      </Cell>
      <Cell>
        <span className="flex justify-end gap-1">
          <button
            type="button"
            onClick={onToggle}
            disabled={busy}
            className="rounded px-1.5 py-0.5 text-[10px] font-bold text-ink-muted transition-colors hover:bg-canvas-soft disabled:opacity-40"
          >
            {rule.enabled ? "끄기" : "켜기"}
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="rounded px-1.5 py-0.5 text-[10px] font-bold text-ask transition-colors hover:bg-ask-soft disabled:opacity-40"
          >
            삭제
          </button>
        </span>
      </Cell>
    </tr>
  );
}

/** 서버 문구의 `**강조**` 만 굵게. dangerouslySetInnerHTML 을 쓰지 않는다. */
