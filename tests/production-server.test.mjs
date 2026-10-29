import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import os from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const host = "127.0.0.1";
const routes = [
  "/",
  "/assets",
  "/jobs",
  "/dashboard",
  "/workspace/local-edit",
  "/workspace/detail-pack",
  "/auth/login",
];

test("production server serves every compiled module and stylesheet", async () => {
  const port = await reservePort();
  const cli = path.join(root, "node_modules", "vinext", "dist", "cli.js");
  const child = spawn(
    process.execPath,
    [cli, "start", "--hostname", host, "--port", String(port)],
    {
      cwd: root,
      env: { ...process.env, NODE_ENV: "production" },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += chunk;
  });
  child.stderr.on("data", (chunk) => {
    output += chunk;
  });

  try {
    await waitForServer(`http://${host}:${port}/`, child, () => output);
    const staticUrls = new Set();

    for (const route of routes) {
      const response = await fetch(`http://${host}:${port}${route}`);
      assert.equal(response.status, 200, `${route} should render`);
      assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
      const html = await response.text();
      assertNamedInteractiveControls(html, route);
      assert.doesNotMatch(
        html,
        /\/assets\/[^"'\\\s<>]+\.(?:js|css)\b/,
        `${route} must not emit chunks beneath the /assets product route`,
      );
      for (const match of html.matchAll(
        /\/_polaris-static\/[A-Za-z0-9._/-]+\.(?:js|css)\b/g,
      )) {
        staticUrls.add(match[0]);
      }
    }

    assert.ok(staticUrls.size > 10, "production HTML should expose compiled assets");
    await assertStaticGraph(`http://${host}:${port}`, staticUrls);

    const businessRoute = await fetch(`http://${host}:${port}/assets`);
    assert.equal(businessRoute.status, 200);
    assert.match(businessRoute.headers.get("content-type") ?? "", /^text\/html\b/i);

    await assertBrowserAuthContract(`http://${host}:${port}`);
  } finally {
    await stopProcessTree(child);
  }
});

async function reservePort() {
  const server = createServer();
  server.listen(0, host);
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const port = address.port;
  const closed = once(server, "close");
  server.close();
  await closed;
  return port;
}

async function waitForServer(url, child, output) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`production server exited early:\n${output()}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The process has not bound the port yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`production server did not become ready:\n${output()}`);
}

async function assertStaticGraph(origin, initialUrls) {
  const pending = [...initialUrls];
  const visited = new Set();
  while (pending.length > 0) {
    const url = pending.pop();
    if (!url || visited.has(url)) continue;
    visited.add(url);
    const response = await fetch(`${origin}${url}`);
    assert.equal(response.status, 200, `${url} should be served`);
    const contentType = response.headers.get("content-type") ?? "";
    assert.match(
      contentType,
      url.endsWith(".css") ? /text\/css/i : /javascript/i,
      `${url} should have the expected MIME type`,
    );
    if (url.endsWith(".js")) {
      const source = await response.text();
      for (const match of source.matchAll(
        /["'](\/_polaris-static\/[A-Za-z0-9._/-]+\.js)["']/g,
      )) {
        if (!visited.has(match[1])) pending.push(match[1]);
      }
    }
  }
}

function assertNamedInteractiveControls(html, route) {
  for (const match of html.matchAll(/<(button|a)\b([^>]*)>([\s\S]*?)<\/\1>/gi)) {
    const [, tag, attributes, body] = match;
    const ariaLabel = attributes.match(/\baria-label="([^"]+)"/i)?.[1]?.trim();
    const visibleText = body
      .replace(/<svg\b[\s\S]*?<\/svg>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&[a-z]+;/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
    assert.ok(
      ariaLabel || visibleText,
      `${route} contains an unnamed <${tag}> control: ${match[0].slice(0, 180)}`,
    );
  }
}

async function assertBrowserAuthContract(origin) {
  const executable = findBrowserExecutable();
  assert.ok(
    executable,
    "A Chromium browser is required for the production authentication regression",
  );
  const debugPort = await reservePort();
  const profile = await mkdtemp(path.join(os.tmpdir(), "polaris-browser-"));
  const browserProcess = spawn(
    executable,
    [
      "--headless=new",
      "--disable-background-networking",
      "--disable-component-update",
      "--disable-default-apps",
      "--disable-extensions",
      "--disable-features=OptimizationHints,OptimizationGuideModelDownloading",
      "--disable-gpu",
      "--no-default-browser-check",
      "--no-first-run",
      "--no-sandbox",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { stdio: "ignore", windowsHide: true },
  );

  let cdp;
  try {
    const target = await waitForBrowserTarget(debugPort, browserProcess);
    cdp = await CdpClient.connect(target.webSocketDebuggerUrl);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Accessibility.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: true,
    });

    await navigate(cdp, `${origin}/assets`);
    await waitForValue(cdp, `location.pathname === "/auth/login"`);
    assert.equal(
      await evaluate(
        cdp,
        `new URL(location.href).searchParams.get("returnTo")`,
      ),
      "/assets",
    );
    await waitForValue(
      cdp,
      `document.querySelector("#auth-title")?.textContent === "欢迎回来"`,
    );
    assert.equal(await accessibleName(cdp, "textbox", "邮箱"), "邮箱");
    assert.equal(await accessibleName(cdp, "textbox", "密码"), "密码");
    assert.equal(await accessibleName(cdp, "button", "登录"), "登录");
    assert.match(await accessibleName(cdp, "link", "免费注册"), /免费注册/);
    await assertAccessibleInteractiveNames(cdp, "/auth/login");
    await assertMobileTaskEntry(cdp, origin);
  } finally {
    cdp?.close();
    await stopProcessTree(browserProcess);
    await rm(profile, {
      recursive: true,
      force: true,
      maxRetries: 8,
      retryDelay: 125,
    });
  }
}

async function assertMobileTaskEntry(cdp, origin) {
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    document.cookie = "sFrontToken=" + btoa(JSON.stringify({ uid: "browser-test", ate: Date.now() + 3600000, up: {} })) + ";path=/";
    document.cookie = "st-last-access-token-update=" + Date.now() + ";path=/";
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === "string" ? input : input.url, location.href);
      let body;
      if (url.pathname.startsWith("/api/auth/")) body = { status: "OK", isVerified: true };
      else if (url.pathname === "/api/v1/workspaces") body = [{ id: "ws-browser-test", name: "Browser test", role: "owner" }];
      else if (url.pathname === "/api/v1/me") body = { id: "browser-test", display_name: "Browser test", email: "browser@example.invalid", email_verified: true, status: "active" };
      else if (url.pathname.endsWith("/jobs")) body = { items: [], next_cursor: null, total: 0 };
      else return originalFetch(input, init);
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    };
  ` });
  await navigate(cdp, origin);
  await waitForValue(cdp, `!!document.querySelector('[aria-label^="打开任务中心"] span')`);
  for (const width of [320, 390, 768]) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: true });
    const entry = await evaluate(cdp, `(() => {
      const button = document.querySelector('[aria-label^="打开任务中心"]');
      const label = button.querySelector('span');
      const rect = label.getBoundingClientRect();
      return { text: label.textContent, visible: getComputedStyle(label).display !== 'none' && rect.width > 0, inside: rect.left >= 0 && rect.right <= innerWidth };
    })()`);
    assert.equal(entry.text, "任务中心");
    assert.equal(entry.visible, true, width + "px should show the task label: " + JSON.stringify(entry));
    assert.equal(entry.inside, true, width + "px task label should fit the viewport");
  }
}

function findBrowserExecutable() {
  const candidates =
    process.platform === "win32"
      ? [
          "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
          "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
          "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
          "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        ]
      : process.platform === "darwin"
        ? [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
          ]
        : [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
          ];
  return candidates.find(existsSync);
}

async function waitForBrowserTarget(port, browserProcess) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (browserProcess.exitCode !== null) {
      throw new Error("Chromium exited before its debugging target was ready");
    }
    try {
      const response = await fetch(`http://${host}:${port}/json/list`);
      if (response.ok) {
        const targets = await response.json();
        const page = targets.find(
          (target) => target.type === "page" && target.webSocketDebuggerUrl,
        );
        if (page) return page;
      }
    } catch {
      // The debugging endpoint has not bound yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Chromium debugging target did not become ready");
}

async function navigate(cdp, url) {
  const loaded = cdp.waitFor("Page.loadEventFired");
  await cdp.send("Page.navigate", { url });
  await loaded;
}

async function accessibleName(cdp, role, includes) {
  const { nodes } = await cdp.send("Accessibility.getFullAXTree");
  const node = nodes.find(
    (candidate) =>
      candidate.role?.value === role &&
      candidate.name?.value?.includes(includes),
  );
  assert.ok(node, `Expected accessible ${role} containing "${includes}"`);
  return node.name.value;
}

async function assertAccessibleInteractiveNames(cdp, route) {
  const { nodes } = await cdp.send("Accessibility.getFullAXTree");
  const interactiveRoles = new Set([
    "button",
    "checkbox",
    "combobox",
    "link",
    "radio",
    "searchbox",
    "textbox",
  ]);
  for (const node of nodes) {
    if (node.ignored || !interactiveRoles.has(node.role?.value)) continue;
    const name = node.name?.value?.trim() ?? "";
    assert.ok(name, `${route} contains an unnamed ${node.role.value}`);
    assert.doesNotMatch(
      name,
      /^\d+$/,
      `${route} contains a numeric-only ${node.role.value}: ${name}`,
    );
  }
}

async function waitForValue(cdp, expression) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (await evaluate(cdp, expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Browser condition did not become true: ${expression}`);
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }
  return result.result.value;
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result);
        return;
      }
      const listeners = this.listeners.get(message.method);
      if (!listeners?.length) return;
      this.listeners.delete(message.method);
      for (const listener of listeners) listener(message.params);
    });
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("CDP connection timed out")),
        10_000,
      );
      socket.addEventListener(
        "open",
        () => {
          clearTimeout(timeout);
          resolve();
        },
        { once: true },
      );
      socket.addEventListener(
        "error",
        () => {
          clearTimeout(timeout);
          reject(new Error("CDP connection failed"));
        },
        { once: true },
      );
    });
    return new CdpClient(socket);
  }

  send(method, params = {}) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  waitFor(method) {
    return new Promise((resolve) => {
      const listeners = this.listeners.get(method) ?? [];
      listeners.push(resolve);
      this.listeners.set(method, listeners);
    });
  }

  close() {
    this.socket.close();
  }
}

async function stopProcessTree(child) {
  if (child.exitCode !== null) return;
  if (process.platform === "win32") {
    const killer = spawn(
      "taskkill",
      ["/pid", String(child.pid), "/t", "/f"],
      { stdio: "ignore", windowsHide: true },
    );
    await once(killer, "exit");
  } else {
    child.kill("SIGTERM");
    await Promise.race([
      once(child, "exit"),
      new Promise((resolve) => setTimeout(resolve, 4_000)),
    ]);
    if (child.exitCode === null) child.kill("SIGKILL");
  }
}
