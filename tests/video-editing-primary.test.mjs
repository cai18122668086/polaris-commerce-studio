import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/editing-primary.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { planningButtonLabel, workspaceActionLabel, CONFIRMING_HINT } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const idle = { busy: false, checking: false, arranging: false, uncertain: false, emptyResponse: false, render: undefined, arranged: false, recover: false, failed: false, blocked: false, unavailable: false, ready: false };
const internal = /回执|待核对|提交结果|调用/;

test("labels follow the four progress steps", () => {
  assert.equal(planningButtonLabel(idle), "开始智能剪辑");
  assert.equal(planningButtonLabel({ ...idle, checking: true }), "正在分析口播");
  assert.equal(planningButtonLabel({ ...idle, arranging: true }), "正在编排画面");
  assert.equal(planningButtonLabel({ ...idle, arranged: true, render: "running" }), "正在生成视频");
  assert.equal(planningButtonLabel({ ...idle, arranged: true, render: "awaiting_review" }), "确认效果，获取高清");
  assert.equal(planningButtonLabel({ ...idle, arranged: true, render: "completed" }), "查看高清成片");
  assert.equal(planningButtonLabel({ ...idle, failed: true }), "重试");
});

test("the paid step says so before it runs", () => {
  assert.equal(planningButtonLabel({ ...idle, ready: true }), "开始智能剪辑 · 不扣积分");
  assert.equal(planningButtonLabel({ ...idle, ready: true, credits: 40 }), "开始智能剪辑 · 40 积分");
});

test("unconfirmed submissions never show internal wording", () => {
  for (const state of [{ ...idle, uncertain: true }, { ...idle, emptyResponse: true }]) {
    const label = planningButtonLabel(state);
    assert.equal(label, "正在确认结果");
    assert.doesNotMatch(label, internal);
  }
  assert.equal(CONFIRMING_HINT, "正在确认结果，不会重复扣费");
});

test("busy wins over every other state so a second click is not invited", () => {
  assert.equal(planningButtonLabel({ ...idle, busy: true, ready: true, failed: true }), "正在提交…");
});

test("the outer action bar uses the same words", () => {
  const base = { busy: false, recognizing: false, transcriptReady: false };
  assert.equal(workspaceActionLabel(base), "开始智能剪辑");
  assert.equal(workspaceActionLabel({ ...base, credits: 40 }), "开始智能剪辑 · 40 积分");
  assert.equal(workspaceActionLabel({ ...base, credits: null }), "开始智能剪辑 · 不扣积分");
  assert.equal(workspaceActionLabel({ ...base, recognizing: true }), "正在分析口播");
  assert.equal(workspaceActionLabel({ ...base, phase: "rendering" }), "正在生成视频");
  assert.equal(workspaceActionLabel({ ...base, transcriptReady: true, phase: "preview" }), "查看预览");
});

// P0 回归：主按钮曾写「查看并确认」却只滚动页面，导出高清只能去折叠卡片里找小按钮。
test("the outer action finishes the current result instead of only scrolling", () => {
  const base = { busy: false, recognizing: false, transcriptReady: true, phase: "preview", credits: 20 };
  assert.equal(workspaceActionLabel({ ...base, result: "awaiting_review" }), "确认效果，获取高清");
  assert.equal(workspaceActionLabel({ ...base, result: "completed" }), "查看高清成片");
  assert.equal(workspaceActionLabel({ ...base, busy: true, result: "awaiting_review" }), "正在提交…");
  assert.equal(workspaceActionLabel({ ...base, phase: "waiting", waitingLabel: "正在编排画面" }), "正在编排画面");
  assert.equal(workspaceActionLabel({ ...base, phase: "recover" }), "继续生成");
});
