import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./generated/openapi";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

const requestMetadata: Middleware = {
  async onRequest({ request }) {
    const headers = new Headers(request.headers);
    headers.set("X-Request-Id", crypto.randomUUID());
    return new Request(request, { headers });
  },
};

export const apiClient = createClient<paths>({ baseUrl });
apiClient.use(requestMetadata);

export function createIdempotencyKey(): string {
  return crypto.randomUUID();
}
