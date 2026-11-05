import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/access-session.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { VideoAccessSession } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; };
const allowed = { status: "allowed", userId: "verified-user-A" };

test("initial verification is loading, never a false access denial", async () => {
  const gate = deferred();
  const session = new VideoAccessSession(() => gate.promise);
  session.setPath("/video-studio/voices");
  const pending = session.check();
  assert.equal(session.snapshot().status, "checking");
  assert.equal(session.snapshot().userId, undefined);
  gate.resolve(allowed); await pending;
  assert.equal(session.snapshot().status, "allowed");
});

test("slow focus rechecks retain the exact verified editor identity", async () => {
  let gate;
  const session = new VideoAccessSession(() => gate ? gate.promise : Promise.resolve(allowed));
  session.setPath("/video-studio/voices"); await session.check();
  const userId = session.snapshot().userId;
  gate = deferred();
  const pending = session.check();
  assert.equal(session.snapshot().status, "allowed");
  assert.equal(session.snapshot().userId, userId);
  assert.equal(session.snapshot().checking, true);
  gate.resolve(allowed); await pending;
  assert.equal(session.snapshot().userId, userId);
});

test("focus, pageshow and visibility events share the in-flight request", async () => {
  let calls = 0; const gate = deferred();
  const session = new VideoAccessSession(() => { calls++; return gate.promise; });
  session.setPath("/video-studio/create");
  const first = session.check();
  assert.equal(session.check(), first); assert.equal(session.check(), first);
  await Promise.resolve(); assert.equal(calls, 1);
  gate.resolve(allowed); await first;
});

test("network errors are recoverable and retain the same editor identity", async () => {
  let fail = false;
  const session = new VideoAccessSession(async () => { if (fail) throw new Error("network"); return allowed; });
  session.setPath("/video-studio/create"); await session.check();
  fail = true; await session.check();
  assert.equal(session.snapshot().status, "error");
  assert.equal(session.snapshot().userId, allowed.userId);
  fail = false; await session.check();
  assert.equal(session.snapshot().status, "allowed");
  assert.equal(session.snapshot().userId, allowed.userId);
});

test("explicit denial removes a previously verified identity", async () => {
  let result = allowed;
  const session = new VideoAccessSession(async () => result);
  session.setPath("/video-studio/voices"); await session.check();
  result = { status: "denied" }; await session.check();
  assert.equal(session.snapshot().status, "denied");
  assert.equal(session.snapshot().userId, undefined);
});

test("logout wins against a late successful validation", async () => {
  const gate = deferred();
  const session = new VideoAccessSession(() => gate.promise);
  session.setPath("/video-studio/voices");
  const pending = session.check(); session.revoke();
  gate.resolve(allowed); await pending;
  assert.equal(session.snapshot().status, "revoked");
  assert.equal(session.snapshot().userId, undefined);
});

test("navigation drops the old route identity and ignores its late response", async () => {
  let gate;
  const session = new VideoAccessSession(() => gate ? gate.promise : Promise.resolve(allowed));
  session.setPath("/video-studio/voices"); await session.check();
  gate = deferred(); const pending = session.check();
  session.setPath("/video-studio/create");
  assert.equal(session.snapshot().userId, undefined);
  gate.resolve(allowed); await pending;
  assert.equal(session.snapshot().path, "/video-studio/create");
  assert.equal(session.snapshot().status, "checking");
});

test("account switching hides the old account before the new grant arrives", async () => {
  let result = allowed;
  const session = new VideoAccessSession(async () => result);
  session.setPath("/video-studio/voices"); await session.check();
  session.sessionChanged();
  assert.equal(session.snapshot().userId, undefined);
  result = { status: "allowed", userId: "verified-user-B" }; await session.check();
  assert.equal(session.snapshot().userId, "verified-user-B");
});

test("a failed initial verification never gains access, even on retry", async () => {
  const session = new VideoAccessSession(async () => { throw new Error("timeout or malformed response"); });
  session.setPath("/video-studio/create"); await session.check(); await session.check();
  assert.equal(session.snapshot().status, "error");
  assert.equal(session.snapshot().userId, undefined);
});
