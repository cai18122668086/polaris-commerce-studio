import assert from "node:assert/strict";
import test from "node:test";
import { editingTaskProgress, planningJobProgress, stepStates } from "../features/video-studio/editing-progress.ts";

test("planning stages map onto analyze and arrange", () => {
  assert.equal(planningJobProgress({ status: "running", stage: "reading_inputs" }).step, "analyze");
  assert.equal(planningJobProgress({ status: "running", stage: "planning" }).label, "编排画面");
  const prepared = planningJobProgress({ status: "prepared", stage: "prepared" });
  assert.deepEqual([prepared.step, prepared.outcome, prepared.label], ["arrange", "waiting_user", "待继续"]);
  assert.equal(planningJobProgress({ status: "completed", stage: "completed" }).step, "render");
});

test("render stages land on 生成视频 and preview waits for the user", () => {
  for (const stage of ["preparing_foreground", "rendering", "validating", "building_preview", "storing"]) {
    assert.equal(editingTaskProgress({ status: "running", stage }).label, "生成视频");
  }
  const review = editingTaskProgress({ status: "awaiting_review", stage: "preview_ready" });
  assert.deepEqual([review.step, review.outcome, review.label], ["review", "waiting_user", "待你确认"]);
  const done = editingTaskProgress({ status: "completed", stage: "completed" });
  assert.deepEqual([done.step, done.outcome], ["review", "done"]);
});

test("recognition tasks never claim later steps", () => {
  assert.equal(editingTaskProgress({ status: "running", stage: "rendering", mode: "transcript" }).step, "analyze");
  assert.equal(editingTaskProgress({ status: "completed", stage: "completed", mode: "transcript" }).label, "口播已识别");
  assert.equal(editingTaskProgress({ status: "failed", stage: "aligning", mode: "transcript" }).label, "识别未完成");
});

test("failures and cancellations keep the step where they stopped", () => {
  const failed = editingTaskProgress({ status: "failed", stage: "compiling" });
  assert.deepEqual([failed.step, failed.outcome, failed.label], ["arrange", "failed", "剪辑未完成"]);
  assert.equal(planningJobProgress({ status: "cancelled", stage: "planning" }).outcome, "cancelled");
  assert.equal(editingTaskProgress({ status: "running", stage: "unknown_stage" }).detail, "正在处理");
});

test("step states mark earlier steps done and the current one", () => {
  const states = stepStates(editingTaskProgress({ status: "running", stage: "rendering" })).map(s => s.state);
  assert.deepEqual(states, ["done", "done", "current", "todo"]);
  assert.deepEqual(stepStates(editingTaskProgress({ status: "completed", stage: "completed" })).map(s => s.state), ["done", "done", "done", "done"]);
});
