import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const utf8 = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const root = fileURLToPath(new URL("..", import.meta.url));

test("OpenAPI exposes every frontend integration operation", async () => {
  const document = JSON.parse(await utf8("docs/openapi-v1.json"));
  const expected = {
    "/api/v1/runtime": ["get"],
    "/api/v1/workspaces": ["get"],
    "/api/v1/workspaces/{workspace_id}/assets": ["get", "post"],
    "/api/v1/workspaces/{workspace_id}/assets/{asset_id}/access-url": ["post"],
    "/api/v1/workspaces/{workspace_id}/jobs": ["get", "post"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}": ["get"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/deliverables.zip": ["get"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/cancel": ["post"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/retry": ["post"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/plan/confirm": ["post"],
  };
  for (const [path, methods] of Object.entries(expected)) {
    assert.ok(document.paths[path], `${path} should exist`);
    for (const method of methods) {
      assert.ok(document.paths[path][method], `${method.toUpperCase()} ${path} should exist`);
    }
  }
});

test("business UI is API-backed and runtime capability is fail-closed", async () => {
  const businessFiles = [
    "app/assets/page.tsx",
    "app/dashboard/page.tsx",
    "app/jobs/page.tsx",
    "app/workspace/detail-pack/page.tsx",
    "app/workspace/local-edit/page.tsx",
    "components/task-drawer.tsx",
    "components/tool-sidebar.tsx",
  ];
  const contents = await Promise.all(businessFiles.map(utf8));
  assert.equal(contents.some((source) => source.includes("mock-data")), false);
  const runtime = await utf8("features/runtime/api/runtime.ts");
  assert.match(runtime, /availability === "available"/);
  assert.match(runtime, /execution === "provider"/);
  assert.match(runtime, /按 fail-closed 处理/);
  assert.match(runtime, /真实生成未启用/);
});

test("browser API client defaults to the same-origin edge proxy", async () => {
  const client = await utf8("lib/api/client.ts");
  assert.ok(client.includes(
    'process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || ""',
  ));
  assert.equal(client.includes("localhost:8000"), false);
});

test("runtime sources contain no non-loopback remote URLs", async () => {
  const files = await sourceFiles(["app", "components", "features", "lib"]);
  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(/https?:\/\/[^\s"'`<>]+/g)) {
      const url = new URL(match[0]);
      assert.ok(
        ["localhost", "127.0.0.1", "app.local"].includes(url.hostname),
        `${path.relative(root, file)} contains remote runtime URL ${url.origin}`,
      );
    }
  }
});

test("mock copy stays honest and icon actions have stable names", async () => {
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  const local = await utf8("app/workspace/local-edit/page.tsx");
  const helpPanel = await utf8("components/help-panel.tsx");
  const jobs = await utf8("app/jobs/page.tsx");

  assert.doesNotMatch(detail, /待 mock 流转/);
  assert.match(detail, /模拟流程完成 · 无真实图片产物/);
  assert.match(detail, /任务状态已完成 · 图片能力未知/);
  assert.match(detail, /runtime 已报告 Provider 执行/);
  assert.match(detail, /能力状态未知，确认入口保持关闭/);
  assert.match(local, /mock 模式不会调用图片 Provider，也没有真实产物/);
  assert.match(local, /能力状态未知，按 fail-closed 处理/);
  assert.match(helpPanel, /真实生成接入后才可下载/);
  assert.match(helpPanel, /能力状态未知，按 fail-closed 处理/);
  assert.match(helpPanel, /Provider 交付/);
  assert.match(
    await utf8("components/task-drawer.tsx"),
    /inert=\{open \? undefined : true\}/,
    "closed drawer controls must not remain focusable",
  );
  assert.doesNotMatch(
    jobs,
    /<button(?=[^>]*\btitle=)(?![^>]*\baria-label=)[^>]*>/,
    "title-only job action buttons are not accessible names",
  );
});

test("write actions use server allowed_actions as the only authority", async () => {
  const jobsPage = await utf8("app/jobs/page.tsx");
  const drawer = await utf8("components/task-drawer.tsx");
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  const local = await utf8("app/workspace/local-edit/page.tsx");
  const mutations = await utf8("features/jobs/api/jobs.ts");

  for (const source of [jobsPage, drawer, detail, local]) {
    assert.match(source, /allowsJobAction\(/);
  }
  for (const action of ["cancel", "retry", "confirm_plan"]) {
    assert.match(
      mutations,
      new RegExp(`assertJobAction\\(input\\.allowedActions, "${action}"\\)`),
    );
  }
});

test("workflow pages submit the bounded inputs and failed-only retry scope", async () => {
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  const local = await utf8("app/workspace/local-edit/page.tsx");

  assert.match(local, /mediaKind: "mask"/);
  assert.match(
    local,
    /input: \{ source_asset_id: sourceAsset\.id, selection_mask_asset_id: mask\.id \}/,
  );
  assert.match(
    local,
    /configuration: \{ instruction: prompt\.trim\(\), output_format: "png", quality \}/,
  );
  assert.match(
    detail,
    /input: \{ product_groups: \[\{ group_key: "primary-product", asset_ids: sources\.map/,
  );
  for (const source of [detail, local]) {
    assert.match(source, /scope: "failed"/);
  }
});


test("mask editor exposes brush, eraser, and rectangle authority tools", async () => {
  const editor = await utf8("components/mask-editor.tsx");
  assert.match(editor, /"brush" \| "eraser" \| "rectangle"/);
  assert.match(editor, /tool === "rectangle"/);
  assert.match(editor, /context\.fillRect\(left, top, width, height\)/);
  assert.match(editor, /aria-label="矩形框选"/);
  assert.match(editor, /disabled=\{!ready \|\| tool === "rectangle"\}/);
});

async function sourceFiles(directories) {
  const results = [];
  for (const directory of directories) {
    await walk(path.join(root, directory), results);
  }
  return results;
}

async function walk(directory, results) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "generated") continue;
      await walk(target, results);
    } else if (/\.(?:ts|tsx|js|jsx|css)$/.test(entry.name)) {
      results.push(target);
    }
  }
}
