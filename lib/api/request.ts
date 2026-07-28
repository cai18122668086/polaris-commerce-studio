import { mapApiError } from "./error-mapper";

type ApiResult<T> = {
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

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "请求未能完成，请稍后重试。";
}
