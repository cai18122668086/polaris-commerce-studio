import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./generated/openapi";

// Local-only integration defaults to the zero-cost compose API. A deployment
// must set an explicit public API base URL; this task does not deploy the app.
const baseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const requestMetadata: Middleware = {
  async onRequest({ request }) {
    const headers = new Headers(request.headers);
    headers.set("X-Request-Id", crypto.randomUUID());
    return new Request(request, { headers });
  },
};

export const apiClient = createClient<paths>({ baseUrl });
apiClient.use(requestMetadata);
