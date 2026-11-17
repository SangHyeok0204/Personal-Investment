// 채용 공고(/careers) 전용 클라이언트 — `GET /api/v1/careers/postings`.
//
// ⚠️`lib/api.ts` 의 `request()` 는 모듈 private 이라 `lib/api-strategy.ts` 와 같은 방식으로 에러 봉투를 처리한다.
import { API_BASE_URL, ApiError } from "@/lib/api";

export interface JobPosting {
  company: string;
  /** 지원 가능 시기(접수기간). 모르면 "공고 확인" */
  apply_period: string;
  work_period: string;
  /** 인턴 / 신입 / 신입·인턴 / 직급 미표기 */
  kind: string;
  role: string;
  /** 한국어 출처 이름 — 대학 게시판은 게시판 이름, 합친 공고는 "금투협, KKB" */
  source: string;
  url: string;
  category: string;
  location: string;
  hire_type: string;
  /** YYYY-MM-DD, 모르면 "" */
  deadline: string;
  posted: string;
  title: string;
}

export interface JobPostings {
  generated_at: string | null;
  since: string | null;
  today: string;
  closed_dropped: number;
  hidden_by_category: Record<string, number>;
  sources: { key: string; name: string; url: string; count: number; error: string | null }[];
  jobs: JobPosting[];
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export async function getJobPostings(): Promise<JobPostings> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/careers/postings`);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "API unreachable");
  }
  const text = await res.text();
  const data = text ? (JSON.parse(text) as unknown) : null;
  if (!res.ok) {
    const env = data as ErrorEnvelope | null;
    throw new ApiError(
      res.status,
      env?.error?.code ?? "INTERNAL_ERROR",
      env?.error?.message ?? `Request failed (${res.status})`,
      env?.error?.details,
    );
  }
  return data as JobPostings;
}
