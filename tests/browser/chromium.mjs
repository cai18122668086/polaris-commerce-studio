import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

function browserExecutable() {
  const explicit = process.env.POLARIS_BROWSER_EXECUTABLE;
  if (explicit) {
    if (!existsSync(explicit)) throw new Error(`Configured Chromium does not exist: ${explicit}`);
    return explicit;
  }
  if (process.env.CI) {
    throw new Error("CI must install Chromium and set POLARIS_BROWSER_EXECUTABLE before browser tests");
  }
  const candidates = process.platform === "win32"
    ? ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"]
    : process.platform === "darwin"
      ? ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
      : ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
  const executable = candidates.find(existsSync);
  if (!executable) throw new Error("Chromium is required; set POLARIS_BROWSER_EXECUTABLE to an installed browser");
  return executable;
}

export async function launchChromium({ label = "production", timeoutMs = 30_000 } = {}) {
  const executable = browserExecutable();
  const profile = await mkdtemp(path.join(os.tmpdir(), "polaris-browser-"));
  let output = "";
  let spawnError;
  let probe = "Chromium has not written DevToolsActivePort";
  const child = spawn(executable, [
    "--headless=new", "--disable-background-networking", "--disable-component-update",
    "--disable-default-apps", "--disable-extensions", "--disable-gpu",
    "--disable-features=OptimizationHints,OptimizationGuideModelDownloading",
    "--disable-dev-shm-usage", "--no-default-browser-check", "--no-first-run", "--no-sandbox",
    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const capture = chunk => { output = (output + chunk).slice(-24_000); };
  child.stdout.on("data", capture);
  child.stderr.on("data", capture);
  child.on("error", error => { spawnError = error; });
  let closed = false;
  async function close() {
    if (closed) return;
    closed = true;
    try {
      if (child.pid && child.exitCode === null && child.signalCode === null) {
        if (process.platform === "win32") {
          const killer = spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore", windowsHide: true });
          await once(killer, "exit");
        } else {
          const exited = once(child, "exit");
          child.kill("SIGTERM");
          await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 2_000))]);
          if (child.exitCode === null && child.signalCode === null) {
            child.kill("SIGKILL");
            await exited;
          }
        }
      }
    } finally {
      try {
        if (process.env.POLARIS_BROWSER_OUTPUT) {
          const directory = path.resolve(process.env.POLARIS_BROWSER_OUTPUT);
          await mkdir(directory, { recursive: true });
          const safeLabel = label.replace(/[^a-zA-Z0-9_-]/g, "_");
          await writeFile(path.join(directory, `chromium-${safeLabel}.log`), `executable=${executable}\nlast_probe=${probe}\n${output}`);
        }
      } finally {
        await rm(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 125 });
      }
    }
  }
  try {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`Chromium exited: code=${child.exitCode}, signal=${child.signalCode}`);
      }
      try {
        // The browser allocates its own port and publishes it in this fresh
        // profile. Reserving and releasing a TCP port before spawn was racy.
        const activePort = await readFile(path.join(profile, "DevToolsActivePort"), "utf8");
        const port = Number(activePort.split(/\r?\n/)[0]);
        if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid DevToolsActivePort");
        const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1_000) });
        probe = `DevTools HTTP ${response.status}`;
        if (response.ok) {
          const targets = await response.json();
          const target = targets.find(row => row.type === "page" && row.webSocketDebuggerUrl);
          if (target) return { target, close };
          probe = "DevTools is responding but has no page target";
        }
      } catch (error) {
        probe = error.code === "ENOENT" ? "Chromium has not written DevToolsActivePort" : error.message;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error(`Chromium debugging target did not become ready: ${probe}`);
  } catch (error) {
    const diagnostic = `${error.message}\nexecutable=${executable}\nlast_probe=${probe}\n${output}`;
    await close();
    throw new Error(diagnostic, { cause: error });
  }
}
