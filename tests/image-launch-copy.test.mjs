import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  isChineseUserCopy,
  jobAssetRoleLabel,
  jobFailureMessage,
  jobItemLabel,
  jobItemStageLabel,
  jobNote,
  jobStageLabel,
  jobStatusLabel,
  localEditReviewReasons,
  safeJobFailureSummary,
} from "../lib/jobs/presentation.ts";

const englishMessages = [
  "Aurora v2.0 six-page set audit did not pass.",
  "Worker lease expired after provider invocation.",
  "The selected tabletop was changed to light marble and the product remains unchanged, but the FINAL composite has a conspicuous rectangular boundary at the selection's right edge.",
  "Planner request failed with HTTP 503",
];

test("backend English error messages never reach customers", () => {
  for (const message of englishMessages) {
    for (const code of ["AURORA_SET_AUDIT_FAILED", "PROVIDER_OUTCOME_UNKNOWN", "LOCAL_EDIT_VISUAL_REVIEW_REJECTED", "SOME_NEW_CODE", null]) {
      const text = jobFailureMessage(code, message);
      assert.ok(text && isChineseUserCopy(text), `${code}: ${text}`);
      assert.doesNotMatch(text, /[A-Za-z]{5,}/);
    }
  }
  assert.match(jobFailureMessage("AURORA_SET_AUDIT_FAILED", englishMessages[0]), /整组一致性检查未通过/);
  assert.equal(jobFailureMessage("SOME_NEW_CODE", "国内电商主图规划失败，请重新提交任务。"), "国内电商主图规划失败，请重新提交任务。");
  assert.equal(jobFailureMessage(null, null), null);
  assert.doesNotMatch(safeJobFailureSummary("UNKNOWN"), /请按页面提供的操作重试/);
  assert.match(safeJobFailureSummary("BUDGET_LIMIT_EXCEEDED"), /积分/);
});

test("single-image review states use single-image copy and no raw stage codes", () => {
  assert.equal(jobStatusLabel("awaiting_final_review", "local_edit"), "待确认修改");
  assert.equal(jobStatusLabel("awaiting_final_review", "domestic_main_image"), "等待整组确认");
  assert.equal(jobStageLabel("awaiting_local_edit_review", "awaiting_final_review", "local_edit"), "等待确认修改效果");
  assert.equal(jobStageLabel("private_internal_stage", "processing"), "处理中");
  assert.equal(jobItemStageLabel("set_audit_failed"), "整组审核未通过");
  assert.equal(jobItemStageLabel("private_internal_stage"), null);
  assert.equal(jobItemLabel("page-003", 2), "第 3 页");
  assert.equal(jobItemLabel("result", 0), "第 1 项");
  assert.equal(jobAssetRoleLabel("locked_candidate"), "局部合成候选");
  assert.equal(jobAssetRoleLabel("some_new_role"), "其他素材");
  assert.deepEqual(localEditReviewReasons(["visible_boundary_defect", "unknown"]), ["选区边缘有明显的接缝或分界"]);
});

test("partial jobs only promise retry when the backend offers it, and use one label", () => {
  const base = { type: "domestic_main_image", status: "partial", stage: "partial", output_asset_count: 6 };
  assert.match(jobNote({ ...base, allowed_actions: ["clone"] }), /重新生成整组/);
  assert.doesNotMatch(jobNote({ ...base, allowed_actions: ["clone"] }), /重试/);
  assert.match(jobNote({ ...base, allowed_actions: ["retry"] }), /重试失败项目/);
  assert.equal(jobStatusLabel("partial"), "部分完成");
  assert.equal(jobStageLabel("partial", "partial"), "部分完成");
});

test("job detail offers regenerate-set via clone with a quoted cost, and the local-edit review path", async () => {
  const [panel, regenerate, credit, inspiration, drawer] = await Promise.all([
    readFile("features/jobs/components/job-detail-panel.tsx", "utf8"),
    readFile("features/jobs/components/job-regenerate-set.tsx", "utf8"),
    readFile("components/job-credit-settlement.tsx", "utf8"),
    readFile("components/inspiration-gallery-db-v2.tsx", "utf8"),
    readFile("components/task-drawer.tsx", "utf8"),
  ]);
  assert.match(panel, /<JobRegenerateSet/);
  assert.match(panel, /去确认修改效果/);
  assert.match(regenerate, /useCloneJob/);
  assert.match(regenerate, /credits\/quote/);
  assert.match(regenerate, /重新生成整组/);
  assert.match(credit, /AbortSignal\.timeout/);
  assert.match(inspiration, /登录后即可生成/);
  assert.match(drawer, /isSignedOutError/);
});
