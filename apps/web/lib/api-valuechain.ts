// 산업 밸류체인(S7) 읽기 클라이언트 — `GET /api/v1/research/valuechain/*`.
//
// ★`lib/api.ts` 는 다른 레인이 동시에 고치는 파일이라 여기로 분리했다(계획 §12-8).
//   api.ts 의 `request` 는 모듈 private 이므로 같은 에러 봉투 처리를 재구현하되,
//   공개된 API_BASE_URL·ApiError 를 재사용해 ApiErrorBanner 가 그대로 동작하게 한다
//   (`lib/stock-discussion.ts` 와 같은 방식).
import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL, ApiError } from "@/lib/api";

// ── 응답 계약 (apps/api/app/api/valuechain.py, 실측 curl 기준) ──────────────────

/** 섹터 종류 — "theme" = 손으로 쓴 테마 밸류체인(bio 등), "taxonomy" = generated/ 의 자동 생성 분류 지도. */
export type VcSectorKind = "theme" | "taxonomy";

/** 섹터 목록 한 줄 — 칩 하나. 숫자는 로더가 센 값. */
export interface VcSectorSummary {
  code: string;
  name: string;
  en: string | null;
  /** 섹터 기준색(분류 섹터 = L1 기준색). */
  color?: string | null;
  kind: VcSectorKind;
  categories: number;
  companies: number;
  /** 로더 검증에서 나온 문제 수(0 이 정상). */
  problems: number;
}

/** 섹터 허브 카드 한 장 — `catalog.ttl` 항목 + 섹터 파일 통계. */
export interface VcCatalogCard {
  code: string;
  name: string;
  en: string | null;
  desc: string | null;
  /** 섹터 기준색. 없으면 묶음 색을 쓴다. */
  color?: string | null;
  /** 섹터 파일의 종류. 미작성 카드는 "theme". */
  kind: VcSectorKind;
  /** 섹터 파일이 있어 들어갈 수 있는가. false 면 "미작성" 자리. */
  built: boolean;
  categories: number;
  companies: number;
  /** 보유·관심 기업 수. */
  mine: number;
  problems: number;
}

/** 허브 묶음(GICS 대섹터 기준). 카탈로그에 없는 섹터 파일은 마지막 "미분류" 묶음. */
export interface VcCatalogGroup {
  id: string;
  name: string;
  /** 묶음(L1) 기준색 — 묶음 안 분류 섹터의 색. */
  color?: string | null;
  sectors: VcCatalogCard[];
}

/** 분류 트리 노드. 최상위(대분류)는 `children` 을, 말단(중분류)은 `companies` 를 가진다. */
export interface VcCategory {
  id: string;
  code: string;
  name: string;
  /** 단계 스트립용 짧은 이름(최상위만). */
  short: string | null;
  desc: string | null;
  /** 분류 색 — 화면은 CSS 변수 `--c` 로 받는다. */
  color: string | null;
  order: number;
  /** 시장 규모 한 줄(중분류). */
  market: string | null;
  children: VcCategory[];
  /** **주 소속(primary)** 기업 id 만. 다중 소속은 카드의 ＋태그로 보인다. */
  companies: string[];
}

export interface VcCompany {
  name: string;
  /** 영문 이름. name 과 같으면 서버가 null 로 보낸다. */
  en: string | null;
  ticker: string | null;
  exchange: string | null;
  country: string | null;
  other_countries: string[];
  listed: boolean;
  role: string | null;
  points: string[];
  /** 소속 분류 코드 전부(주 소속 포함). */
  categories: string[];
  primary: string;
  src: string[];
  /** 판정 근거 링크(IR·SEC) — 분류 섹터에만 있다. */
  url?: string | null;
  held: boolean;
  watch: boolean;
}

export interface VcThesis {
  src: string;
  text: string;
}

export interface VcSource {
  tag: string;
  file: string;
  note: string | null;
}

export interface VcSectorDetail {
  sector: {
    code: string;
    name: string;
    en: string | null;
    desc: string | null;
    color?: string | null;
    problems: string[];
  };
  categories: VcCategory[];
  /** [from, to] 분류 코드 쌍 — 최상위끼리도, 중분류끼리도 섞여 온다. */
  flows: [string, string][];
  companies: Record<string, VcCompany>;
  theses: VcThesis[];
  sources: VcSource[];
}

// ── fetch ─────────────────────────────────────────────────────────────────────

async function request<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "API unreachable");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const env = data as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    throw new ApiError(
      res.status,
      env?.error?.code ?? "INTERNAL_ERROR",
      env?.error?.message ?? `Request failed (${res.status})`,
      env?.error?.details,
    );
  }
  return data as T;
}

export function getValueChainSectors(): Promise<VcSectorSummary[]> {
  return request<VcSectorSummary[]>("/api/v1/research/valuechain/sectors");
}

export function getValueChainCatalog(): Promise<VcCatalogGroup[]> {
  return request<VcCatalogGroup[]>("/api/v1/research/valuechain/catalog");
}

export function getValueChainSector(code: string): Promise<VcSectorDetail> {
  return request<VcSectorDetail>(
    `/api/v1/research/valuechain/${encodeURIComponent(code)}`,
  );
}

// ── react-query 훅 ────────────────────────────────────────────────────────────
// 분류 원본은 TTL 파일이라 자주 바뀌지 않는다 — 10분 stale.

export function useValueChainSectors() {
  return useQuery({
    queryKey: ["valuechain", "sectors"],
    queryFn: getValueChainSectors,
    staleTime: 10 * 60_000,
  });
}

export function useValueChainSector(code: string | null) {
  return useQuery({
    queryKey: ["valuechain", "sector", code],
    queryFn: () => getValueChainSector(code!),
    enabled: code != null,
    // 404 = 카탈로그에만 있는 "미작성" 섹터. 재시도해도 안 생기니 바로 안내를 띄운다.
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 3,
    staleTime: 10 * 60_000,
  });
}

export function useValueChainCatalog() {
  return useQuery({
    queryKey: ["valuechain", "catalog"],
    queryFn: getValueChainCatalog,
    staleTime: 10 * 60_000,
  });
}
