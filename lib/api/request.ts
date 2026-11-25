import { ApiError } from "./api-error";
import { mapApiError } from "./error-mapper";

export type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export function unwrapApiResponse<T>({ data, error, response }: ApiResult<T>): T {
  if (error !== undefined || !response.ok || data === undefined) {
    throw mapApiError(error, response);
  }
  return data;
}

/** A final 401 from the API: the visitor is not signed in (public pages stay browsable). */
export function isSignedOutError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** 402 from a submission: the workspace lacks credits; the UI offers 「充值积分」. */
export function isInsufficientCreditsError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 402 || error.code === "BUDGET_LIMIT_EXCEEDED");
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "请求未能完成，请稍后重试。";
}


export function errorDiagnostic(error: unknown): string {
  if (!(error instanceof ApiError)) return errorMessage(error);
  const metadata = [
    error.code,
    error.status !== undefined ? `HTTP ${error.status}` : null,
    error.requestId ? `请求 ${error.requestId}` : null,
    `可重试：${error.retryable ? "是" : "否"}`,
  ].filter(Boolean).join(" · ");
  return metadata ? `${error.message}（${metadata}）` : error.message;
}
