import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/active-works.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { activeWorkView, matchesKeyword } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const work = (over = {}) => ({
  kind: "editing",
  task_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
  project_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  project_title: "春季新品口播",
  status: "running",
  created_at: "2026-11-20T08:00:00Z",
  preview: null,
  ...over,
});

test("an editing task links back to its own card on the editing page", () => {
  const view = activeWorkView(work());
  assert.equal(view.href, "/video-studio/editing?project=7c9e6679-7425-40de-944b-e07fc1f90ae7#editing-task-0f8fad5b-d9cb-469f-a165-70867728950e");
  assert.match(view.href, /#editing-task-[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/);
  assert.equal(view.label, "正在剪辑");
  assert.equal(view.polling, true);
  assert.equal(view.needsUser, false);
});

test("a preview waiting for confirmation asks the user to confirm it", () => {
  const view = activeWorkView(work({ status: "awaiting_review", preview: { url: "/p.mp4" } }));
  assert.deepEqual([view.label, view.action, view.needsUser, view.polling], ["待确认预览", "去确认", true, false]);
});

test("planning tasks open the project, since planning has no task card anchor", () => {
  const prepared = activeWorkView(work({ kind: "planning", status: "prepared" }));
  assert.equal(prepared.href, "/video-studio/editing?project=7c9e6679-7425-40de-944b-e07fc1f90ae7");
  assert.deepEqual([prepared.label, prepared.action, prepared.needsUser], ["待继续", "继续剪辑", true]);
  assert.equal(activeWorkView(work({ kind: "planning", status: "queued" })).label, "正在编排");
  assert.equal(activeWorkView(work({ kind: "planning", status: "failed" })).label, "编排未完成");
});

test("failures stay visible and lead back to the original task instead of a new one", () => {
  const view = activeWorkView(work({ status: "failed" }));
  assert.deepEqual([view.label, view.action, view.needsUser, view.polling], ["剪辑未完成", "查看原任务", true, false]);
});

test("ids are encoded so a malformed id cannot break out of the link", () => {
  const view = activeWorkView(work({ project_id: "a b&c", task_id: "x#y" }));
  assert.equal(view.href, "/video-studio/editing?project=a%20b%26c#editing-task-x%23y");
});

test("keyword search matches project titles like the finished works list", () => {
  assert.equal(matchesKeyword(work(), ""), true);
  assert.equal(matchesKeyword(work(), " 新品 "), true);
  assert.equal(matchesKeyword(work(), "秋季"), false);
});
