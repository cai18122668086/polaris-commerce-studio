import { ApiError } from "./api-error";

type ErrorEnvelope = {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
};

export function mapApiError(error: unknown, response?: Response): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError({
      kind: "aborted",
      code: "REQUEST_ABORTED",
      message: "请求已取消。",
      retryable: false,
    });
  }
  const envelope = isErrorEnvelope(error) ? error.error : undefined;
  if (response) {
    return new ApiError({
      kind: "http",
      status: response.status,
      code: envelope?.code ?? `HTTP_${response.status}`,
      message: envelope?.message ?? "请求未能完成。",
      details: envelope?.details,
      requestId:
        envelope?.request_id ?? response.headers.get("X-Request-Id") ?? undefined,
    });
  }
  return new ApiError({
    kind: "network",
    code: "NETWORK_ERROR",
    message: "网络连接失败，请检查网络后重试。",
  });
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof value.error === "object"
  );
}
