import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/editing-flow-steps.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { EDITING_FLOW_STEPS, editingFlowSteps } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const base = { hasSource: false, hasTemplate: false, working: false, previewReady: false, finalReady: false };
const states = input => editingFlowSteps(input).map(step => step.state);

test("three steps in order, each pointing at its section", () => {
  assert.deepEqual(EDITING_FLOW_STEPS.map(step => step.label), ["选视频", "选模板", "预览确认"]);
  assert.deepEqual(EDITING_FLOW_STEPS.map(step => step.anchor), ["editing-source", "editing-templates", "editing-results"]);
});

test("a fresh page starts at choosing the video", () => {
  assert.deepEqual(states(base), ["current", "todo", "todo"]);
});

test("a template chosen first still leaves the video as the current step", () => {
  assert.deepEqual(states({ ...base, hasTemplate: true }), ["current", "done", "todo"]);
});

test("with video and template, review is current and its hint follows the real task state", () => {
  const ready = { ...base, hasSource: true, hasTemplate: true };
  assert.deepEqual(states(ready), ["done", "done", "current"]);
  assert.equal(editingFlowSteps(ready)[2].hint, "生成后在这里预览");
  assert.equal(editingFlowSteps({ ...ready, working: true })[2].hint, "正在生成");
  assert.equal(editingFlowSteps({ ...ready, working: true, previewReady: true })[2].hint, "预览已就绪，等你确认");
});

test("review is done only once a confirmed final exists", () => {
  const full = { ...base, hasSource: true, hasTemplate: true, previewReady: true };
  assert.equal(editingFlowSteps(full)[2].state, "current");
  assert.deepEqual(states({ ...full, finalReady: true }), ["done", "done", "done"]);
  assert.equal(editingFlowSteps({ ...full, finalReady: true })[2].hint, "可下载高清");
});
