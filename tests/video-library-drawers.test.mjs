// W6 形象与声音库：固定形象规则、声音克隆开关、三个抽屉的渲染（C4）。
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const css = new Proxy({}, { get: (_, key) => (typeof key === "string" ? key : undefined) });
function load(file, resolver) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function("require", "module", "exports", outputText)(resolver, mod, mod.exports);
  return mod.exports;
}
const rules = load("../features/video-studio/persona-rules.ts", require);
const creditCalls = [];
const stubs = {
  "@/features/video-studio/persona-rules": rules,
  "@/features/video-studio/credits": {
    useVideoCredits: () => ({ note: actions => { creditCalls.push(actions); return { text: "预计 30 积分", credits: 30, insufficient: false }; } }),
    billableLabel: (action, credits) => (typeof credits === "number" ? `${action} · ${credits} 积分` : `${action}（计费）`),
  },
  "@/lib/api/base-url": { mediaUrl: url => url },
  "@/lib/api/api-error": { ApiError: class ApiError extends Error {} },
  "./voice-progress": { VoiceProgress: ({ status }) => createElement("span", null, `进度:${status}`) },
};
const apiStubs = {
  "@/lib/api/client": { apiClient: { GET: async () => ({ data: [] }), POST: async () => { throw new Error("不应调用"); } } },
  "@/lib/api/request": { unwrapApiResponse: result => result.data },
};
const polishModule = load("../features/video-studio/avatar-polish.ts", name => apiStubs[name] || stubs[name] || require(name));
stubs["@/features/video-studio/avatar-polish"] = polishModule;
function resolver(name) {
  if (name in stubs) return stubs[name];
  if (name.endsWith(".css")) return css;
  if (name === "./side-drawer") return sideDrawer;
  if (name === "./persona-create-drawer") return personaDrawer;
  return require(name);
}
const sideDrawer = load("../components/video-studio/side-drawer.tsx", resolver);
const personaDrawer = load("../components/video-studio/persona-create-drawer.tsx", resolver);
const { VoiceCloneDrawer } = load("../components/video-studio/voice-clone-drawer.tsx", resolver);
const { AvatarCreateDrawer } = load("../components/video-studio/avatar-create-drawer.tsx", resolver);
const { PersonaShelf } = load("../components/video-studio/persona-shelf.tsx", resolver);
const { PersonaCreateDrawer } = personaDrawer;

const persona = (id, extra = {}) => ({ id, name: `形象${id}`, avatar_id: `a${id}`, voice_id: `v${id}`, avatar_name: "Angel-休闲-sit_body", voice_name: "温柔女声", cover_url: `/c/${id}`, avatar_preview_url: null, voice_preview_url: `/p/${id}`, emotion: null, language: null, available: true, unavailable_reason: null, created_at: `2026-11-28T0${id}:00:00Z`, updated_at: "2026-11-28T00:00:00Z", ...extra });

test("选固定形象会同时带出形象和声音（声音参数有才覆盖）", () => {
  assert.deepEqual(rules.personaDraftPatch(persona("1")), { personaId: "1", avatarId: "a1", voiceId: "v1" });
  assert.deepEqual(rules.personaDraftPatch(persona("2", { emotion: "愉快", language: "auto" })), { personaId: "2", avatarId: "a2", voiceId: "v2", emotion: "愉快", language: "auto" });
});

test("固定形象排序：可用在前，新的在前", () => {
  const sorted = rules.sortPersonas([persona("1"), persona("3", { available: false }), persona("2")]);
  assert.deepEqual(sorted.map(item => item.id), ["2", "1", "3"]);
});

test("固定形象名称：必填、限长、本地重名提示", () => {
  assert.equal(rules.personaNameError("  "), "请给固定形象起个名字");
  assert.match(rules.personaNameError("字".repeat(31)), /最多 30/);
  assert.match(rules.personaNameError(" 店长 ", ["店长"]), /同名/);
  assert.equal(rules.personaNameError("店长", ["主播"]), "");
});

test("定制形象阶段：生成中 / 待确认 / 登记中 / 完成 / 失败", () => {
  assert.equal(rules.avatarPhase(undefined, true), "uploading");
  assert.equal(rules.avatarPhase({ status: "queued", stage: "queued" }), "generating");
  assert.equal(rules.avatarPhase({ status: "awaiting_review" }), "review");
  assert.equal(rules.avatarPhase({ status: "running", stage: "model_submitting" }), "registering");
  assert.equal(rules.avatarPhase({ status: "completed" }), "ready");
  assert.equal(rules.avatarPhase({ status: "failed" }), "failed");
  assert.equal(rules.ownAvatarStatus({ ready: false }, { status: "running" }).label, "定制中");
  assert.equal(rules.ownAvatarStatus({ ready: false }, { status: "failed" }).label, "未成功");
  assert.equal(rules.ownAvatarStatus({ ready: true }).label, "可使用");
  for (const copy of Object.values(rules.AVATAR_PHASE_COPY)) assert.doesNotMatch(copy.title + copy.detail, /h3|template|job|bundle/i);
});

test("声音克隆开关：配置关闭 = 入口可见但显示暂未开通", () => {
  assert.equal(rules.voiceCloneGate(undefined, false).open, false);
  assert.deepEqual(rules.voiceCloneGate({ available: false }, true).title, "声音克隆暂未开通");
  assert.equal(rules.voiceCloneGate(undefined, true).title, "声音克隆暂未开通");
  assert.equal(rules.voiceCloneGate({ available: true }, true).open, true);
});

function clonesStub(config) {
  const calls = { create: 0 };
  return { calls, clones: { voices: [], config, error: "", reload: async () => {}, refresh: async () => {}, preview: async () => {}, create: async () => { calls.create += 1; throw new Error("不应调用"); } } };
}

test("声音克隆关闭：抽屉只显示暂未开通，没有上传框和付费按钮，不调用创建", () => {
  const { calls, clones } = clonesStub({ available: false, min_seconds: 5, max_seconds: 60, consent_version: "v", max_bytes: 1, preview_text: "" });
  const html = renderToStaticMarkup(createElement(VoiceCloneDrawer, { open: true, onClose() {}, workspaceId: "ws", clones, onUseSystemVoices() {} }));
  assert.match(html, /声音克隆暂未开通/);
  assert.match(html, /去选系统声音/);
  assert.doesNotMatch(html, /type="file"/);
  assert.doesNotMatch(html, /创建声音/);
  assert.equal(calls.create, 0);
});

test("声音克隆打开配置后：抽屉给出录音上传、授权和计费按钮", () => {
  const { clones } = clonesStub({ available: true, min_seconds: 5, max_seconds: 60, consent_version: "v", max_bytes: 1, preview_text: "" });
  const html = renderToStaticMarkup(createElement(VoiceCloneDrawer, { open: true, onClose() {}, workspaceId: "ws", clones }));
  assert.match(html, /type="file"/);
  assert.match(html, /我授权平台处理录音/);
  assert.match(html, /创建声音 · 30 积分/);
  assert.doesNotMatch(html, /暂未开通/);
});

test("抽屉关闭时不渲染任何内容（由外层 open 控制）", () => {
  const { clones } = clonesStub({ available: true });
  assert.equal(renderToStaticMarkup(createElement(VoiceCloneDrawer, { open: false, onClose() {}, workspaceId: "ws", clones })), "");
});

const library = {
  avatars: [
    { id: "own-avatar-1", name: "店长小林", gender: "女", tag: "我的形象", source: "self_owned", cover_url: "/own", ready: false },
    { id: "qy-model-62", name: "Angel-休闲-sit_body", gender: "女", tag: "公共数字人", source: "quanyu_public", cover_url: "/pub", ready: true },
  ],
  voices: [
    { id: "qy-voice-1", name: "温柔女声", gender: "女", tag: "公共音色", description: "系统声音", available: true, preview_url: null },
    { id: "tao-1", name: "知性女声", gender: "女", tag: "中文", description: "系统声音", available: true, preview_url: "/p" },
    { id: "off", name: "停用声音", gender: "男", tag: "", description: "", available: false },
  ],
  jobs: [],
};

test("新建固定形象抽屉：形象分「我的 / 公共」，声音只列可用的，定制中形象有标记", () => {
  const html = renderToStaticMarkup(createElement(PersonaCreateDrawer, { open: true, onClose() {}, library, personas: { personas: [], create: async () => ({}) } }));
  assert.match(html, /新建固定形象/);
  assert.match(html, /我的形象 1/);
  assert.match(html, /店长小林/);
  assert.match(html, /定制中/);
  assert.match(html, /温柔女声/);
  assert.match(html, /试听知性女声/);
  assert.match(html, /<span>暂无试听<\/span>/);
  assert.doesNotMatch(html, /<button[^>]*>[^<]*暂无试听/);
  assert.doesNotMatch(html, /停用声音/);
  assert.match(html, /保存固定形象/);
});

test("定制形象抽屉：照片 / 视频、授权勾选、按积分标价", () => {
  creditCalls.length = 0;
  const html = renderToStaticMarkup(createElement(AvatarCreateDrawer, { open: true, onClose() {}, workspaceId: "ws", userId: "u", library: { ...library, createAvatar: async () => { throw new Error("不应调用"); } } }));
  assert.match(html, /定制我的形象/);
  assert.match(html, /上传照片/);
  assert.match(html, /上传视频/);
  assert.match(html, /本人或已获授权/);
  assert.match(html, /生成形象动作 · 30 积分/);
  assert.ok(creditCalls.some(actions => actions.includes("avatar_motion") && actions.includes("avatar_register")));
});

test("我的固定形象分区：封面 + 名字 + 声音名 + 试听；不可用的给原因", () => {
  const personas = { personas: [persona("1"), persona("2", { available: false, unavailable_reason: "声音已删除或不可用，请更换声音", cover_url: null, voice_preview_url: null })], error: "", update: async () => {}, remove: async () => {} };
  const html = renderToStaticMarkup(createElement(PersonaShelf, { personas, onCreate() {}, onUse() {} }));
  assert.match(html, /我的固定形象/);
  assert.match(html, /src="\/c\/1"/);
  assert.match(html, /形象1/);
  assert.match(html, /Angel · 休闲 · 温柔女声/);
  assert.match(html, /试听温柔女声/);
  assert.match(html, /声音已删除或不可用/);
  assert.match(html, /更多操作/);
  assert.doesNotMatch(html, />改名</); // 改名 / 删除收进「…」菜单
  assert.match(html, /新建固定形象/);
});

test("AI 润色描述：换脸 / 名人 / 不适宜内容在前端就拦下，正常描述放行", () => {
  const { polishDescriptionError, POLISH_PRESETS } = polishModule;
  for (const bad of ["把我换成刘德华的脸", "换脸成明星", "变成当红偶像", "长得像某演员", "穿比基尼", "face swap"]) assert.notEqual(polishDescriptionError(bad), "", bad);
  for (const ok of ["把我变成一个很帅、穿西装、站在门店里的人", "枪灰色西装", "儿童服装店店长，暖光"]) assert.equal(polishDescriptionError(ok), "", ok);
  assert.equal(POLISH_PRESETS.length, 4);
  for (const preset of POLISH_PRESETS) assert.equal(polishDescriptionError(preset.description), "");
  assert.match(polishDescriptionError(""), /示例/);
  assert.match(polishDescriptionError("字".repeat(121)), /120/);
});

test("定制形象抽屉：照片模式有「AI 润色（可选）」开关，视频模式没有", () => {
  const html = renderToStaticMarkup(createElement(AvatarCreateDrawer, { open: true, onClose() {}, workspaceId: "ws", userId: "u", library: { ...library, createAvatar: async () => { throw new Error("不应调用"); } } }));
  assert.match(html, /AI 润色（可选）/);
  assert.match(html, /role="switch"/);
  assert.match(html, /保持你本人的五官/);
});
