import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const utf8 = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("OpenAPI exposes every frontend integration operation", async () => {
  const document = JSON.parse(await utf8("docs/openapi-v1.json"));
  const expected = {
    "/api/v1/runtime": ["get"],
    "/api/v1/workspaces": ["get"],
    "/api/v1/workspaces/{workspace_id}/assets": ["get", "post"],
    "/api/v1/workspaces/{workspace_id}/assets/{asset_id}/access-url": ["post"],
    "/api/v1/workspaces/{workspace_id}/jobs": ["get", "post"],
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}": ["get"],
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
