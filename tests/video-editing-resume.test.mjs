import assert from "node:assert/strict";
import test from "node:test";
import { planSubmission, resumableEditing, resumablePreparation } from "../features/video-studio/editing-resume.ts";

const transcript = (id, at, status = "completed") => ({ id, status, created_at: at, options: { mode: "transcript" }, artifacts: status === "completed" ? [{ role: "transcript" }] : [] });
const job = (id, mode, at, extra = {}) => ({ id, mode, status: mode === "prepare" ? "prepared" : "completed", call_state: "not_submitted", error_code: null, base_task_id: "t1", prepared_task_id: null, created_at: at, overlay_template: { id: "bihuo-02-v1" }, ...extra });

test("reopening restores the recognized speech and the template of its last planning", () => {
  const tasks = [transcript("t1", "2026-11-24T18:58:00Z"), { ...transcript("r1", "2026-11-24T19:20:00Z"), options: { mode: "suite_plan" } }];
  const jobs = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "failed", call_state: "response_saved" })];
  assert.deepEqual(resumableEditing(tasks, jobs), { taskId: "t1", templateId: "bihuo-02-v1" });
});

test("a recognition closed mid-way is restored so its progress stays visible", () => {
  assert.deepEqual(resumableEditing([transcript("t2", "2026-11-24T18:58:00Z", "running")], []), { taskId: "t2", templateId: undefined });
  assert.equal(resumableEditing([transcript("t3", "2026-11-24T18:58:00Z", "failed")], []), undefined);
});

test("a newer recognition wins over an older planning source", () => {
  const tasks = [transcript("t1", "2026-11-24T18:58:00Z"), transcript("t9", "2026-11-24T20:00:00Z")];
  assert.deepEqual(resumableEditing(tasks, [job("p1", "prepare", "2026-11-24T19:08:00Z")]), { taskId: "t9", templateId: "bihuo-02-v1" });
});

test("a saved model response stays recoverable for free after refresh", () => {
  const failed = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "failed", call_state: "response_saved", error_code: "EDITING_PLAN_CONTRACT_INVALID" })];
  assert.equal(resumablePreparation(failed, "t1", "bihuo-02-v1"), "p1");
  assert.equal(resumablePreparation(failed, "t1", "other-template"), undefined);
  assert.equal(resumablePreparation(failed, "", "bihuo-02-v1"), undefined);
  const running = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "running" })];
  assert.equal(resumablePreparation(running, "t1", "bihuo-02-v1"), "p1");
});

test("an empty response or an unsent check is never adopted", () => {
  const empty = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "failed", call_state: "response_saved", error_code: "EDITING_PLAN_EMPTY_RESPONSE" })];
  assert.equal(resumablePreparation(empty, "t1", "bihuo-02-v1"), undefined);
  const unsent = [job("p1", "prepare", "2026-11-24T19:08:00Z")];
  assert.equal(resumablePreparation(unsent, "t1", "bihuo-02-v1"), undefined);
});

// P0 回归：编排已完成、预览待确认时刷新页面，主按钮曾回到「开始智能剪辑」，再点就重复编排、重复扣费。
test("a finished planning is restored after refresh so the page offers its preview instead of a new paid run", () => {
  const done = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", preview_task_id: "r1" })];
  assert.equal(resumablePreparation(done, "t1", "bihuo-02-v1"), "p1");
  // A later, never-submitted check (e.g. a stray click) does not hide the finished one.
  assert.equal(resumablePreparation([...done, job("p2", "prepare", "2026-11-24T20:00:00Z")], "t1", "bihuo-02-v1"), "p1");
  // A live run wins over an older recoverable failure.
  const mixed = [job("p0", "prepare", "2026-11-24T18:00:00Z"), job("g0", "generate", "2026-11-24T18:01:00Z", { prepared_task_id: "p0", status: "failed", call_state: "response_saved" }), ...done];
  assert.equal(resumablePreparation(mixed, "t1", "bihuo-02-v1"), "p1");
  assert.equal(resumablePreparation(done, "t1", "bihuo-36-v1"), undefined);
});

test("a new check of the same request joins the existing result instead of paying again", () => {
  const jobs = [
    job("p1", "prepare", "2026-11-24T19:08:00Z", { request_sha256: "abc" }),
    job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", request_sha256: "abc" }),
    job("p2", "prepare", "2026-11-24T20:00:00Z", { request_sha256: "abc" }),
    job("p3", "prepare", "2026-11-24T20:01:00Z", { request_sha256: "other" }),
  ];
  assert.equal(planSubmission(jobs, jobs[0])?.id, "g1");
  assert.equal(planSubmission(jobs, jobs[2])?.id, "g1");
  assert.equal(planSubmission(jobs, jobs[3]), undefined);
  assert.equal(planSubmission(jobs, undefined), undefined);
  // A failed run of the same request does not block a fresh, explicit retry.
  const failed = [job("p1", "prepare", "2026-11-24T19:08:00Z", { request_sha256: "abc" }), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", request_sha256: "abc", status: "failed", call_state: "not_submitted" }), job("p2", "prepare", "2026-11-24T20:00:00Z", { request_sha256: "abc" })];
  assert.equal(planSubmission(failed, failed[2]), undefined);
});
