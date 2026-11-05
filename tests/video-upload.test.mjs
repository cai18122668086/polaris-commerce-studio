import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["lib/api/upload.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { uploadWithProgress } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const progressModule = await build({ entryPoints: ["features/video-studio/voice-progress.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { estimatedVoiceProgress } = await import(`data:text/javascript;base64,${Buffer.from(progressModule.outputFiles[0].text).toString("base64")}`);

class FakeXHR {
  static last;
  upload = {}; headers = {}; status = 200; statusText = "OK"; responseText = '{"id":"owned-voice"}';
  constructor() { FakeXHR.last = this; }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(key, value) { this.headers[key] = value; }
  getAllResponseHeaders() { return "Content-Type: application/json\r\nX-Request-Id: test-request"; }
  send(body) { this.body = body; }
  abort() { this.aborted = true; this.onabort?.(); }
}

globalThis.XMLHttpRequest = FakeXHR;

test("estimated processing reaches near 90 quickly, slows down and never claims completion", () => {
  const early = estimatedVoiceProgress(18);
  assert.ok(early >= 85 && early <= 90);
  assert.ok(estimatedVoiceProgress(60) - early < early - estimatedVoiceProgress(0));
  let previous = 0;
  for (let seconds = 0; seconds <= 3600; seconds++) {
    const progress = estimatedVoiceProgress(seconds);
    assert.ok(progress >= previous && progress <= 98);
    previous = progress;
  }
});

test("authenticated upload preserves metadata, multipart body and real byte progress", async () => {
  const form = new FormData(); form.append("file", new Blob(["sample"]), "mine.wav");
  const updates = [];
  const request = new Request("https://local.example/api/upload", { method: "POST", body: form, credentials: "include", headers: { "X-Request-Id": "same-intent", "anti-csrf": "fixture" } });
  const pending = uploadWithProgress(form, value => updates.push(value))(request);
  const xhr = FakeXHR.last;
  assert.equal(xhr.withCredentials, true);
  assert.equal(xhr.headers["x-request-id"], "same-intent");
  assert.equal(xhr.headers["anti-csrf"], "fixture");
  assert.equal(xhr.headers["content-type"], undefined);
  assert.equal(xhr.body, form);
  xhr.upload.onprogress({ loaded: 25, total: 100, lengthComputable: true });
  assert.deepEqual(updates.at(-1), { loaded: 25, total: 100, complete: false });
  xhr.upload.onload({ loaded: 100, total: 100, lengthComputable: true });
  assert.equal(updates.at(-1).complete, true);
  xhr.onload(); const response = await pending;
  assert.equal(response.headers.get("X-Request-Id"), "test-request");
  assert.equal((await response.json()).id, "owned-voice");
});

test("unknown upload length stays indeterminate and final HTTP denial reaches API middleware", async () => {
  const updates = [];
  const pending = uploadWithProgress(new FormData(), value => updates.push(value))(new Request("https://local.example/upload", { method: "POST" }));
  const xhr = FakeXHR.last;
  xhr.upload.onprogress({ loaded: 25, total: 0, lengthComputable: false });
  assert.equal(updates[0].total, undefined);
  xhr.status = 401; xhr.responseText = '{"error":{"code":"UNAUTHORISED"}}'; xhr.onload();
  assert.equal((await pending).status, 401);
});

test("aborting an upload ends its request without retrying a creation", async () => {
  const controller = new AbortController();
  const pending = uploadWithProgress(new FormData(), () => {})(new Request("https://local.example/upload", { method: "POST", signal: controller.signal }));
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(FakeXHR.last.aborted, true);
});

test("a broken connection rejects instead of inventing a successful upload", async () => {
  const pending = uploadWithProgress(new FormData(), () => {})(new Request("https://local.example/upload", { method: "POST" }));
  FakeXHR.last.onerror();
  await assert.rejects(pending, TypeError);
});
