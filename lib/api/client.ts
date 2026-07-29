import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./generated/openapi";

// Browser requests default to the current origin. Internal and production deployments
// route /api through the edge proxy; local development may opt into an explicit URL.
const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "";

const requestMetadata: Middleware = {
  async onRequest({ request }) {
    const headers = new Headers(request.headers);
    headers.set("X-Request-Id", crypto.randomUUID());
    return new Request(request, { headers });
  },
};

export const apiClient = createClient<paths>({ baseUrl });
apiClient.use(requestMetadata);
