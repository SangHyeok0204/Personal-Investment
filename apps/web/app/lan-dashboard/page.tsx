"use client";

// LAN 서버 모니터링 — 원본 lan-dashboard/public/index.html 의 GE 라이트 테마 이식.
// 기능 1:1: 요약 4카드 · 카드/표 뷰 · 자동 새로고침 · 그룹 분류 · Check/Edit/Delete ·
//           Add Server 모달(그룹 즉석 추가) · 토스트.

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, X } from "lucide-react";
import {
  addLanGroup,
  addLanServer,
  checkAllLan,
  checkLanServer,
  deleteLanServer,
  getLanGroups,
  getLanServers,
  updateLanServer,
  type LanServer,
} from "@/lib/api";
import { Topbar } from "@/components/layout/topbar";
import { PageContainer } from "@/components/layout/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiErrorBanner } from "@/components/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

type ViewMode = "cards" | "table";
type ToastItem = { id: number; msg: string; type: "success" | "error" };

const REFRESH_MS = 30000;

// 상태별 색/라벨 (GE 토큰): online=초록, offline=빨강, error/unknown=앰버.
const STATUS_META: Record<
  string,
  { bar: string; badge: string; dot: string }
> = {
  online: {
    bar: "bg-status-success",
    badge: "bg-status-success/[0.10] text-status-success border-status-success/30",
    dot: "bg-status-success",
  },
  offline: {
    bar: "bg-status-failed",
    badge: "bg-status-failed/[0.08] text-status-failed border-status-failed/30",
    dot: "bg-status-failed",
  },
  error: {
    bar: "bg-amber-400",
    badge: "bg-amber-400/[0.15] text-amber-600 border-amber-400/40",
    dot: "bg-amber-500",
  },
  unknown: {
    bar: "bg-amber-400",
    badge: "bg-amber-400/[0.15] text-amber-600 border-amber-400/40",
    dot: "bg-amber-500",
  },
};

function statusMeta(status: string | undefined) {
  return STATUS_META[status ?? "unknown"] ?? STATUS_META.unknown;
}

function hostUrl(s: LanServer): string {
  const proto = s.protocol === "https" ? "https" : "http";
  return `${proto}://${s.host}:${s.port}`;
}

function respClass(ms: number | null | undefined): string {
  if (ms == null) return "text-ink-faint";
  if (ms < 50) return "text-status-success";
  if (ms < 200) return "text-amber-600";
  return "text-status-failed";
}

function respText(ms: number | null | undefined): string {
  return ms == null ? "-" : `${ms}ms`;
}

// heartbeat: 마지막 수신 시각(로컬 시간). 클라이언트 전용 렌더라 hydration 문제 없음.
function lastSeenText(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleTimeString("ko-KR") : "-";
}

/* ── 페이지 ──────────────────────────────────────────────────────────── */

export default function LanDashboardPage() {
  const qc = useQueryClient();
  const [view, setView] = useState<ViewMode>("cards");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [checking, setChecking] = useState(false);
  const [modal, setModal] = useState<{ edit: LanServer | null } | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const serversQuery = useQuery({
    queryKey: ["lanServers"],
    queryFn: getLanServers,
    refetchInterval: autoRefresh ? REFRESH_MS : false,
  });
  const groupsQuery = useQuery({ queryKey: ["lanGroups"], queryFn: getLanGroups });

  const servers = serversQuery.data ?? [];
  const groups = groupsQuery.data ?? [];

  const toast = (msg: string, type: "success" | "error" = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3000);
  };

  const reload = () => qc.invalidateQueries({ queryKey: ["lanServers"] });

  const summary = useMemo(() => {
    let online = 0;
    let offline = 0;
    let unknown = 0;
    for (const s of servers) {
      const st = s.status?.status;
      if (st === "online") online++;
      else if (st === "offline" || st === "error") offline++;
      else unknown++;
    }
    return { total: servers.length, online, offline, unknown };
  }, [servers]);

  // 그룹핑 — group 없으면 'Ungrouped'.
  const grouped = useMemo(() => {
    const map = new Map<string, LanServer[]>();
    for (const s of servers) {
      const g = s.group || "Ungrouped";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(s);
    }
    return [...map.entries()];
  }, [servers]);

  const refreshAll = async () => {
    setChecking(true);
    try {
      await checkAllLan();
      await reload();
      toast("All servers checked");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Check failed", "error");
    } finally {
      setChecking(false);
    }
  };

  const checkOne = async (id: string) => {
    try {
      await checkLanServer(id);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Check failed", "error");
    }
  };

  const remove = async (s: LanServer) => {
    if (!window.confirm(`"${s.name}" 서버를 삭제하시겠습니까?`)) return;
    try {
      await deleteLanServer(s.id);
      await reload();
      toast("Server deleted");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  };

  const lastUpdated =
    serversQuery.dataUpdatedAt > 0
      ? new Date(serversQuery.dataUpdatedAt).toLocaleTimeString("ko-KR")
      : null;

  return (
    <>
      <Topbar
        title="LAN Dashboard"
        subtitle="기타 · 사내 LAN 서버 상태 모니터링"
        actions={
          <div className="flex items-center gap-2.5">
            <label className="flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-ink-muted">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="accent-ge-point"
              />
              Auto (30s)
            </label>
            <button
              type="button"
              onClick={refreshAll}
              disabled={checking}
              className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas-soft px-3 py-1.5 text-[12px] font-semibold text-ink-secondary transition hover:text-ge-point disabled:opacity-60"
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", checking && "animate-spin")}
                strokeWidth={2.2}
              />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => setModal({ edit: null })}
              className="inline-flex items-center gap-1.5 rounded-full bg-ge-point px-3 py-1.5 text-[12px] font-bold text-white transition hover:bg-ge-main"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={2.6} />
              Add Server
            </button>
          </div>
        }
      />

      <PageContainer wide>
        {serversQuery.isError && (
          <div className="mb-4">
            <ApiErrorBanner error={serversQuery.error} />
          </div>
        )}

        {/* 요약 4카드 */}
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="Total Servers" value={summary.total} tone="total" />
          <SummaryCard label="Online" value={summary.online} tone="online" />
          <SummaryCard label="Offline" value={summary.offline} tone="offline" />
          <SummaryCard label="Unknown" value={summary.unknown} tone="unknown" />
        </div>

        {/* 툴바 — 뷰 토글 + 마지막 갱신 */}
        <div className="mb-4 flex items-center gap-3">
          <ViewToggle view={view} onChange={setView} />
          {lastUpdated && (
            <span className="text-[12px] text-ink-faint">
              Last updated: {lastUpdated}
            </span>
          )}
        </div>

        {serversQuery.isLoading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-44 w-full rounded-2xl" />
            ))}
          </div>
        ) : servers.length === 0 ? (
          <p className="text-sm text-ink-muted">등록된 서버가 없습니다.</p>
        ) : (
          <div className="space-y-7">
            {grouped.map(([name, items]) => (
              <section key={name}>
                <div className="mb-3 flex items-center gap-2 border-b border-hairline pb-2">
                  <span className="h-4 w-1.5 rounded-full bg-ge-point" />
                  <span className="text-[13px] font-extrabold uppercase tracking-wide text-ge-navy">
                    {name}
                  </span>
                  <span className="rounded-full bg-canvas-soft px-2 py-0.5 text-[11px] font-bold text-ink-muted">
                    {items.length}
                  </span>
                </div>
                {view === "cards" ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {items.map((s) => (
                      <ServerCard
                        key={s.id}
                        server={s}
                        onCheck={() => checkOne(s.id)}
                        onEdit={() => setModal({ edit: s })}
                        onDelete={() => remove(s)}
                      />
                    ))}
                  </div>
                ) : (
                  <ServerTable
                    items={items}
                    onCheck={checkOne}
                    onEdit={(s) => setModal({ edit: s })}
                    onDelete={remove}
                  />
                )}
              </section>
            ))}
          </div>
        )}
      </PageContainer>

      {modal && (
        <ServerModal
          key={modal.edit?.id ?? "new"}
          edit={modal.edit}
          groups={groups}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            reload();
          }}
          onGroupsChanged={() =>
            qc.invalidateQueries({ queryKey: ["lanGroups"] })
          }
          toast={toast}
        />
      )}

      <Toasts items={toasts} />
    </>
  );
}

/* ── 요약 카드 ───────────────────────────────────────────────────────── */

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "total" | "online" | "offline" | "unknown";
}) {
  const toneClass = {
    total: "border-hairline bg-canvas text-ge-navy",
    online: "border-status-success/30 bg-status-success/[0.07] text-status-success",
    offline: "border-status-failed/30 bg-status-failed/[0.06] text-status-failed",
    unknown: "border-amber-400/40 bg-amber-400/[0.09] text-amber-600",
  }[tone];

  return (
    <div className={cn("rounded-2xl border p-5 shadow-card", toneClass)}>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
        {label}
      </div>
      <div className="mt-1 text-[32px] font-extrabold leading-none tabular-nums">
        {value}
      </div>
    </div>
  );
}

/* ── 뷰 토글 ─────────────────────────────────────────────────────────── */

function ViewToggle({
  view,
  onChange,
}: {
  view: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-lg border border-hairline">
      {(["cards", "table"] as const).map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "px-3.5 py-1.5 text-[12px] font-semibold transition",
            view === v
              ? "bg-ge-blue-bg text-ge-point"
              : "bg-canvas text-ink-muted hover:text-ink",
          )}
        >
          {v === "cards" ? "Cards" : "Table"}
        </button>
      ))}
    </div>
  );
}

/* ── 상태 배지 ───────────────────────────────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const meta = statusMeta(status);
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wide",
        meta.badge,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {status}
    </span>
  );
}

/* ── 서버 카드 ───────────────────────────────────────────────────────── */

function ServerCard({
  server: s,
  onCheck,
  onEdit,
  onDelete,
}: {
  server: LanServer;
  onCheck: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const st = s.status?.status ?? "unknown";
  const meta = statusMeta(st);
  const isHb = s.protocol === "heartbeat";
  return (
    <div className="relative overflow-hidden rounded-2xl border border-hairline bg-canvas p-5 shadow-card transition hover:border-ge-point/40">
      <span className={cn("absolute left-0 top-0 h-full w-1", meta.bar)} />
      <div className="flex items-start justify-between gap-2">
        <span className="text-[15px] font-extrabold text-ge-navy">{s.name}</span>
        <StatusBadge status={st} />
      </div>

      <dl className="mt-3 flex flex-col gap-1.5">
        <CardRow label={isHb ? "Key" : "Host"}>
          {isHb ? (
            <span className="font-mono text-[12.5px] text-ink">{s.key || "-"}</span>
          ) : (
            <a
              href={hostUrl(s)}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-[12.5px] text-ge-point hover:underline"
            >
              {s.host}:{s.port}
            </a>
          )}
        </CardRow>
        <CardRow label="Proto">
          <span className="font-mono text-[12.5px] text-ink">
            {s.protocol.toUpperCase()}
          </span>
        </CardRow>
        <CardRow label={isHb ? "Last" : "Resp"}>
          {isHb ? (
            <span className="font-mono text-[12.5px] text-ink-secondary">
              {lastSeenText(s.status?.lastChecked)}
            </span>
          ) : (
            <span
              className={cn(
                "font-mono text-[12.5px] font-semibold",
                respClass(s.status?.responseTime),
              )}
            >
              {respText(s.status?.responseTime)}
            </span>
          )}
        </CardRow>
        {!isHb && s.status?.httpStatus != null && (
          <CardRow label="HTTP">
            <span className="font-mono text-[12.5px] text-ink">
              {s.status.httpStatus}
            </span>
          </CardRow>
        )}
        {s.status?.error && (
          <CardRow label="Error">
            <span className="text-[12px] text-status-failed">
              {s.status.error}
            </span>
          </CardRow>
        )}
      </dl>

      {s.description && (
        <div className="mt-3 border-t border-hairline pt-3 text-[12.5px] text-ink-muted">
          {s.description}
        </div>
      )}

      <div className="mt-3 flex gap-2 border-t border-hairline pt-3">
        <ActionButton onClick={onCheck}>Check</ActionButton>
        <ActionButton onClick={onEdit}>Edit</ActionButton>
        <ActionButton onClick={onDelete} danger>
          Delete
        </ActionButton>
      </div>
    </div>
  );
}

function CardRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 text-[13px]">
      <span className="w-12 shrink-0 font-semibold text-ink-muted">{label}</span>
      <span className="min-w-0 truncate">{children}</span>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg border px-2.5 py-1 text-[12px] font-semibold transition",
        danger
          ? "border-status-failed/30 text-status-failed hover:bg-status-failed/[0.06]"
          : "border-hairline text-ink-secondary hover:border-ge-point hover:text-ge-point",
      )}
    >
      {children}
    </button>
  );
}

/* ── 서버 표 ─────────────────────────────────────────────────────────── */

function ServerTable({
  items,
  onCheck,
  onEdit,
  onDelete,
}: {
  items: LanServer[];
  onCheck: (id: string) => void;
  onEdit: (s: LanServer) => void;
  onDelete: (s: LanServer) => void;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Host</TableHeaderCell>
            <TableHeaderCell className="text-right">Port</TableHeaderCell>
            <TableHeaderCell>Protocol</TableHeaderCell>
            <TableHeaderCell className="text-right">Response</TableHeaderCell>
            <TableHeaderCell>Description</TableHeaderCell>
            <TableHeaderCell className="text-right">Actions</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((s) => {
            const isHb = s.protocol === "heartbeat";
            return (
              <TableRow key={s.id}>
                <TableCell>
                  <StatusBadge status={s.status?.status ?? "unknown"} />
                </TableCell>
                <TableCell className="font-bold text-ge-navy">{s.name}</TableCell>
                <TableCell className="font-mono text-[12.5px]">
                  {isHb ? (
                    <span className="text-ink">key: {s.key || "-"}</span>
                  ) : (
                    <a
                      href={hostUrl(s)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-ge-point hover:underline"
                    >
                      {s.host}
                    </a>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono text-[12.5px]">
                  {isHb ? "-" : s.port}
                </TableCell>
                <TableCell className="font-mono text-[12.5px]">
                  {s.protocol.toUpperCase()}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-right font-mono text-[12.5px] font-semibold",
                    isHb ? "text-ink-secondary" : respClass(s.status?.responseTime),
                  )}
                >
                  {isHb
                    ? lastSeenText(s.status?.lastChecked)
                    : respText(s.status?.responseTime)}
                </TableCell>
                <TableCell className="text-ink-muted">
                  {s.description || "-"}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <ActionButton onClick={() => onCheck(s.id)}>Check</ActionButton>
                    <ActionButton onClick={() => onEdit(s)}>Edit</ActionButton>
                    <ActionButton onClick={() => onDelete(s)} danger>
                      Del
                    </ActionButton>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/* ── Add/Edit 모달 ───────────────────────────────────────────────────── */

function ServerModal({
  edit,
  groups,
  onClose,
  onSaved,
  onGroupsChanged,
  toast,
}: {
  edit: LanServer | null;
  groups: string[];
  onClose: () => void;
  onSaved: () => void;
  onGroupsChanged: () => Promise<void> | void;
  toast: (msg: string, type?: "success" | "error") => void;
}) {
  const [name, setName] = useState(edit?.name ?? "");
  const [host, setHost] = useState(edit?.host ?? "");
  const [port, setPort] = useState(edit ? String(edit.port) : "");
  const [protocol, setProtocol] = useState(edit?.protocol ?? "tcp");
  const [group, setGroup] = useState(edit?.group ?? "");
  const [desc, setDesc] = useState(edit?.description ?? "");
  const [key, setKey] = useState(edit?.key ?? "");
  const [maxAge, setMaxAge] = useState(
    edit?.maxAgeSec != null ? String(edit.maxAgeSec) : "",
  );
  const [saving, setSaving] = useState(false);
  const isHb = protocol === "heartbeat";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const addGroup = async () => {
    const raw = window.prompt("새 그룹 이름:");
    const n = raw?.trim();
    if (!n) return;
    try {
      await addLanGroup(n);
      await onGroupsChanged();
      setGroup(n);
      toast("Group added");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Group add failed", "error");
    }
  };

  const save = async () => {
    const body = {
      name: name.trim(),
      host: host.trim(),
      port: isHb ? 0 : Number(port),
      protocol,
      group: group.trim(),
      description: desc.trim(),
      key: isHb ? key.trim() : "",
      maxAgeSec: isHb && maxAge ? Number(maxAge) : null,
    };
    const invalid = isHb
      ? !body.name || !body.key
      : !body.name || !body.host || !port;
    if (invalid) {
      toast(
        isHb ? "Name, Key are required" : "Name, Host, Port are required",
        "error",
      );
      return;
    }
    setSaving(true);
    try {
      if (edit) {
        await updateLanServer(edit.id, body);
        toast("Server updated");
      } else {
        await addLanServer(body);
        toast("Server added");
      }
      onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ge-navy/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-[460px] max-w-[92vw] rounded-2xl bg-canvas p-7 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[17px] font-extrabold text-ge-navy">
            {edit ? "Edit Server" : "Add Server"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-ink-muted transition hover:bg-canvas-soft hover:text-ink"
          >
            <X className="h-4 w-4" strokeWidth={2} />
          </button>
        </div>

        <div className="flex flex-col gap-3.5">
          <Field label="Service Name">
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Main Web Server"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Protocol">
              <select
                className={inputClass}
                value={protocol}
                onChange={(e) => setProtocol(e.target.value)}
              >
                <option value="tcp">TCP</option>
                <option value="http">HTTP</option>
                <option value="heartbeat">Heartbeat (push)</option>
              </select>
            </Field>
            <Field label="Group">
              <div className="flex items-stretch gap-1.5">
                <select
                  className={cn(inputClass, "min-w-0 flex-1")}
                  value={group}
                  onChange={(e) => setGroup(e.target.value)}
                >
                  <option value="">(No group)</option>
                  {groups.map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={addGroup}
                  className="shrink-0 whitespace-nowrap rounded-lg border border-hairline px-2.5 text-[12px] font-semibold text-ink-secondary transition hover:border-ge-point hover:text-ge-point"
                >
                  + New
                </button>
              </div>
            </Field>
          </div>

          {isHb ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Key (push 대상)">
                  <input
                    className={inputClass}
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder="e.g. macro"
                  />
                </Field>
                <Field label="Max age (s)">
                  <input
                    type="number"
                    className={inputClass}
                    value={maxAge}
                    onChange={(e) => setMaxAge(e.target.value)}
                    placeholder="150"
                  />
                </Field>
              </div>
              <Field label="Source host (info, optional)">
                <input
                  className={inputClass}
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="192.168.194.121"
                />
              </Field>
            </>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Host / IP">
                <input
                  className={inputClass}
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="192.168.0.10"
                />
              </Field>
              <Field label="Port">
                <input
                  type="number"
                  className={inputClass}
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder="8080"
                />
              </Field>
            </div>
          )}

          <Field label="Description">
            <input
              className={inputClass}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="e.g. REST API for mobile app"
            />
          </Field>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-hairline px-4 py-2 text-[13px] font-semibold text-ink-secondary transition hover:bg-canvas-soft"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="rounded-lg bg-ge-point px-4 py-2 text-[13px] font-bold text-white transition hover:bg-ge-main disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-hairline bg-canvas-soft px-3 py-2 text-[13.5px] text-ink outline-none transition focus:border-ge-point";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

/* ── 토스트 ──────────────────────────────────────────────────────────── */

function Toasts({ items }: { items: ToastItem[] }) {
  return (
    <div className="fixed bottom-5 right-5 z-[60] flex flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={cn(
            "rounded-lg border bg-canvas px-4 py-2.5 text-[13px] font-semibold shadow-panel",
            t.type === "error"
              ? "border-status-failed/40 text-status-failed"
              : "border-status-success/40 text-ink",
          )}
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
