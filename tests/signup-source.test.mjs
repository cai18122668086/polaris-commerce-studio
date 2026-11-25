import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const utf8 = (relativePath) => readFile(path.join(root, relativePath), "utf8");

async function importBundled(entry) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "polaris-signup-source-"));
  const output = path.join(directory, "module.mjs");
  await build({ absWorkingDir: root, entryPoints: [entry], bundle: true, format: "esm", platform: "node", outfile: output, logLevel: "silent" });
  const importedModule = await import(`${pathToFileURL(output).href}?t=${Date.now()}`);
  await rm(directory, { recursive: true, force: true });
  return importedModule;
}

function fakeStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

test("signup source is captured from ?from= and expires after 30 days", async () => {
  const source = await importBundled("lib/auth/signup-source.ts");
  globalThis.window = {};
  globalThis.localStorage = fakeStorage();
  const day = 24 * 60 * 60 * 1000;
  assert.equal(source.pendingSignupSource(), null);
  source.captureSignupSource("?from=XHS-01&utm=x", 1000);
  assert.equal(source.pendingSignupSource(1000 + day), "xhs-01");
  // 后点的链接覆盖前一个；格式不对的不覆盖
  source.captureSignupSource("?from=dy-02", 2000);
  source.captureSignupSource("?from=%3Cscript%3E", 3000);
  source.captureSignupSource("?other=1", 4000);
  assert.equal(source.pendingSignupSource(2000 + day), "dy-02");
  assert.equal(source.pendingSignupSource(2000 + 31 * day), null);
  assert.equal(globalThis.localStorage.getItem("polaris.signup-source"), null);
  globalThis.localStorage.setItem("polaris.signup-source", "not json");
  assert.equal(source.pendingSignupSource(), null);
  delete globalThis.window;
  delete globalThis.localStorage;
});

test("API client sends the signup source header and the root provider captures it", async () => {
  const client = await utf8("lib/api/client.ts");
  assert.match(client, /headers\.set\("X-Signup-Source", source\)/);
  const providers = await utf8("app/providers.tsx");
  assert.match(providers, /captureSignupSource\(window\.location\.search\)/);
  const main = await utf8("backend/app/main.py");
  assert.match(main, /"X-Signup-Source"/);
});
