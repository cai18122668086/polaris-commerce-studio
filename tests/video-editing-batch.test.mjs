import assert from "node:assert/strict";
import test from "node:test";
import { batchFinished, batchPlan, candidateKey, durationLabel, generationSummary, itemStatus, shortCaptionHint, templateNeeds } from "../features/video-studio/editing-batch.ts";

const talking = (id, extra = {}) => ({ key: candidateKey("talking", id), kind: "talking", refId: `gen-${id}`, itemId: id, batchId: "b1", projectId: "p", title: `稿${id}`, videoUrl: null, ready: true, ...extra });
const library = (id, extra = {}) => ({ key: candidateKey("library", id), kind: "library", refId: id, projectId: "p", title: `库${id}`, videoUrl: null, ready: true, ...extra });

test("a talking batch is edited as it is; anything else becomes a direct-editing batch", () => {
  assert.deepEqual(batchPlan([talking("i1"), talking("i2")]), { kind: "existing", batchId: "b1", itemIds: ["i1", "i2"] });
  // Unfinished talking items are never sent.
  assert.deepEqual(batchPlan([talking("i1"), talking("i2", { ready: false })]), { kind: "existing", batchId: "b1", itemIds: ["i1"] });
  const direct = batchPlan([library("s1"), { ...library("u1"), kind: "upload", key: "upload:u1" }]);
  assert.equal(direct.kind, "create");
  assert.deepEqual(direct.items.map(item => item.source_video_ref), [{ kind: "library", id: "s1" }, { kind: "upload", id: "u1" }]);
  assert.ok(direct.items.every(item => item.drive_mode === "uploaded_video"));
  // A talking result keeps its own work item (title, body, script): never mixed into a copy batch.
  assert.equal(batchPlan([talking("i1"), library("s1")]).kind, "conflict");
  assert.equal(batchPlan([talking("i1"), talking("i9", { batchId: "b2" })]).kind, "conflict");
  assert.deepEqual(batchPlan([]), { kind: "empty" });
  assert.deepEqual(batchPlan([talking("i1", { ready: false })]), { kind: "empty" });
});

test("result boxes tell the truth about the shared queue", () => {
  const queued = itemStatus({ item_id: "a", position: 0, phase: "queued", queue_position: 2, estimate_minutes: 18 });
  assert.equal(queued.label, "排队中 · 第 2 位");
  assert.match(queued.detail, /全站按顺序处理，预计 18 分钟内完成/);
  assert.deepEqual(itemStatus({ item_id: "a", position: 0, phase: "planning" }).done, 2);
  assert.equal(itemStatus({ item_id: "a", position: 0, phase: "rendering" }).label, "生成视频中");
  assert.equal(itemStatus({ item_id: "a", position: 0, phase: "done" }).tone, "ok");
  assert.equal(itemStatus({ item_id: "a", position: 0, phase: "failed", error: "积分不足，充值后点重试。" }).detail, "积分不足，充值后点重试。");
  assert.equal(itemStatus({ item_id: "a", position: 0, waiting_for_source: true }).label, "口播未完成");
  for (const phase of ["queued", "transcribing", "preparing", "planning", "rendering", "done", "failed"]) {
    const status = itemStatus({ item_id: "a", position: 0, phase });
    assert.doesNotMatch(`${status.label}${status.detail}`, /[A-Z]{3,}|planning|bundle|task/i);
  }
});

test("go to finishing only when nothing is still running and something finished", () => {
  const row = (phase) => ({ item_id: phase, position: 0, phase });
  assert.equal(batchFinished([row("done"), row("rendering")]).finished, false);
  assert.deepEqual(batchFinished([row("done"), row("failed"), { item_id: "x", position: 2 }]), { finished: true, done: 1, failed: 1, active: 0 });
  assert.equal(batchFinished([row("failed")]).finished, false);
  assert.equal(batchFinished([]).finished, false);
});

test("summary and template needs in plain words", () => {
  assert.equal(generationSummary(3, 20).credits, "预计 60 积分（每条 20）");
  assert.match(generationSummary(3, 20).time, /约 18 分钟（逐条处理/);
  // Other people's videos ahead on the shared worker are part of the honest estimate.
  assert.match(generationSummary(2, 20, 6, { tasks_ahead: 3, minutes_ahead: 11 }).time, /约 23 分钟（剪辑服务全站共用，前面还有 3 个任务/);
  assert.match(itemStatus({ item_id: "a", position: 0, phase: "queued", queue_position: 1, queue_ahead: 4, estimate_minutes: 26 }).detail, /前面还有 4 个任务，预计 26 分钟内完成/);
  assert.equal(itemStatus({ item_id: "a", position: 0, phase: "rendering", queue_ahead: 2, estimate_minutes: 16 }).label, "等待生成视频");
  assert.equal(generationSummary(1, null).credits, "按实际用量计费");
  assert.equal(durationLabel(21040), "21秒");
  assert.equal(durationLabel(95000), "1分35秒");
  // C11：只有后端 MG 白名单里的模板才写「支持 MG 动效」；白名单没读到时不声称支持。
  assert.match(templateNeeds({ id: "bihuo-36-v1", capabilities: ["images", "music"], engine: "bihuo-full-suite" }, ["bihuo-36-v1"]), /支持配图.*支持 MG 动效/);
  assert.doesNotMatch(templateNeeds({ id: "bihuo-14-v1", capabilities: ["images"], engine: "bihuo-full-suite" }, ["bihuo-36-v1"]), /MG/);
  assert.doesNotMatch(templateNeeds({ id: "bihuo-36-v1", capabilities: ["images"], engine: "bihuo-full-suite" }), /MG/);
  assert.match(templateNeeds({ capabilities: ["music"], material_mode: "speech" }), /不需要配图/);
});

// C3：黑底黄字适合短句；长句口播稿选它时给一句轻提示，其它模板和短句稿不提示。
test("黑底黄字 warns lightly about long sentences only", () => {
  const long = "家具不是天天买。我建议你先量好尺寸再去门店慢慢挑，所以挑家具这件事。";
  assert.match(shortCaptionHint("bihuo-34-v1", [long]), /适合短句：口播稿里有 1 句超过 9 个字/);
  assert.equal(shortCaptionHint("bihuo-34-v1", ["家具不是天天买，但你天天用。"]), null);
  assert.equal(shortCaptionHint("bihuo-36-v1", [long]), null);
  assert.equal(shortCaptionHint(undefined, [long]), null);
  assert.equal(shortCaptionHint("bihuo-34-v1", []), null);
});
