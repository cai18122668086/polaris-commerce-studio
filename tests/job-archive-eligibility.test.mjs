import assert from "node:assert/strict";
import test from "node:test";
import { canDownloadJobArchive } from "../lib/jobs/results.ts";

function job(type, count = 3) {
  return { type, status: "completed", expected_item_count: count, succeeded_item_count: count, failed_item_count: 0,
    assets: Array.from({ length: count }, (_, ordinal) => ({ asset_id: `asset-${ordinal}`, direction: "output", is_deliverable: true, ordinal })),
    items: Array.from({ length: count }, () => ({ status: "succeeded", error_details: null })) };
}

test("archive controls match supported backend types and complete deliverables", () => {
  for (const type of ["detail_pack", "domestic_main_image", "amazon_visual_suite"]) assert.equal(canDownloadJobArchive(job(type)), true);
  for (const type of ["reference_remix", "product_image", "creative_image", "model_pose_transfer", "local_edit"]) assert.equal(canDownloadJobArchive(job(type)), false);
  const detail = job("detail_pack");
  detail.assets[0].is_deliverable = false;
  assert.equal(canDownloadJobArchive(detail), false);
  assert.equal(canDownloadJobArchive(job("detail_pack", 0)), false);
  assert.equal(canDownloadJobArchive(undefined), false);
});

test("partial archives only allow preserved Amazon infrastructure failures", () => {
  const amazon = job("amazon_visual_suite", 21);
  amazon.status = "partial"; amazon.succeeded_item_count = 20; amazon.failed_item_count = 1;
  amazon.items[0] = { status: "failed", error_details: { failure_kind: "review_infrastructure_failure", image_quality_failed: false, generated_asset_preserved: true } };
  assert.equal(canDownloadJobArchive(amazon), true);
  amazon.items[0].error_details.image_quality_failed = true;
  assert.equal(canDownloadJobArchive(amazon), false);
  amazon.items[0].error_details.image_quality_failed = false;
  amazon.items[1].status = "running";
  assert.equal(canDownloadJobArchive(amazon), false);
  for (const type of ["detail_pack", "domestic_main_image"]) assert.equal(canDownloadJobArchive({ ...job(type), status: "partial" }), false);
});
