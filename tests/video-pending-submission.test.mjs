import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/pending-submission.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { ABSENT_AFTER_MS, encodePending, decodePending, pendingOutcome } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const isBody = value => typeof value === "object" && value !== null && typeof value.request_id === "string";
const body = { request_id: "r1", kind: "lipsync", avatar_id: "a" };

test("round-trips the request with the time it was saved", () => {
  assert.deepEqual(decodePending(encodePending(body, 1000), isBody), { body, savedAt: 1000 });
});

test("older bare-body records still decode, as long since saved", () => {
  assert.deepEqual(decodePending(JSON.stringify(body), isBody), { body, savedAt: 0 });
});

test("garbage or foreign records are ignored", () => {
  assert.equal(decodePending("not json", isBody), undefined);
  assert.equal(decodePending(JSON.stringify({ body: { x: 1 } }), isBody), undefined);
  assert.equal(decodePending(null, isBody), undefined);
});

test("a received request is shown, never re-sent", () => {
  assert.equal(pendingOutcome({ received: true }, 0, 5), "found");
});

test("a missing request waits while it could still be in flight, then counts as not received", () => {
  assert.equal(pendingOutcome({ received: false }, 1000, 1000 + ABSENT_AFTER_MS - 1), "wait");
  assert.equal(pendingOutcome({ received: false }, 1000, 1000 + ABSENT_AFTER_MS), "absent");
});
