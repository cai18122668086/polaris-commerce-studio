import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { launchChromium } from "./browser/chromium.mjs";

function restore(name, previous) {
  if (previous === undefined) delete process.env[name];
  else process.env[name] = previous;
}

test("CI refuses to silently use an unconfigured system browser", async () => {
  const ci = process.env.CI;
  const executable = process.env.POLARIS_BROWSER_EXECUTABLE;
  try {
    process.env.CI = "true";
    delete process.env.POLARIS_BROWSER_EXECUTABLE;
    await assert.rejects(launchChromium(), /CI must install Chromium/);
    process.env.POLARIS_BROWSER_EXECUTABLE = path.join(os.tmpdir(), "missing-polaris-chromium", "browser");
    await assert.rejects(launchChromium(), /Configured Chromium does not exist/);
  } finally {
    restore("CI", ci);
    restore("POLARIS_BROWSER_EXECUTABLE", executable);
  }
});

test("a browser startup failure preserves executable and process diagnostics", async () => {
  const executable = process.env.POLARIS_BROWSER_EXECUTABLE;
  const output = process.env.POLARIS_BROWSER_OUTPUT;
  const directory = await mkdtemp(path.join(os.tmpdir(), "polaris-startup-test-"));
  try {
    // Node is a real executable that rejects Chromium flags immediately. This
    // exercises failed-process handling without waiting for a 30-second probe.
    process.env.POLARIS_BROWSER_EXECUTABLE = process.execPath;
    process.env.POLARIS_BROWSER_OUTPUT = directory;
    await assert.rejects(launchChromium({ label: "failure", timeoutMs: 5_000 }), error => {
      assert.match(error.message, /Chromium exited/);
      assert.ok(error.message.includes(`executable=${process.execPath}`));
      assert.match(error.message, /bad option|unknown option|unrecognized option/i);
      return true;
    });
    const log = await readFile(path.join(directory, "chromium-failure.log"), "utf8");
    assert.ok(log.includes(`executable=${process.execPath}`));
    assert.match(log, /--headless/);
  } finally {
    restore("POLARIS_BROWSER_EXECUTABLE", executable);
    restore("POLARIS_BROWSER_OUTPUT", output);
    await rm(directory, { recursive: true, force: true });
  }
});
