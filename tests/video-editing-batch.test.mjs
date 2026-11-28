import assert from "node:assert/strict";
import test from "node:test";
import { batchFinished, batchPlan, candidateKey, durationLabel, finishAction, generationSummary, itemMinutes, itemStatus, minutesRange, templateNeeds } from "../features/video-studio/editing-batch.ts";

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
  assert.match(queued.detail, /全站按顺序处理，预计约 14–24 分钟完成/);
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
  assert.deepEqual(batchFinished([row("done"), row("failed"), { item_id: "x", position: 2 }]), { finished: true, canFinish: true, done: 1, failed: 1, active: 0 });
  assert.equal(batchFinished([row("failed")]).finished, false);
  assert.equal(batchFinished([]).finished, false);
});

test("summary and template needs in plain words", () => {
  assert.equal(generationSummary([null, null, null], 20).credits, "预计 60 积分（每条 20）");
  // Unknown lengths: about 6 minutes each, said as a range.
  assert.match(generationSummary([null, null, null], 20).time, /约 14–24 分钟（逐条处理/);
  // Other people's videos ahead on the shared worker are part of the honest estimate.
  assert.match(generationSummary([null, null], 20, { tasks_ahead: 3, minutes_ahead: 11 }).time, /约 18–30 分钟（剪辑服务全站共用，前面还有 3 个任务/);
  assert.match(itemStatus({ item_id: "a", position: 0, phase: "queued", queue_position: 1, queue_ahead: 4, estimate_minutes: 26 }).detail, /前面还有 4 个任务，预计约 20–34 分钟完成/);
  assert.equal(itemStatus({ item_id: "a", position: 0, phase: "rendering", queue_ahead: 2, estimate_minutes: 16 }).label, "等待生成视频");
  assert.match(itemStatus({ item_id: "a", position: 0, phase: "transcribing", queue_ahead: 0, estimate_minutes: 6 }).detail, /^前面没有其他任务，马上开始，预计约 4–8 分钟完成$/);
  assert.match(itemStatus({ item_id: "a", position: 0, phase: "rendering", estimate_minutes: 4 }).detail, /自动导出高清，还需约 3–6 分钟/);
  // No configured price: the page shows the shared gray-test line (credit-notes).
  assert.equal(generationSummary([null], null).credits, null);
  assert.equal(durationLabel(21040), "21秒");
  assert.equal(durationLabel(95000), "1分35秒");
  assert.match(templateNeeds({ capabilities: ["images", "music"], engine: "bihuo-full-suite" }), /支持配图.*支持 MG 动效/);
  assert.match(templateNeeds({ capabilities: ["music"], material_mode: "speech" }), /不需要配图/);
});

test("C7: the estimate follows each video's length and is said as a range", () => {
  assert.equal(itemMinutes(null), 6);
  assert.equal(Math.round(itemMinutes(13000) * 10) / 10, 4.5);
  assert.equal(Math.round(itemMinutes(180000) * 10) / 10, 36.5);
  // Server coefficients win over the defaults.
  assert.equal(itemMinutes(60000, { minutes_base: 1, minutes_per_source_minute: 10 }), 11);
  assert.equal(minutesRange(10), "约 8–13 分钟");
  assert.equal(minutesRange(1), "约 1–2 分钟");
  // A 13-second and a 3-minute video are no longer estimated the same.
  assert.notEqual(generationSummary([13000], null).time, generationSummary([180000], null).time);
});

test("B4: go to finishing as soon as one item is done, saying where the rest go", () => {
  const row = (phase) => ({ item_id: phase + Math.random(), position: 0, phase });
  const first = batchFinished([row("done"), row("rendering"), row("queued")]);
  assert.equal(first.canFinish, true);
  assert.equal(first.finished, false);
  assert.deepEqual(finishAction(first), { label: "去成片（已完成 1 条）", note: "其余 2 条剪完会出现在成片页，不用等全部完成" });
  assert.equal(batchFinished([row("rendering")]).canFinish, false);
  assert.equal(finishAction(batchFinished([row("done"), row("failed")])).note, "1 条未完成，可在上面单独重试");
});
