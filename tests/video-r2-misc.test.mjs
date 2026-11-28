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

test("B8：文案、补充素材、形象三处价格为空统一「灰度测试期间不扣积分」，有价才说失败不扣", async () => {
  const { build } = await import("esbuild");
  const compiled = await build({ entryPoints: ["features/video-studio/supplement-materials.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
  const m = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
  assert.equal(m.aiCost(3, null), "3 张，灰度测试期间不扣积分");
  assert.equal(m.aiCost(3, 7), "3 张 × 7 积分 = 21 积分");
  const files = ["components/video-studio/auto-writing.tsx", "components/video-studio/avatar-cloning.tsx", "components/video-studio/avatar-create-drawer.tsx", "components/video-studio/generation-confirmation.tsx", "components/video-studio/generation-preview.tsx", "components/video-studio/supplement-materials-panel.tsx", "features/video-studio/supplement-materials.ts"];
  for (const file of files) assert.doesNotMatch(readFileSync(file, "utf8"), /按实际(用量|服务|张数)计费|（计费）|按实际服务计费/, file);
  const panel = readFileSync("components/video-studio/supplement-materials-panel.tsx", "utf8");
  assert.match(panel, /whenPriced\(credits, "，按实际生成成功的张数扣，失败不扣"\)/);
  assert.match(panel, /creditPhrase\(credits, \{ per: "张", failureFree: true \}\)/);
  const confirm = readFileSync("components/video-studio/generation-confirmation.tsx", "utf8");
  assert.match(confirm, /whenPriced\(cost\?\.credits, "，可能产生登记费用"\)/);
});

test("文案页旧版本：只有口播稿时显示「生成于旧版本」+ 补写按钮，新版本不受影响", () => {
  const format = load("../features/video-studio/script-library-format.ts", require);
  const cssProxy = new Proxy({}, { get: (_, key) => (typeof key === "string" ? key : undefined) });
  const partsModule = load("../components/video-studio/script-library-parts.tsx", name => name === "@/features/video-studio/script-library-format" ? format : name.endsWith(".css") ? cssProxy : require(name));
  const old = { publish_title: "", publish_body: "", script: "今天给大家推荐一款冰丝凉席。", platform: "douyin" };
  assert.equal(format.needsFill(old), true);
  const legacy = renderToStaticMarkup(createElement(partsModule.ScriptParts, { parts: old, onCopy: () => {}, legacy: createElement("button", null, "补写标题和正文") }));
  assert.match(legacy, /这一版生成于旧版本，没有标题和正文/);
  assert.match(legacy, /补写标题和正文/);
  assert.doesNotMatch(legacy, /还没有标题|还没有发布正文/);
  assert.match(legacy, /今天给大家推荐一款冰丝凉席/);
  const fresh = { ...old, publish_title: "夏天必备冰丝凉席", publish_body: "睡得凉快 #好物" };
  assert.equal(format.needsFill(fresh), false);
  const normal = renderToStaticMarkup(createElement(partsModule.ScriptParts, { parts: fresh, onCopy: () => {} }));
  assert.match(normal, /夏天必备冰丝凉席/);
  assert.doesNotMatch(normal, /旧版本/);
  const writing = readFileSync(new URL("../components/video-studio/auto-writing.tsx", import.meta.url), "utf8");
  assert.match(writing, /library\.fill\(row\.id, platform \|\| "douyin", crypto\.randomUUID\(\)\)/);
  assert.match(writing, /legacy=\{legacy \? <>/);
});
