import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/generation-progress.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { generationProgress, elapsedLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("video stage feedback follows real stages and never claims early completion", () => {
  const job = { status: "running", kind: "lipsync" };
  const stages = ["tts_submitting", "preparing_forward_template", "lipsync_generating", "downloading_video"];
  const progress = stages.map(stage => generationProgress({ ...job, stage }));
  assert.deepEqual(progress.map(state => state.step), [0, 1, 2, 3]);
  assert.ok(progress.every(state => state.active && !state.done && state.width < 100));
  assert.equal(generationProgress({ ...job, stage: "completed", status: "completed" }).width, 100);
});

test("failed and uncertain jobs stop motion; avatar review is separate from completion", () => {
  for (const status of ["failed", "unknown", "awaiting_resume", "rejected"]) {
    const state = generationProgress({ status, kind: "lipsync", stage: "lipsync_generating" });
    assert.equal(state.active, false);
    assert.equal(state.stopped, true);
  }
  const review = generationProgress({ status: "awaiting_review", kind: "h3_template", stage: "awaiting_review" });
  assert.equal(review.review, true);
  assert.equal(review.done, false);
  assert.equal(elapsedLabel(125), "2 分 5 秒");
});
