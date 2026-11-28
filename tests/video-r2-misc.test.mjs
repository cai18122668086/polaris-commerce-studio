// 第二轮 L6：形象「结果待确认」只查询不重提（B7 前端）、声音行用途说明。
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
function load(file, resolver) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function("require", "module", "exports", outputText)(resolver, mod, mod.exports);
  return mod.exports;
}
const rules = load("../features/video-studio/persona-rules.ts", require);
const checkButton = load("../components/video-studio/avatar-check-button.tsx", require);

test("结果待确认：单独的阶段与标签，只给「查询结果」", () => {
  assert.equal(rules.avatarPhase({ status: "unknown" }), "pending_check");
  assert.equal(rules.ownAvatarStatus({ ready: false }, { status: "unknown" }).label, "结果待确认");
  assert.equal(rules.AVATAR_PHASE_COPY.pending_check.title, "结果待确认");
  assert.match(rules.AVATAR_PHASE_COPY.pending_check.detail, /不会重新生成.*不会重复扣积分/);
  assert.equal(rules.canCheckAvatarJob({ status: "unknown" }), true);
  for (const status of ["failed", "queued", "running", "completed", "awaiting_review"]) assert.equal(rules.canCheckAvatarJob({ status }), false);
  assert.equal(rules.canCheckAvatarJob(undefined), false);
});

test("查询结果按钮：查询中禁用", () => {
  const idle = renderToStaticMarkup(createElement(checkButton.AvatarCheckButton, { jobId: "j", check: async () => null, checking: false }));
  assert.match(idle, />查询结果</);
  const busy = renderToStaticMarkup(createElement(checkButton.AvatarCheckButton, { jobId: "j", check: async () => null, checking: true }));
  assert.match(busy, /disabled=""[^>]*>正在查询…/);
});

test("查询结果走 /check，绝不对待确认任务调 /resume", () => {
  const library = readFileSync(new URL("../features/video-studio/library.ts", import.meta.url), "utf8");
  const check = library.slice(library.indexOf("const checkResult"), library.indexOf("return { avatars"));
  assert.match(check, /generation-tasks\/\{job_id\}\/check/);
  assert.doesNotMatch(check, /\/resume`, \{/);
  const studio = readFileSync(new URL("../components/video-studio/video-studio.tsx", import.meta.url), "utf8");
  assert.match(studio, /canCheckAvatarJob\(job\)\) : undefined; return pending \? <AvatarCheckButton/);
  const drawer = readFileSync(new URL("../components/video-studio/avatar-create-drawer.tsx", import.meta.url), "utf8");
  assert.match(drawer, /phase === "pending_check" && job && <div className=\{styles.checkRow\}><AvatarCheckButton jobId=\{job.id\} check=\{library.checkResult\}/);
});

test("声音行显示接口返回的用途说明（系统兜底文字不显示）", () => {
  const picker = readFileSync(new URL("../components/video-studio/voice-picker.tsx", import.meta.url), "utf8");
  assert.match(picker, /voice\.description && voice\.description !== "系统声音" && <em className=\{styles\.voiceUsage\}>/);
});
