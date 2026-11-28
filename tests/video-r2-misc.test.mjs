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
  assert.match(studio, /canCheckAvatarJob\(job\)\) : undefined;[^]*?return pending \? <AvatarCheckButton/);
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
  assert.match(writing, /library\.fill\(row\.id, platformOf\(d\) \|\| "douyin", crypto\.randomUUID\(\)\)/);
  assert.match(writing, /legacy=\{legacy \? <>/);
});

test("声音库克隆入口：未开通时置灰、写明暂未开通、点了不打开表单", () => {
  assert.deepEqual(rules.cloneEntry({ available: true }), { available: true, label: "克隆新声音", hint: "" });
  for (const config of [undefined, null, { available: false }]) {
    const entry = rules.cloneEntry(config);
    assert.equal(entry.available, false);
    assert.equal(entry.label, "克隆新声音（暂未开通）");
    assert.match(entry.hint, /可以先用系统声音/);
  }
  const studio = readFileSync(new URL("../components/video-studio/video-studio.tsx", import.meta.url), "utf8");
  assert.match(studio, /const entry = cloneEntry\(clones\.config\);[^]*?onClick=\{\(\) => \{ if \(entry\.available\) setLibraryDrawer\("voice"\); \}\}/);
  const mine = readFileSync(new URL("../components/video-studio/voice-cloning.tsx", import.meta.url), "utf8");
  assert.match(mine, /onClick=\{\(\) => \{ if \(entry\.available\) onClone\(\); \}\}/);
  assert.match(mine, /克隆我的声音（暂未开通）/);
});

test("C8 停止核对：形象任务显示失败说明、已退回积分，给「重新定制」", () => {
  const job = { status: "failed", error_code: "VIDEO_PROVIDER_OUTCOME_EXPIRED" };
  assert.equal(rules.avatarPhase(job), "expired");
  assert.equal(rules.avatarPhase({ status: "failed", error_code: "OTHER" }), "failed");
  assert.equal(rules.ownAvatarStatus({ ready: false }, job).label, "已停止核对");
  assert.equal(rules.AVATAR_PHASE_COPY.expired.detail, "这条长时间没能确认结果，已停止核对，积分已退回。如果供应商那边其实已生成，请联系客服。");
  assert.equal(rules.isOutcomeExpired(job), true);
  assert.equal(rules.isOutcomeExpired({ status: "unknown" }), false);
  const drawer = readFileSync(new URL("../components/video-studio/avatar-create-drawer.tsx", import.meta.url), "utf8");
  assert.match(drawer, /phase === "expired" && <button type="button" className=\{base\.primaryButton\} onClick=\{reset\}>重新定制<\/button>/);
  const studio = readFileSync(new URL("../components/video-studio/video-studio.tsx", import.meta.url), "utf8");
  assert.match(studio, /notify\(AVATAR_PHASE_COPY\.expired\.detail\); setLibraryDrawer\("avatar"\);/);
});

test("声音列表瘦身：按 id 还原试听地址、tag 缺省用语言；列表 30 秒超时并自动重试一次", async () => {
  const lib = load("../features/video-studio/library.ts", name => ({
    react: { useCallback: f => f, useEffect: () => {}, useRef: v => ({ current: v }), useState: v => [v, () => {}] },
    "@/lib/api/client": { apiClient: {} }, "@/lib/api/request": { unwrapApiResponse: r => r.data },
    "@/lib/api/upload": {}, "@/lib/auth/timeout": {},
  })[name] ?? {});
  const [sys, own] = lib.expandVoices([
    { id: "mm-voice-abc", name: "沉稳男声 · 商务讲解", gender: "男", description: "x", language: "中文 (普通话)", available: true, preview: true },
    { id: "cv-voice-1", name: "我的声音", gender: "女", tag: "我的声音", description: "", preview_url: null },
  ], "ws_1");
  assert.equal(sys.preview_url, "/api/v1/video-studio/workspaces/ws_1/voices/mm-voice-abc/preview");
  assert.equal(sys.tag, "中文 (普通话)");
  assert.equal("preview" in sys, false);
  assert.equal(own.preview_url, null);
  assert.equal(own.tag, "我的声音");
  assert.equal(lib.LIST_TIMEOUT_MS, 30000);
  let calls = 0;
  assert.equal(await lib.withRetry(async () => { calls += 1; if (calls === 1) throw new Error("timeout"); return "ok"; }), "ok");
  assert.equal(calls, 2);
});
