import assert from "node:assert/strict";
import test from "node:test";
import { mergeReplicaProgress, replicaAnalysisMessage, replicaOverallProgress, replicaPlanFailure, replicaWorkflowStep } from "../lib/replica/progress.ts";

const doc = (progress, extra = {}) => ({ id: "rep_test", status: "analysing", payload: { analysis_attempt_id: "attempt-1", progress }, ...extra });

test("exhausted quality reviews explain retained plans instead of suggesting another transport retry", () => {
  const failed = doc(82, {status:"failed"});
  failed.payload.error_code = "REPLICA_PLAN_AUDIT_REJECTED";
  failed.payload.analysis_progress = {stage:"review_plan",total:12,planned:12,reviewed:12,accepted:9,pending_corrections:3};
  const failure = replicaPlanFailure(failed);
  assert.equal(failure.title, "还有 3 屏方案待调整");
  assert.match(failure.message, /已通过的 9 屏方案/);
  assert.match(failure.message, /请先调整/);
  delete failed.payload.analysis_progress;
  assert.equal(replicaPlanFailure(failed).title, "部分方案需要调整");
  failed.payload.error_code = "REPLICA_ANALYSIS_UNAVAILABLE";
  assert.equal(replicaPlanFailure(failed), undefined);
});

test("planning progress explains retained work without presenting a failed screen as a restart", () => {
  const current = doc(82);
  current.payload.analysis_progress = { stage: "review_plan", total: 12, planned: 12, reviewed: 12, accepted: 8, pending_corrections: 4 };
  assert.equal(replicaAnalysisMessage(current), "已确认 8 / 12 屏方案，正在处理剩余部分");
  current.payload.analysis_progress.accepted = 12;
  assert.equal(replicaAnalysisMessage(current), "12 屏方案已确认，正在准备生成");
});

test("replanning and delayed poll responses do not move progress backwards", () => {
  let current;
  for (const progress of [12, 48, 82, 48, 82]) current = mergeReplicaProgress(current, doc(progress));
  assert.equal(current.payload.progress, 82);
  assert.equal(mergeReplicaProgress(doc(82, {updated_at:"2026-10-23T13:00:00Z"}), doc(48, {updated_at:"2026-10-23T12:00:00Z"})).payload.progress, 82);
});

test("an explicitly new analysis or job may reset progress", () => {
  const next = doc(0); next.payload.analysis_attempt_id = "attempt-2";
  assert.equal(mergeReplicaProgress(doc(82), next).payload.progress, 0);
  const retry = doc(25); retry.payload.job_ids = ["job_new"];
  assert.equal(mergeReplicaProgress(doc(82), retry).payload.progress, 25);
});

test("a terminal failure is not revived by an old generating reply", () => {
  const failed = doc(82, {status:"failed"});
  assert.equal(mergeReplicaProgress(failed, doc(70, {status:"generating"})).status, "failed");
});

test("a delayed reply for the old job cannot replace a newer retry", () => {
  const current = doc(25, {updated_at:"2026-10-23T13:00:00Z"});
  current.payload.job_ids = ["job_retry"];
  const stale = doc(95, {updated_at:"2026-10-23T12:00:00Z"});
  stale.payload.job_ids = ["job_old"];
  assert.deepEqual(mergeReplicaProgress(current, stale).payload.job_ids, ["job_retry"]);
});

test("analysis completion and generation share one scale, failure is not success 100%", () => {
  assert.equal(replicaOverallProgress(doc(92)), 22);
  const generated = doc(100, {status:"generating"});
  generated.payload.job_ids = ["job_new"];
  generated.payload.execution_progress = {percentage:25};
  assert.equal(replicaOverallProgress(generated), 25);
  assert.equal(replicaOverallProgress({...generated,status:"failed"}), 25);
  assert.equal(replicaOverallProgress({...generated,status:"completed"}), 100);
});

test("failed, partial and cancelled suites never mark successful delivery in the stepper", () => {
  for (const status of ["failed", "partial", "cancelled", "processing"]) {
    const current = doc(95, {status}); current.payload.job_ids = ["job_suite"];
    assert.equal(replicaWorkflowStep(current, {job_suite:status}), 4);
  }
  const success = doc(100, {status:"completed"}); success.payload.job_ids = ["job_suite"];
  assert.equal(replicaWorkflowStep(success, {job_suite:"completed"}), 5);
  success.payload.submission_complete = false;
  assert.equal(replicaWorkflowStep(success, {job_suite:"completed"}), 4);
});
