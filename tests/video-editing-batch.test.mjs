import assert from "node:assert/strict";
import test from "node:test";
import { batchFinished, batchPlan, candidateKey, durationLabel, generationSummary, itemStatus, templateNeeds } from "../features/video-studio/editing-batch.ts";

const talking = (id, extra = {}) => ({ key: candidateKey("talking", id), kind: "talking", refId: `gen-${id}`, itemId: id, batchId: "b1", projectId: "p", title: `稿${id}`, videoUrl: null, ready: true, ...extra });
const library = (id, extra = {}) => ({ key: candidateKey("library", id), kind: "library", refId: id, projectId: "p", title: `库${id}`, videoUrl: null, ready: true, ...extra });

test("a talking batch is edited as it is; anything else becomes a direct-editing batch", () => {
  assert.deepEqual(batchPlan([talking("i1"), talking("i2")]), { kind: "existing", batchId: "b1", itemIds: ["i1", "i2"] });
  // Unfinished talking items are never sent.
  assert.deepEqual(batchPlan([talking("i1"), talking("i2", { ready: false })]), { kind: "existing", batchId: "b1", itemIds: ["i1"] });
  const mixed = batchPlan([talking("i1"), library("s1"), { ...library("u1"), kind: "upload", key: "upload:u1" }]);
  assert.equal(mixed.kind, "create");
  assert.deepEqual(mixed.items.map(item => item.source_video_ref), [{ kind: "library", id: "gen-i1" }, { kind: "library", id: "s1" }, { kind: "upload", id: "u1" }]);
  assert.ok(mixed.items.every(item => item.drive_mode === "uploaded_video"));
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
  assert.equal(generationSummary(1, null).credits, "按实际用量计费");
  assert.equal(durationLabel(21040), "21秒");
  assert.equal(durationLabel(95000), "1分35秒");
  assert.match(templateNeeds({ capabilities: ["images", "music"], engine: "bihuo-full-suite" }), /支持配图.*支持 MG 动效/);
  assert.match(templateNeeds({ capabilities: ["music"], material_mode: "speech" }), /不需要配图/);
});
