export const AUTH_REQUEST_TIMEOUT_MS = 8000;

export function authRequestInit(requestInit: RequestInit, timeoutMs = AUTH_REQUEST_TIMEOUT_MS): RequestInit {
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = requestInit.signal
    ? AbortSignal.any([requestInit.signal, timeout])
    : timeout;
  return { ...requestInit, signal };
}

export async function boundedAuthRequest(context: { url: string; requestInit: RequestInit }) {
  return { url: context.url, requestInit: authRequestInit(context.requestInit) };
}

// Bound SDK work as well as fetch: session restoration may be waiting for a
// cross-tab refresh lock before it starts a request.
export async function withAuthTimeout<T>(operation: Promise<T>, timeoutMs = AUTH_REQUEST_TIMEOUT_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("AUTH_CHECK_TIMEOUT")), timeoutMs);
  });
  try {
    return await Promise.race([operation, timeout]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
