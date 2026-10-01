// 영상 요약(/news/video) 전용 클라이언트 — `GET /api/v1/news/videos` · `POST /api/v1/news/videos/refresh`.
//
// ⚠️`lib/api.ts` 의 `request()` 는 모듈 private 이라 가져올 수 없다. 공개된
//   `API_BASE_URL` · `ApiError` 만 가져와 같은 에러 봉투 처리를 한다(`lib/api-coverage.ts` 와 같은 방식).
// ⚠️summary_ko 는 status 가 done 일 때만 있다. pending(Plaud 전사 없음)·failed(LLM 실패)는 null —
//   화면이 빈칸을 "요약 없음"으로 그리고 이유(error)를 보인다. 실패 문구를 요약 자리에 넣지 않는다.
import { API_BASE_URL, ApiError } from "@/lib/api";

export type VideoStatus = "done" | "pending" | "failed" | (string & {});

export interface VideoDigest {
  id: number;
  plaud_file_id: string;
  title: string;
  source_tag: string;
  /** 제목의 YYMMDD — 영상 날짜(YYYY-MM-DD). */
  video_date: string;
  channel: string;
  /** Plaud 녹음 시작(UTC aware ISO). 모르면 null. */
  recorded_at: string | null;
  summary_ko: string | null;
  status: VideoStatus;
  error: string | null;
  model: string | null;
  updated_at: string | null;
}

export interface VideoDigestList {
  days: number;
  schedule: string;
  items: VideoDigest[];
  source: {
    last_ok_at: string | null;
    last_error_at: string | null;
    last_error_kind: string | null;
    last_error_message: string | null;
  } | null;
  last_job: {
    status: string;
    created_at: string | null;
    finished_at: string | null;
    error_message: string | null;
  } | null;
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init);
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
  return data as T;
}

export function getVideoDigests(days = 30): Promise<VideoDigestList> {
  return call<VideoDigestList>(`/api/v1/news/videos?days=${days}`);
}

/** "지금 확인" — 이미 대기·실행 중이면 queued=false. */
export function refreshVideoDigests(): Promise<{ queued: boolean; job_id: string | null }> {
  return call(`/api/v1/news/videos/refresh`, { method: "POST" });
}
