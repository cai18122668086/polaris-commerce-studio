import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/task-center.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { taskCenterItems, settledSince } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const edit = (over = {}) => ({ kind: "editing", task_id: "0f8fad5b-d9cb-469f-a165-70867728950e", project_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7", project_title: "春季新品", status: "running", created_at: "2026-11-21T08:00:00Z", preview: null, ...over });
const job = (over = {}) => ({ id: "j1", kind: "lipsync", status: "running", created_at: "2026-11-21T09:00:00Z", snapshot: { draft: { name: "口播一" } }, ...over });

test("finished and failed generations are left out; running ones link to 我的作品", () => {
  const items = taskCenterItems([], [job(), job({ id: "j2", status: "completed" }), job({ id: "j3", status: "failed" })]);
  assert.deepEqual(items.map(i => [i.id, i.label, i.href]), [["generation:j1", "口播生成中", "/video-studio/works"]]);
});

test("items waiting for the user come first, then newest", () => {
  const items = taskCenterItems([edit({ status: "awaiting_review" }), edit({ task_id: "x", created_at: "2026-11-21T10:00:00Z" })], [job()]);
  assert.deepEqual(items.map(i => i.label), ["待确认预览", "正在剪辑", "口播生成中"]);
  assert.equal(items[0].needsUser, true);
});

test("avatar templates waiting for approval point to the avatar library", () => {
  const [item] = taskCenterItems([], [job({ kind: "h3_template", status: "awaiting_review", snapshot: null })]);
  assert.deepEqual([item.title, item.label, item.href, item.needsUser], ["定制形象", "形象待确认", "/video-studio/avatars", true]);
});

test("a running task that finished or now needs the user is reported once", () => {
  const before = taskCenterItems([edit()], [job()]);
  const after = taskCenterItems([edit({ status: "awaiting_review" })], []);
  assert.deepEqual(settledSince(before, after).map(i => i.id).sort(), ["editing:0f8fad5b-d9cb-469f-a165-70867728950e", "generation:j1"]);
  assert.deepEqual(settledSince(after, after), []);
});
