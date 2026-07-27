"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUp,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import { getMeetingFile, getMeetingList } from "@/lib/api";
import type { MeetingEntry } from "@/lib/api";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { ApiErrorBanner } from "@/components/states";

function fmtSize(n?: number): string {
  if (!n) return "";
  return n >= 1024 * 1024
    ? `${(n / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(n / 1024))}KB`;
}

const ROOT_LABEL = "회의자료";

export default function MeetingPage() {
  const [cwd, setCwd] = useState("");
  const [selRel, setSelRel] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const viewerRef = useRef<HTMLElement>(null);
  const [isFs, setIsFs] = useState(false);

  useEffect(() => {
    setIframeLoaded(false);
    setZoom(1); // 파일 바뀌면 배율 초기화
  }, [selRel]);

  // 전체화면(Fullscreen API) 상태 동기화 — Esc 로 빠져나가도 아이콘이 맞게 바뀌도록.
  useEffect(() => {
    const onFsChange = () => setIsFs(document.fullscreenElement === viewerRef.current);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void viewerRef.current?.requestFullscreen?.();
  };

  const listQuery = useQuery({
    queryKey: ["meetingList", cwd],
    queryFn: () => getMeetingList(cwd),
    refetchInterval: 300000,
    retry: false,
  });
  const fileQuery = useQuery({
    queryKey: ["meetingFile", selRel],
    queryFn: () => getMeetingFile(selRel as string),
    enabled: selRel != null,
    retry: false,
  });

  const listing = listQuery.data;
  const selName = selRel ? (selRel.split("/").pop() ?? selRel) : null;

  // 브레드크럼: 루트 + cwd 세그먼트
  const crumbs = useMemo(() => {
    const out = [{ label: ROOT_LABEL, path: "" }];
    if (cwd) {
      const segs = cwd.split("/");
      segs.forEach((s, i) => out.push({ label: s, path: segs.slice(0, i + 1).join("/") }));
    }
    return out;
  }, [cwd]);

  const onEntry = (e: MeetingEntry) => {
    if (e.type === "dir") setCwd(e.rel);
    else setSelRel(e.rel);
  };

  return (
    <>
      <Topbar
        title="회의"
        subtitle="회의자료 파일 탐색기"
        status={
          selName ? (
            <span className="max-w-[360px] truncate text-[11px] text-slate-400">
              {selName}
            </span>
          ) : undefined
        }
      />
      <PageContainer wide>
        <div className="flex flex-col gap-3 lg:h-[84vh] lg:flex-row">
          {/* ── 파일 탐색기 (좌) ─────────────────────────────────────── */}
          {/* 접으면 레이아웃에서 완전히 빠진다(뷰어 풀폭). 재오픈은 sidebar 손잡이로. */}
          {!collapsed && (
          <aside className="flex w-full shrink-0 flex-col overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-card lg:w-[300px]">
            <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
              <FolderOpen className="h-4 w-4 text-ge-point" />
              <span className="text-[13.5px] font-extrabold text-ge-navy">
                파일 탐색기
              </span>
              <div className="ml-auto flex items-center gap-1.5">
                <span className="rounded-md bg-ge-blue-bg px-1.5 py-0.5 text-[9.5px] font-bold text-ge-point">
                  PoC
                </span>
                <button
                  onClick={() => setCollapsed(true)}
                  title="접기"
                  className="rounded-md p-1 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ge-point"
                >
                  <PanelLeftClose className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* 브레드크럼 */}
            <div className="flex flex-wrap items-center gap-0.5 border-b border-hairline bg-canvas-soft px-3 py-2 text-[11.5px]">
              {crumbs.map((c, i) => (
                <span key={c.path} className="flex items-center">
                  {i > 0 && <ChevronRight className="h-3 w-3 text-ink-faint" />}
                  <button
                    onClick={() => setCwd(c.path)}
                    className={
                      i === crumbs.length - 1
                        ? "font-bold text-ge-navy"
                        : "text-ink-muted hover:text-ge-point"
                    }
                  >
                    {c.label}
                  </button>
                </span>
              ))}
            </div>

            {/* 목록 */}
            <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
              {listQuery.isPending ? (
                <div className="flex h-32 items-center justify-center text-ink-faint">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : listQuery.isError || !listing ? (
                <div className="px-3 py-4 text-[12px] text-ink-muted">
                  폴더를 불러올 수 없습니다.
                </div>
              ) : (
                <>
                  {cwd && (
                    <button
                      onClick={() => setCwd(listing.parent)}
                      className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] text-ink-muted hover:bg-canvas-soft"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                      상위 폴더
                    </button>
                  )}
                  {listing.entries.map((e) => {
                    const active = e.type === "html" && e.rel === selRel;
                    return (
                      <button
                        key={e.rel}
                        onClick={() => onEntry(e)}
                        className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] ${
                          active
                            ? "bg-ge-blue-bg font-bold text-ge-point"
                            : "text-ink hover:bg-canvas-soft"
                        }`}
                      >
                        {e.type === "dir" ? (
                          <Folder className="h-3.5 w-3.5 shrink-0 text-ge-main" />
                        ) : (
                          <FileText
                            className={`h-3.5 w-3.5 shrink-0 ${active ? "text-ge-point" : "text-ink-faint"}`}
                          />
                        )}
                        <span className="min-w-0 flex-1 truncate">{e.name}</span>
                        {e.type === "html" && (
                          <span className="shrink-0 text-[10px] tabular-nums text-ink-faint">
                            {fmtSize(e.size)}
                          </span>
                        )}
                      </button>
                    );
                  })}
                  {listing.entries.length === 0 && (
                    <div className="px-3 py-4 text-[12px] text-ink-faint">
                      (빈 폴더)
                    </div>
                  )}
                </>
              )}
            </div>
          </aside>
          )}

          {/* ── 뷰어 (우) ────────────────────────────────────────────── */}
          <section
            ref={viewerRef}
            className={`relative min-h-[60vh] flex-1 overflow-hidden bg-white lg:min-h-0 ${
              isFs
                ? "h-screen w-screen rounded-none border-0"
                : "rounded-2xl border border-hairline shadow-card"
            }`}
          >
            {selRel == null ? (
              <EmptyState />
            ) : fileQuery.isError ? (
              <div className="flex h-full items-center justify-center p-6">
                <ApiErrorBanner error={fileQuery.error} />
              </div>
            ) : (
              <>
                {fileQuery.data && (
                  /* 확대 시 스크롤. iframe 내부 뷰포트는 그대로 두고(자체 fit 로직 보존)
                     렌더 결과만 transform 으로 배율 적용 — 브라우저 확대와 동일한 체감. */
                  <div className="h-full w-full overflow-auto">
                    {/* sizer: 레이아웃 크기를 배율만큼 잡아 실제 스크롤 영역을 만든다
                        (transform 만으로는 스크롤 영역이 생기지 않아 확대분이 잘림).
                        iframe 실제 크기는 컨테이너 원래 크기 그대로 → 내부 재배치 없음. */}
                    <div
                      style={{
                        width: `${100 * zoom}%`,
                        height: `${100 * zoom}%`,
                      }}
                    >
                      <iframe
                        key={selRel}
                        title={selName ?? "회의자료"}
                        srcDoc={fileQuery.data.html}
                        onLoad={() => setIframeLoaded(true)}
                        sandbox="allow-scripts allow-same-origin allow-popups"
                        className="border-0 bg-white"
                        style={{
                          width: `${100 / zoom}%`,
                          height: `${100 / zoom}%`,
                          transform: `scale(${zoom})`,
                          transformOrigin: "0 0",
                        }}
                      />
                    </div>
                  </div>
                )}
                {fileQuery.data && iframeLoaded && (
                  <ZoomBar
                    zoom={zoom}
                    setZoom={setZoom}
                    isFs={isFs}
                    onToggleFs={toggleFullscreen}
                  />
                )}
                {(fileQuery.isPending || !iframeLoaded) && (
                  <Loading name={selName} />
                )}
              </>
            )}
          </section>
        </div>

        {/* 접힘 손잡이 — 좌측 sidebar 오른쪽 가장자리 세로 중앙에 살짝 돌출.
            fixed 라 콘텐츠 폭을 전혀 차지하지 않는다. 클릭하면 탐색기 재오픈. */}
        {collapsed && (
          <button
            onClick={() => setCollapsed(false)}
            title="파일 탐색기 열기"
            aria-label="파일 탐색기 열기"
            className="group fixed left-[212px] top-1/2 z-40 flex h-16 w-[18px] -translate-y-1/2 items-center justify-center rounded-r-xl bg-gradient-to-b from-ge-point to-ge-navy shadow-[3px_0_14px_rgba(70,105,170,0.35)] transition-all duration-200 hover:w-[24px] hover:brightness-110"
          >
            <ChevronRight className="h-4 w-4 shrink-0 text-white/95 transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </PageContainer>
    </>
  );
}

/* ── 확대/축소 툴바 (뷰어 우상단 플로팅) ─────────────────────────────── */
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;

function ZoomBar({
  zoom,
  setZoom,
  isFs,
  onToggleFs,
}: {
  zoom: number;
  setZoom: (z: number) => void;
  isFs: boolean;
  onToggleFs: () => void;
}) {
  const step = (d: number) =>
    setZoom(
      Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round((zoom + d) * 100) / 100)),
    );
  return (
    <div className="absolute right-3 top-3 z-20 flex items-center gap-0.5 rounded-xl border border-hairline bg-white/90 p-1 shadow-card backdrop-blur">
      <button
        onClick={() => step(-0.25)}
        disabled={zoom <= ZOOM_MIN}
        title="축소"
        className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ge-point disabled:opacity-35 disabled:hover:bg-transparent"
      >
        <ZoomOut className="h-4 w-4" />
      </button>
      <button
        onClick={() => setZoom(1)}
        title="100%로 되돌리기"
        className="min-w-[48px] rounded-lg px-1 py-1 text-[11.5px] font-extrabold tabular-nums text-ge-navy transition-colors hover:bg-canvas-soft"
      >
        {Math.round(zoom * 100)}%
      </button>
      <button
        onClick={() => step(0.25)}
        disabled={zoom >= ZOOM_MAX}
        title="확대"
        className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ge-point disabled:opacity-35 disabled:hover:bg-transparent"
      >
        <ZoomIn className="h-4 w-4" />
      </button>

      <span className="mx-0.5 h-4 w-px bg-hairline" />

      {/* 전체화면 — 브라우저 최대화(□)처럼 뷰어를 화면 꽉 채움. Esc 로 복귀. */}
      <button
        onClick={onToggleFs}
        title={isFs ? "전체화면 해제 (Esc)" : "전체화면"}
        aria-label={isFs ? "전체화면 해제" : "전체화면"}
        className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-canvas-soft hover:text-ge-point"
      >
        {isFs ? (
          <Minimize2 className="h-4 w-4" />
        ) : (
          <Maximize2 className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}

/* ── 빈 상태 ──────────────────────────────────────────────────────────── */
function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-br from-ge-main via-ge-point to-ge-navy shadow-[0_10px_30px_rgba(70,105,170,0.28)]">
        <FolderOpen className="h-9 w-9 text-white" strokeWidth={1.8} />
      </div>
      <div>
        <div className="text-[15px] font-extrabold text-ge-navy">
          회의자료를 선택하세요
        </div>
        <div className="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
          왼쪽 파일 탐색기에서 폴더를 열고
          <br />
          HTML 파일을 클릭하면 이곳에 표시됩니다.
        </div>
      </div>
    </div>
  );
}

/* ── 예쁜 로딩 오버레이 ───────────────────────────────────────────────── */
function Loading({ name }: { name: string | null }) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-5 bg-white/85 backdrop-blur-sm">
      <div className="relative flex h-24 w-24 items-center justify-center">
        <div className="absolute inset-0 animate-spin rounded-full border-[5px] border-ge-blue-bg border-t-ge-point" />
        <div className="absolute inset-2 animate-[spin_2.4s_linear_infinite_reverse] rounded-full border-[3px] border-transparent border-b-ge-main/60" />
        <FileText className="h-8 w-8 animate-pulse text-ge-point" strokeWidth={1.8} />
      </div>
      <div className="text-center">
        <div className="text-[14px] font-extrabold text-ge-navy">
          회의자료 불러오는 중…
        </div>
        {name && (
          <div className="mt-1 max-w-[380px] truncate px-4 text-[12px] text-ink-muted">
            {name}
          </div>
        )}
      </div>
      <div className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-2 w-2 animate-pulse rounded-full bg-ge-point"
            style={{ animationDelay: `${i * 0.18}s` }}
          />
        ))}
      </div>
    </div>
  );
}
