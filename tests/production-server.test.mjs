import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
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
