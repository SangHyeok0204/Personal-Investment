"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, KeyRound, Loader2, X } from "lucide-react";
import {
  getBrokerAccounts,
  registerCredentials,
  runBrokerageSync,
  type BrokerAccountPreview,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 계좌 연동 팝업 — appkey/secretkey 를 넣으면 검증 → 저장 → 동기화까지 한 번에.
//
// ⚠️키는 **보내기만** 한다. 서버는 어떤 응답에도 키를 싣지 않고(지문·꼬리 4자리뿐),
//   화면도 입력값을 상태에 남기지 않는다(성공하면 즉시 비운다).
// ⚠️저장은 **검증 성공 후에만** 일어난다. 틀린 키를 저장해 두면 그 뒤 모든 동기화가
//   조용히 실패하고 "왜 안 되지"만 남는다.

const MARKET_OPTIONS = [
  { id: "US", label: "해외(미국)" },
  { id: "KR", label: "국내" },
];

export function ConnectDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [appKey, setAppKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [environment, setEnvironment] = useState("REAL");
  const [markets, setMarkets] = useState<string[]>(["US"]);
  const [error, setError] = useState<string | null>(null);
  // IP 차단일 때 등록해야 할 서버 공인 IP. 값을 보여줘야 사용자가 찾아 헤매지 않는다.
  const [blockedIp, setBlockedIp] = useState<string | null>(null);
  const [phase, setPhase] = useState<"form" | "syncing" | "done">("form");
  const [synced, setSynced] = useState<{ positions: number; trades: number } | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // 이미 등록된 키가 있으면 그 키에 묶인 계좌를 보여준다(사용자 요청).
  const status = useQuery({
    queryKey: ["brokerAccounts"],
    queryFn: getBrokerAccounts,
    enabled: open,
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const connect = useMutation({
    mutationFn: async () => {
      await registerCredentials({
        app_key: appKey.trim(),
        secret_key: secretKey.trim(),
        environment,
        markets,
      });
      setPhase("syncing");
      return runBrokerageSync();
    },
    onSuccess: (result) => {
      // 입력값은 즉시 버린다 — 화면 상태에 키를 남겨 둘 이유가 없다.
      setAppKey("");
      setSecretKey("");
      setError(null);
      setSynced({ positions: result.positions, trades: result.trades });
      setPhase("done");
      // 대시보드 전체를 새로 읽는다.
      void queryClient.invalidateQueries();
    },
    onError: (err: unknown) => {
      setPhase("form");
      setError(err instanceof Error ? err.message : "연결에 실패했습니다.");
      // ApiError 의 details 에 공인 IP 가 실려 온다(IP 차단일 때만).
      const details = (err as { details?: Record<string, unknown> })?.details;
      setBlockedIp(
        typeof details?.public_ip === "string" ? details.public_ip : null,
      );
    },
  });

  const syncOnly = useMutation({
    mutationFn: runBrokerageSync,
    onSuccess: (result) => {
      setSynced({ positions: result.positions, trades: result.trades });
      setPhase("done");
      void queryClient.invalidateQueries();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "동기화에 실패했습니다.");
    },
  });

  if (!open) return null;

  const busy = connect.isPending || syncOnly.isPending;
  const existing = status.data;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-ge-navy/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="계좌 연동"
        className="max-h-[90vh] w-full max-w-[540px] overflow-y-auto rounded-2xl bg-canvas shadow-[0_24px_60px_rgba(36,59,94,0.32)]"
      >
        <header className="flex items-center gap-3 rounded-t-2xl bg-ge-header px-5 py-3.5">
          <KeyRound className="h-4 w-4 text-white" />
          <h2 className="text-[14px] font-extrabold text-white">계좌 연동</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="ml-auto rounded-lg p-1 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-5">
          {/* 이미 등록된 키 — 그 키에 묶인 계좌를 고를 수 있게 한다. */}
          {existing?.configured && (
            <RegisteredBox
              tail={existing.app_key_tail}
              environment={existing.environment}
              markets={existing.markets}
              ok={existing.connection_ok}
              message={existing.connection_message}
              publicIp={existing.public_ip}
              accounts={existing.accounts}
              loading={status.isFetching}
              busy={busy}
              onSync={() => {
                setError(null);
                setPhase("syncing");
                syncOnly.mutate();
              }}
            />
          )}

          {phase === "done" && synced ? (
            <div className="flex items-start gap-3 rounded-xl border border-status-success/30 bg-status-success/5 px-4 py-3">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-status-success" />
              <div>
                <p className="text-[13px] font-extrabold text-status-success">
                  동기화 완료
                </p>
                <p className="mt-0.5 text-[12px] font-semibold text-ink-secondary">
                  보유 {synced.positions}종목 · 체결 {synced.trades}건을 불러왔습니다.
                  대시보드에 반영됐습니다.
                </p>
              </div>
            </div>
          ) : (
            <>
              <p className="text-[12px] font-medium leading-relaxed text-ink-secondary">
                키움 REST API 홈페이지에서 발급한 App Key 와 Secret Key 를 넣으면
                검증 후 저장하고 바로 동기화합니다.
                <br />
                <span className="text-ink-faint">
                  키는 서버에만 저장되고 화면으로 다시 내려오지 않습니다.
                </span>
              </p>

              <Field label="App Key">
                <input
                  value={appKey}
                  onChange={(e) => setAppKey(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="발급받은 App Key"
                  className="w-full rounded-lg border border-hairline bg-white px-3 py-2 text-[13px] font-semibold text-ge-navy outline-none focus:border-ge-point"
                />
              </Field>

              <Field label="Secret Key">
                {/* 어깨너머로 보이지 않게 가린다. 저장은 서버에서만 한다. */}
                <input
                  type="password"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="발급받은 Secret Key"
                  className="w-full rounded-lg border border-hairline bg-white px-3 py-2 text-[13px] font-semibold text-ge-navy outline-none focus:border-ge-point"
                />
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="환경">
                  <div className="flex gap-1.5">
                    {["REAL", "PAPER"].map((env) => (
                      <Toggle
                        key={env}
                        active={environment === env}
                        onClick={() => setEnvironment(env)}
                      >
                        {env === "REAL" ? "실전" : "모의"}
                      </Toggle>
                    ))}
                  </div>
                </Field>
                <Field label="조회 시장">
                  <div className="flex gap-1.5">
                    {MARKET_OPTIONS.map((m) => (
                      <Toggle
                        key={m.id}
                        active={markets.includes(m.id)}
                        onClick={() =>
                          setMarkets((prev) =>
                            prev.includes(m.id)
                              ? prev.filter((x) => x !== m.id)
                              : [...prev, m.id],
                          )
                        }
                      >
                        {m.label}
                      </Toggle>
                    ))}
                  </div>
                </Field>
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded-xl border border-status-failed/30 bg-status-failed/5 px-3.5 py-2.5">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-status-failed" />
                  <div className="min-w-0">
                    <p className="text-[12px] font-bold leading-snug text-status-failed">
                      {error}
                    </p>
                    {/IP|8050/.test(error) && (
                      <div className="mt-1.5 space-y-1.5">
                        <p className="text-[11px] font-medium text-ink-secondary">
                          키가 아니라 <b>IP 등록</b> 문제입니다. 키움 REST API 홈페이지 &gt;
                          API 사용신청에서 아래 IP 를 등록하세요.
                        </p>
                        {blockedIp && <IpBox ip={blockedIp} />}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <button
                type="button"
                disabled={busy || !appKey.trim() || !secretKey.trim() || markets.length === 0}
                onClick={() => {
                  setError(null);
                  connect.mutate();
                }}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-ge-point px-4 py-2.5 text-[13px] font-extrabold text-white transition-colors hover:bg-ge-point/90 disabled:opacity-50"
              >
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                {phase === "syncing" ? "동기화 중…" : "연결하고 동기화"}
              </button>
              <p className="text-center text-[11px] font-medium text-ink-faint">
                처음 동기화는 체결·성과 이력까지 받아오느라 10초 정도 걸립니다.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 이미 등록된 키와 그 키에 묶인 계좌 목록. */
function RegisteredBox({
  tail,
  environment,
  markets,
  ok,
  message,
  publicIp,
  accounts,
  loading,
  busy,
  onSync,
}: {
  tail: string | null;
  environment: string;
  markets: string[];
  ok: boolean | null;
  message: string | null;
  publicIp: string | null;
  accounts: BrokerAccountPreview[];
  loading: boolean;
  busy: boolean;
  onSync: () => void;
}) {
  return (
    <div className="rounded-xl border border-hairline bg-canvas-soft/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-extrabold text-ge-navy">등록된 API 키</span>
        <code className="rounded bg-white px-1.5 py-0.5 text-[11px] font-bold text-ink-secondary ring-1 ring-hairline">
          ••••{tail ?? "????"}
        </code>
        <span className="rounded bg-ge-blue-bg px-1.5 py-0.5 text-[10px] font-bold text-ge-point">
          {environment === "REAL" ? "실전" : "모의"}
        </span>
        <span className="text-[11px] font-semibold text-ink-faint">
          {markets.join(" · ")}
        </span>
        <span
          className={cn(
            "ml-auto rounded-full px-2 py-0.5 text-[10px] font-extrabold",
            loading
              ? "bg-slate-100 text-ink-muted"
              : ok
                ? "bg-status-success/10 text-status-success"
                : "bg-status-failed/10 text-status-failed",
          )}
        >
          {loading ? "확인 중…" : ok ? "연결됨" : "연결 실패"}
        </span>
      </div>

      {!loading && !ok && message && (
        <div className="mt-2 space-y-1.5">
          <p className="text-[11px] font-semibold leading-snug text-status-failed">
            {message}
          </p>
          {publicIp && <IpBox ip={publicIp} />}
        </div>
      )}

      {accounts.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-[11px] font-bold text-ink-muted">
            이 키에 연결된 계좌
          </p>
          <div className="space-y-1.5">
            {accounts.map((a) => (
              <div
                key={a.external_account_id}
                className="flex items-center gap-2 rounded-lg border border-hairline bg-white px-3 py-2"
              >
                <span className="text-[13px] font-extrabold text-ge-navy">
                  {a.account_number_masked ?? a.external_account_id}
                </span>
                <span className="text-[11px] font-semibold text-ink-muted">
                  {a.account_name ?? a.account_type ?? ""}
                </span>
              </div>
            ))}
          </div>
          {/* 계좌가 하나뿐이면 고를 것이 없다 — 여럿일 때만 선택 UI 를 쓴다.
              (상단 바의 계좌 선택기가 동기화 뒤의 실제 선택을 담당한다.) */}
          {accounts.length > 1 && (
            <p className="mt-1.5 text-[11px] font-medium text-ink-faint">
              동기화 후 상단 바에서 계좌를 전환할 수 있습니다.
            </p>
          )}
        </div>
      )}

      <button
        type="button"
        disabled={busy}
        onClick={onSync}
        className="mt-3 w-full rounded-lg border border-ge-point bg-white px-3 py-2 text-[12px] font-bold text-ge-point transition-colors hover:bg-ge-blue-bg disabled:opacity-50"
      >
        {busy ? "동기화 중…" : "이 키로 지금 동기화"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-bold text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

function Toggle({
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
        "flex-1 rounded-lg border px-2 py-1.5 text-[12px] font-bold transition-colors",
        active
          ? "border-ge-point bg-ge-blue-bg text-ge-point"
          : "border-hairline bg-white text-ink-muted hover:bg-canvas-soft",
      )}
    >
      {children}
    </button>
  );
}

/** 등록해야 할 공인 IP 를 눈에 띄게 + 복사 가능하게.
 *
 * ★IP 미등록으로 두 번 막혔고 두 번째는 네트워크가 바뀌어 IP 자체가 달라진
 *   경우였다. "IP를 등록하세요"만 보여주면 어떤 IP 인지 찾아 헤매게 된다.
 */
function IpBox({ ip }: { ip: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-hairline bg-white px-2.5 py-1.5">
      <code className="flex-1 text-[13px] font-extrabold tabular-nums text-ge-navy">
        {ip}
      </code>
      <button
        type="button"
        onClick={() => {
          // 클립보드는 보안 컨텍스트에서만 된다 — 실패해도 IP 는 이미 보인다.
          navigator.clipboard?.writeText(ip).then(
            () => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            },
            () => setCopied(false),
          );
        }}
        className="shrink-0 rounded-md border border-hairline px-2 py-0.5 text-[11px] font-bold text-ink-secondary transition-colors hover:bg-canvas-soft"
      >
        {copied ? "복사됨" : "복사"}
      </button>
    </div>
  );
}
