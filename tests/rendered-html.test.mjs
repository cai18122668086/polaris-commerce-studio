import assert from "node:assert/strict";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the finished product shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>首页｜极光商绘<\/title>/i);
  assert.match(html, /一键直达任务/);
  assert.match(html, /全品类/);
  assert.match(html, /一句话改图/);
  assert.match(html, /商品详情图/);
  assert.doesNotMatch(html, /Your site is taking shape|codex-preview/i);
});

test("core product routes render", async () => {
  for (const path of [
    "/workspace/local-edit",
    "/workspace/detail-pack",
    "/jobs",
    "/assets",
  ]) {
    const response = await render(path);
    assert.equal(response.status, 200, `${path} should render`);
  }
});
