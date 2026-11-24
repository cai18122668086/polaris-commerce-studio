import assert from "node:assert/strict";
import test from "node:test";
import { resumableEditing, resumablePreparation } from "../features/video-studio/editing-resume.ts";

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

test("nothing billable or finished is adopted, and a newer check replaces an older failure", () => {
  const empty = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "failed", call_state: "response_saved", error_code: "EDITING_PLAN_EMPTY_RESPONSE" })];
  assert.equal(resumablePreparation(empty, "t1", "bihuo-02-v1"), undefined);
  const unsent = [job("p1", "prepare", "2026-11-24T19:08:00Z")];
  assert.equal(resumablePreparation(unsent, "t1", "bihuo-02-v1"), undefined);
  const done = [job("p1", "prepare", "2026-11-24T19:08:00Z"), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1" })];
  assert.equal(resumablePreparation(done, "t1", "bihuo-02-v1"), undefined);
  const newer = [...empty.slice(0, 1), job("g1", "generate", "2026-11-24T19:08:50Z", { prepared_task_id: "p1", status: "failed", call_state: "response_saved" }), job("p2", "prepare", "2026-11-24T19:33:00Z")];
  assert.equal(resumablePreparation(newer, "t1", "bihuo-02-v1"), undefined);
});
