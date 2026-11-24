import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { apiUrl, apiWebSocketUrl, resolveApiBaseUrl } from "../lib/api/base-url.ts";

const root = new URL("..", import.meta.url).pathname;

test("接口前缀：正式环境同源，预览子路径和完整地址都能拼接", () => {
  assert.equal(apiUrl("/api/v1/admin/overview", ""), "/api/v1/admin/overview");
  assert.equal(apiUrl("/api/v1/admin/overview", resolveApiBaseUrl("/site/")), "/site/api/v1/admin/overview");
  assert.equal(apiUrl("/api/v1/workspaces", resolveApiBaseUrl("http://localhost:8000")), "http://localhost:8000/api/v1/workspaces");
});

test("WebSocket 地址按页面协议选择 ws / wss", () => {
  assert.equal(apiWebSocketUrl("/api/ecommerce/session/stream?x=1", { href: "https://www.jgshai.cn/admin/accounts", protocol: "https:" }), "wss://www.jgshai.cn/api/ecommerce/session/stream?x=1");
  assert.equal(apiWebSocketUrl("/api/ecommerce/session/stream", { href: "http://127.0.0.1:3100/site/admin", protocol: "http:" }), "ws://127.0.0.1:3100/api/ecommerce/session/stream");
});

function sources(directory) {
  return readdirSync(path.join(root, directory)).flatMap((name) => {
    const file = path.join(directory, name);
    if (statSync(path.join(root, file)).isDirectory()) return sources(file);
    return /\.(ts|tsx)$/.test(name) ? [file] : [];
  });
}

test("直接请求后端接口时必须带上接口前缀（不能写死 fetch(\"/api…\")）", () => {
  const offenders = ["app", "components", "features", "lib"].flatMap(sources)
    .filter((file) => !file.startsWith(path.join("components", "video-studio")))
    .filter((file) => /(^|[^\w.])fetch\(\s*[`"']\/api/.test(readFileSync(path.join(root, file), "utf8")));
  assert.deepEqual(offenders, []);
});
