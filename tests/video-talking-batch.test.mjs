import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/talking-batch.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const t = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const script = (key, text, extra = {}) => ({ key, source: "library", documentId: `doc-${key}`, title: `标题${key}`, body: `正文${key} #好物`, script: text, ...extra });
const catalog = { avatarIds: new Set(["a1", "a2", "p-avatar"]), voiceIds: new Set(["v1", "v2", "p-voice"]) };
const persona = { id: "p1", name: "店长小林", avatar_id: "p-avatar", voice_id: "p-voice" };
const threeScripts = () => t.addScripts(t.emptyDraft(), [script("1", "第一条口播稿。"), script("2", "第二条。"), script("3", "第三条口播。")]);

test("same presenter mode: one setting applies to all three scripts in the request body", () => {
  let draft = threeScripts();
  draft = t.assign(draft, "1", current => t.withAvatar(current, "a1"));
  draft = t.assign(draft, "1", current => t.withVoice(current, "v1"));
  const items = t.batchItems(draft);
  assert.equal(items.length, 3);
  for (const item of items) {
    assert.equal(item.avatar_id, "a1");
    assert.equal(item.voice_id, "v1");
    assert.equal(item.drive_mode, "text");
  }
  assert.deepEqual(items.map(i => i.script_document_id), ["doc-1", "doc-2", "doc-3"]);
  assert.deepEqual(items.map(i => i.script_text), ["第一条口播稿。", "第二条。", "第三条口播。"]);
  assert.deepEqual(t.problems(draft, catalog), []);
});

test("each mode: different presenters and voices per script; switching keeps the shared choice as a start", () => {
  let draft = threeScripts();
  draft = t.assign(draft, "all", () => ({ avatarId: "a1", voiceId: "v1" }));
  draft = t.switchMode(draft, "each");
  draft = t.assign(draft, "2", () => t.withPersona(persona));
  draft = t.assign(draft, "3", current => t.withVoice(t.withAvatar(current, "a2"), "v2"));
  const items = t.batchItems(draft);
  assert.deepEqual(items.map(i => [i.avatar_id, i.voice_id, i.persona_id]), [["a1", "v1", null], ["p-avatar", "p-voice", "p1"], ["a2", "v2", null]]);
  assert.equal(t.voiceFromPersona(t.assignmentFor(draft, "2"), [persona]), true);
  // Changing the voice of a persona row keeps the persona's presenter but no longer says "brought in".
  draft = t.assign(draft, "2", current => t.withVoice(current, "v2"));
  assert.equal(t.voiceFromPersona(t.assignmentFor(draft, "2"), [persona]), false);
  assert.equal(t.batchItems(draft)[1].avatar_id, "p-avatar");
  // Picking a plain avatar drops the persona.
  draft = t.assign(draft, "2", current => t.withAvatar(current, "a1"));
  assert.equal(t.batchItems(draft)[1].persona_id, null);
});

test("problems name the step and how many rows are missing", () => {
  let draft = t.switchMode(threeScripts(), "each");
  draft = t.assign(draft, "1", () => ({ avatarId: "a1", voiceId: "v1" }));
  assert.deepEqual(t.problems(draft, catalog), [{ step: 2, text: "还有 2 条没选数字人" }, { step: 3, text: "还有 2 条没选音色" }]);
  assert.deepEqual(t.problems(t.emptyDraft(), catalog), [{ step: 1, text: "请至少选择或输入一条口播稿" }]);
  const unknownAvatar = t.assign(threeScripts(), "1", () => ({ avatarId: "gone", voiceId: "v1" }));
  assert.equal(t.problems(unknownAvatar, catalog)[0].text, "请选择数字人");
});

test("audio drive: one item per audio, no voice needed, text scripts dropped on switch", () => {
  let draft = threeScripts();
  draft = t.switchDrive(draft, "audio");
  assert.equal(draft.scripts.length, 0);
  draft = t.addScripts(draft, [{ key: "a", source: "audio", title: "", body: "", script: "", audioId: "11111111-1111-4111-8111-111111111111", audioName: "录音1.mp3", audioSeconds: 31.6 }]);
  draft = t.assign(draft, "a", () => ({ avatarId: "a1" }));
  const [item] = t.batchItems(draft);
  assert.equal(item.drive_mode, "audio");
  assert.equal(item.voice_id, null);
  assert.equal(item.audio_file_id, "11111111-1111-4111-8111-111111111111");
  assert.deepEqual(t.problems(draft, catalog), []);
  assert.equal(t.scriptSeconds(draft.scripts[0]), 32);
  assert.equal(t.displayTitle(draft.scripts[0]), "录音1.mp3");
});

test("summary: count, credits, four in parallel per round", () => {
  const five = t.addScripts(t.emptyDraft(), [1, 2, 3, 4, 5].map(i => script(String(i), "四点八个字每秒的估算。")));
  const value = t.summary(five, 50);
  assert.equal(value.count, 5);
  assert.equal(value.credits, 250);
  assert.deepEqual(value.minutes, [6, 12]);
  assert.equal(value.queued, 1);
  assert.equal(t.summary(five, null).credits, null);
});

test("adding the same library script twice keeps one; any change makes a new submission id", () => {
  let draft = threeScripts();
  draft = { ...draft, requestId: "r1" };
  draft = t.addScripts(draft, [script("1", "第一条口播稿。")]);
  assert.equal(draft.scripts.length, 3);
  assert.equal(draft.requestId, undefined);
  draft = t.removeScript({ ...draft, requestId: "r2" }, "2");
  assert.deepEqual(draft.scripts.map(s => s.key), ["1", "3"]);
  assert.equal(draft.requestId, undefined);
});

test("session draft round-trips and rejects foreign data", () => {
  let draft = t.switchMode(threeScripts(), "each");
  draft = t.assign(draft, "2", () => t.withPersona(persona));
  draft = { ...draft, step: 3, requestId: "req-1" };
  assert.deepEqual(t.decodeDraft(t.encodeDraft(draft)), draft);
  assert.equal(t.decodeDraft("{"), undefined);
  assert.equal(t.decodeDraft(JSON.stringify({ version: 2 })), undefined);
  assert.equal(t.decodeDraft(null), undefined);
});

test("result boxes: queue positions, stage labels and retry", () => {
  const items = [
    { id: "i1", position: 0, status: "succeeded", error: null, publish_title: "冰丝凉席", script_text: "x", avatar_id: "a1", voice_id: "v1", persona_id: null, generation_task_id: "g1", drive_mode: "text", stage: "talking" },
    { id: "i2", position: 1, status: "running", error: null, publish_title: "", script_text: "第二条稿。后面", avatar_id: "a1", voice_id: "v1", persona_id: null, generation_task_id: "g2", drive_mode: "text", stage: "talking" },
    { id: "i3", position: 2, status: "failed", error: "这条没有生成成功", publish_title: "三", script_text: "x", avatar_id: "a1", voice_id: "v1", persona_id: null, generation_task_id: "g3", drive_mode: "text", stage: "talking" },
    { id: "i4", position: 3, status: "queued", error: null, publish_title: "四", script_text: "x", avatar_id: "a1", voice_id: "v1", persona_id: null, generation_task_id: null, drive_mode: "text", stage: "talking" },
  ];
  const view = { batch: { id: "b1", created_at: "", item_ids: items.map(i => i.id), items, status_counts: {} }, parallel_limit: 4, talking: [
    { item_id: "i1", queue_position: null, stage: "completed", video_url: "/v/g1", can_retry: false },
    { item_id: "i2", queue_position: null, stage: "lipsync_generating", video_url: null, can_retry: false },
    { item_id: "i3", queue_position: null, stage: "lipsync_submitting", video_url: null, can_retry: true },
    { item_id: "i4", queue_position: 1, stage: null, video_url: null, can_retry: false },
  ] };
  const boxes = t.resultBoxes(view, stage => ({ lipsync_generating: "正在生成口播视频" })[stage] || "正在处理");
  assert.deepEqual(boxes.map(b => [b.state, b.label]), [["done", "已完成"], ["running", "正在生成口播视频"], ["failed", "生成失败"], ["queued", "排队中 · 第 1 位"]]);
  assert.equal(boxes[1].title, "第二条稿");
  assert.equal(boxes[0].videoUrl, "/v/g1");
  assert.equal(boxes[2].canRetry, true);
  assert.equal(t.batchSettled(view), false);
});

test("editing CTA: partial batches edit the finished ones first and say the rest can join later", () => {
  assert.deepEqual(t.editingCta([{ state: "done" }, { state: "running" }, { state: "queued" }], false), { label: "先剪已完成的 1 条", note: "其余 2 条完成后可继续加入", disabled: false });
  assert.deepEqual(t.editingCta([{ state: "done" }, { state: "failed" }, { state: "done" }], true), { label: "去剪辑这 2 条", note: "", disabled: false });
  assert.equal(t.editingCta([{ state: "running" }, { state: "queued" }], false).disabled, true);
  assert.equal(t.editingCta([{ state: "done" }, { state: "checking" }], false).label, "先剪已完成的 1 条");
});

test("counts match the script library: API numbers for library scripts, scriptStats for typed ones", () => {
  const fromLibrary = { key: "doc:x", source: "library", documentId: "x", title: "", body: "", script: "短稿 #标签", chars: 418, seconds: 87 };
  assert.equal(t.scriptChars(fromLibrary), 418);
  assert.equal(t.scriptSeconds(fromLibrary), 87);
  const typed = { key: "m", source: "manual", title: "", body: "", script: "家人们，夏天睡觉最怕什么？" };
  assert.equal(t.scriptChars(typed) > 0, true);
  assert.equal(t.summary(t.addScripts(t.emptyDraft(), [fromLibrary]), 50).seconds, 87);
});

test("slow provider and unknown outcome both offer 查询结果 with a no-double-charge note", () => {
  const item = (id, status) => ({ id, position: 0, status, error: null, publish_title: "稿", script_text: "x", avatar_id: "a", voice_id: "v", persona_id: null, generation_task_id: "g", drive_mode: "text", stage: "talking", version: 3 });
  const view = { batch: { id: "b", created_at: "", item_ids: ["i1", "i2"], items: [item("i1", "running"), item("i2", "running")], status_counts: {} }, parallel_limit: 4, talking: [
    { item_id: "i1", queue_position: null, stage: "lipsync_generating", video_url: null, can_retry: false, long_wait: true },
    { item_id: "i2", queue_position: null, stage: "lipsync_submitting", video_url: null, can_retry: false, awaiting_check: true },
  ] };
  const [slow, unknown] = t.resultBoxes(view, () => "正在处理");
  assert.deepEqual([slow.state, slow.label, slow.note, slow.canCheck], ["checking", "供应商排队较久", "系统会自动继续查询，不会重复扣费", true]);
  assert.deepEqual([unknown.state, unknown.label, unknown.canCheck], ["checking", "结果待确认", true]);
});

// ---- A4：带新文案进来时不被上一批盖住 ----

const submittedDraft = () => ({ ...t.assign(threeScripts(), "1", () => t.withPersona(persona)), submittedBatchId: "batch-old" });
const fromLibrary = keys => keys.map(key => script(`n${key}`, `新选的第 ${key} 条。`));

test("A4: ?scripts= with a batch still generating opens the new batch's setup, not the old batch", () => {
  const plan = t.planEntry({ stored: submittedDraft(), hasScripts: true, batchParam: null, latestOpen: "batch-old" });
  assert.equal(plan.show, null, "the old batch must not cover the page");
  assert.equal(plan.previous, "batch-old", "the old batch is offered in the top line");
  const draft = t.addScripts(plan.draft, fromLibrary(["1", "2", "3"]));
  assert.deepEqual(draft.scripts.map(s => s.documentId), ["doc-n1", "doc-n2", "doc-n3"], "only the three new scripts, old submitted ones are not mixed in");
  assert.equal(draft.step, 1);
  assert.equal(draft.submittedBatchId, undefined);
  // The presenter chosen for the previous batch is kept as a starting point.
  assert.equal(draft.shared.personaId, "p1");
});

test("A4: an unsubmitted draft is kept and new scripts are added to it", () => {
  const stored = t.addScripts(t.emptyDraft(), [script("x", "还没生成的稿。")]);
  const plan = t.planEntry({ stored, hasScripts: true, latestOpen: "batch-old" });
  const draft = t.addScripts(plan.draft, fromLibrary(["1"]));
  assert.deepEqual(draft.scripts.map(s => s.documentId), ["doc-x", "doc-n1"]);
  assert.equal(plan.previous, "batch-old");
});

test("A4: without ?scripts= the open batch is still found again (other browser / refresh)", () => {
  const plan = t.planEntry({ stored: submittedDraft(), hasScripts: false, latestOpen: "batch-old" });
  assert.equal(plan.show, "batch-old");
  assert.equal(plan.previous, null);
  assert.equal(plan.draft.scripts.length, 3, "the shown batch's draft stays until 再做一批");
  const nothing = t.planEntry({ stored: submittedDraft(), hasScripts: false, latestOpen: null });
  assert.equal(nothing.show, null);
  assert.equal(nothing.draft.scripts.length, 0, "a submitted draft is not offered again as a new batch");
});

test("A4: 查看 the old batch (?batch=&scripts=) then 再做一批 keeps the newly chosen scripts", () => {
  const fresh = t.addScripts(t.freshDraft(), fromLibrary(["1", "2", "3"]));
  const plan = t.planEntry({ stored: fresh, hasScripts: true, batchParam: "batch-old", latestOpen: null });
  assert.equal(plan.show, "batch-old");
  const again = t.draftAfterBatch(t.addScripts(plan.draft, fromLibrary(["1", "2", "3"])));
  assert.deepEqual(again.scripts.map(s => s.documentId), ["doc-n1", "doc-n2", "doc-n3"]);
  // After generating, 再做一批 starts over.
  const done = t.draftAfterBatch({ ...again, submittedBatchId: "batch-new" });
  assert.equal(done.scripts.length, 0);
});

test("A4: submittedBatchId survives the session draft round trip and editing clears it", () => {
  const decoded = t.decodeDraft(t.encodeDraft(submittedDraft()));
  assert.equal(decoded.submittedBatchId, "batch-old");
  assert.equal(t.removeScript(decoded, "1").submittedBatchId, undefined);
});

test("A4: the top line reports x/y of the previous batch", () => {
  const view = { batch: { id: "b", created_at: "", item_ids: [], status_counts: {}, items: [
    { id: "1", position: 0, status: "succeeded", error: null, publish_title: "", script_text: "a", avatar_id: null, voice_id: null, persona_id: null, generation_task_id: "g1", drive_mode: "text", stage: "talking", version: 2 },
    { id: "2", position: 1, status: "running", error: null, publish_title: "", script_text: "b", avatar_id: null, voice_id: null, persona_id: null, generation_task_id: "g2", drive_mode: "text", stage: "talking", version: 2 },
    { id: "3", position: 2, status: "queued", error: null, publish_title: "", script_text: "c", avatar_id: null, voice_id: null, persona_id: null, generation_task_id: null, drive_mode: "text", stage: "talking", version: 1 },
  ] }, talking: [], parallel_limit: 4 };
  assert.equal(t.previousBatchLine(view), "上一批还在生成（已完成 1/3）");
});

// ---- C10：固定形象轮流分配 ----

const personas = [
  { id: "pa", name: "店长小林", avatar_id: "a1", voice_id: "v1" },
  { id: "pb", name: "阿杰", avatar_id: "a2", voice_id: "v2" },
  { id: "pc", name: "小美", avatar_id: "p-avatar", voice_id: "p-voice" },
];
const twelve = () => t.addScripts(t.emptyDraft(), Array.from({ length: 12 }, (_, i) => script(String(i + 1), `第 ${i + 1} 条口播。`)));

test("C10: 12 scripts across 3 fixed personas are split 4/4/4 in turn, with each persona's voice", () => {
  const draft = t.rotate(twelve(), personas);
  assert.equal(draft.mode, "each");
  assert.deepEqual(t.rotationCounts(draft).map(row => [row.personaId, row.count]), [["pa", 4], ["pb", 4], ["pc", 4]]);
  const items = t.batchItems(draft);
  assert.deepEqual(items.slice(0, 4).map(i => i.persona_id), ["pa", "pb", "pc", "pa"]);
  assert.deepEqual(items.slice(0, 3).map(i => [i.avatar_id, i.voice_id]), [["a1", "v1"], ["a2", "v2"], ["p-avatar", "p-voice"]]);
  assert.deepEqual(t.problems(draft, catalog), []);
});

test("C10: rotation follows added/removed scripts and ends when one row is changed by hand", () => {
  let draft = t.rotate(twelve(), personas);
  draft = t.addScripts(draft, [script("13", "第十三条。")]);
  assert.deepEqual(t.rotationCounts(draft).map(row => row.count), [5, 4, 4]);
  draft = t.removeScript(draft, "13");
  assert.deepEqual(t.rotationCounts(draft).map(row => row.count), [4, 4, 4]);
  const decoded = t.decodeDraft(t.encodeDraft(draft));
  assert.deepEqual(decoded.rotation.map(row => row.personaId), ["pa", "pb", "pc"]);
  const manual = t.assign(draft, "2", current => t.withAvatar(current, "a1"));
  assert.equal(manual.rotation, undefined);
  assert.equal(manual.perScript["3"].personaId, "pc", "other rows keep their assignment");
  assert.equal(t.switchMode(draft, "each").rotation, undefined, "pressing 每条单独选 leaves rotation mode");
  assert.equal(t.switchMode(draft, "same").rotation, undefined);
});

// ---- B15 / B8 ----

test("B15: clone button follows voice-clone-config.available", () => {
  assert.deepEqual(t.cloneAction({ available: false }), { available: false, label: "克隆新声音（暂未开通）", hint: "声音克隆暂未开通，可以先用系统声音" });
  assert.equal(t.cloneAction(undefined).available, false, "unknown config is treated as closed: no request is sent");
  assert.deepEqual(t.cloneAction({ available: true }), { available: true, label: "克隆新声音", hint: "" });
});

test("B8: result notes do not mention charges when prices are not configured", () => {
  const view = { batch: { id: "b", created_at: "", item_ids: [], status_counts: {}, items: [
    { id: "1", position: 0, status: "running", error: null, publish_title: "t", script_text: "a", avatar_id: null, voice_id: null, persona_id: null, generation_task_id: "g1", drive_mode: "text", stage: "talking", version: 2 },
  ] }, talking: [{ item_id: "1", queue_position: null, stage: null, video_url: null, can_retry: false, awaiting_check: true }], parallel_limit: 4 };
  assert.equal(t.resultBoxes(view, s => s, false)[0].note, "不会重新生成");
  assert.equal(t.resultBoxes(view, s => s)[0].note, "不会重新生成，也不会重复扣积分");
});
