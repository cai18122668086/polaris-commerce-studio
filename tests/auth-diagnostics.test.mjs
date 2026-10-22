import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { build } from "esbuild";

async function load(entry) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "polaris-diagnostic-"));
  try {
    const output = path.join(directory, "entry.mjs");
    await build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", outfile: output, logLevel: "silent" });
    return await import(pathToFileURL(output).href);
  } finally { await rm(directory, { recursive: true, force: true }); }
}

const diagnostic = {
  id: "auth_12345678-1234-1234-1234-123456789abc",
  occurred_at: "2026-10-22T08:00:00.000Z",
  phase: "email_verification", reason: "server", path: "/assets",
  elapsed_ms: 9000, http_status: 503, request_ids: ["req_abc123"],
};

test("authentication retries only transient failures and never a final 4xx or offline state", async () => {
  const { authFailureReason: reason, authFailureCanRetry: retry } = await load("lib/auth/diagnostic-payload.ts");
  assert.equal(reason(new Error("AUTH_CHECK_TIMEOUT"), true), "timeout");
  assert.equal(reason(new TypeError("fetch failed"), true), "network");
  assert.equal(reason(new Error(), true, 503), "server");
  assert.equal(reason(new Error(), false), "offline");
  assert.equal(retry("timeout"), true);
  assert.equal(retry("server", 503), true);
  assert.equal(retry("network", 401), false);
  assert.equal(retry("server", 403), false);
  assert.equal(retry("offline"), false);
  assert.equal(retry("unexpected"), false);
});

test("diagnostics whitelist fields and reject secret-bearing URLs or arbitrary request IDs", async () => {
  const { parseAuthDiagnostic: parse } = await load("lib/auth/diagnostic-payload.ts");
  assert.deepEqual(parse({ ...diagnostic, cookie: "private", email: "private", message: "secret" }), diagnostic);
  assert.equal(parse({ ...diagnostic, path: "/assets?token=secret" }), null);
  assert.equal(parse({ ...diagnostic, request_ids: ["token=secret"] }), null);
  assert.equal(parse({ ...diagnostic, http_status: 200 }), null);
  assert.equal(parse({ ...diagnostic, elapsed_ms: -1 }), null);
});

test("auth hooks correlate requests without inspecting their bodies", async () => {
  const { boundedAuthRequest } = await load("lib/auth/request-timeout.ts");
  const context = { url: "https://example.test/api/auth/session/refresh", requestInit: { method: "POST", credentials: "include", body: "private" } };
  const result = await boundedAuthRequest(context);
  assert.equal(result.url, context.url);
  assert.match(result.requestInit.headers.get("X-Request-Id"), /^[0-9a-f-]{36}$/);
  assert.equal(result.requestInit.credentials, "include");
  assert.equal(result.requestInit.body, "private");
  assert.ok(result.requestInit.signal);
});

test("frontend diagnostic endpoint bounds, deduplicates and sanitizes anonymous reports", async () => {
  const { POST } = await load("app/diagnostics/auth/route.ts");
  const lines = [];
  const warn = console.warn;
  console.warn = (...args) => lines.push(args.join(" "));
  const request = (data, origin = "http://localhost:4321") => new Request("http://localhost:4321/diagnostics/auth", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify(data) });
  try {
    const report = { ...diagnostic, cookie: "SECRET_COOKIE" };
    assert.equal((await POST(request(report))).status, 202);
    assert.equal((await POST(request(report))).status, 202);
    assert.equal(lines.length, 1);
    assert.ok(lines[0].includes(diagnostic.id));
    assert.ok(!lines[0].includes("SECRET_COOKIE"));
    assert.equal((await POST(request(report, "https://other.test"))).status, 403);
    assert.equal((await POST(request({ ...report, path: "/?token=private" }))).status, 400);
    assert.equal((await POST(request({ ...report, padding: "x".repeat(5000) }))).status, 413);
    for (let index = 0; index < 99; index++) {
      const id = `auth_12345678-1234-1234-1234-${String(index).padStart(12, "0")}`;
      assert.equal((await POST(request({ ...diagnostic, id }))).status, 202);
    }
    const limited = await POST(request({ ...diagnostic, id: "auth_ffffffff-ffff-ffff-ffff-ffffffffffff" }));
    assert.equal(limited.status, 429);
    assert.equal(limited.headers.get("Cache-Control"), "no-store");
  } finally { console.warn = warn; }
});


test("SDK-thrown HTTP responses retain their status and server request ID", async () => {
  const oldWindow = globalThis.window;
  globalThis.window = { location: { pathname: "/assets" } };
  Object.defineProperty(globalThis.navigator, "onLine", { value: true, configurable: true });
  try {
    const { createAuthDiagnostic, beginAuthDiagnostics } = await load("lib/auth/diagnostics.ts");
    beginAuthDiagnostics();
    const error = new Response(null, { status: 503, headers: { "X-Request-Id": "req_server_failure" } });
    const report = createAuthDiagnostic(error, "email_verification", performance.now());
    assert.equal(report.reason, "server");
    assert.equal(report.http_status, 503);
    assert.deepEqual(report.request_ids, ["req_server_failure"]);
  } finally {
    if (oldWindow === undefined) delete globalThis.window; else globalThis.window = oldWindow;
    delete globalThis.navigator.onLine;
  }
});
