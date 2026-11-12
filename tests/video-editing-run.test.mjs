import assert from "node:assert/strict";
import test from "node:test";
import { EditingAutomaticRun } from "../features/video-studio/editing-run.ts";

test("one explicit start advances one prepared job once", () => {
  const run = new EditingAutomaticRun();
  const clicked = run.start("source-template-materials");
  assert.equal(run.take("source-template-materials", "prepared-1"), false);
  run.prepared(clicked, "prepared-1");
  assert.equal(run.take("source-template-materials", "prepared-1"), true);
  assert.equal(run.take("source-template-materials", "prepared-1"), false);
});

test("new inputs and late preparation responses cannot revive cancelled starts", () => {
  const run = new EditingAutomaticRun();
  const oldClick = run.start("old-inputs");
  run.cancelUnless("new-inputs");
  run.prepared(oldClick, "late-job");
  assert.equal(run.take("old-inputs", "late-job"), false);
  const nextClick = run.start("new-inputs");
  run.prepared(oldClick, "late-job");
  assert.equal(run.take("new-inputs", "late-job"), false);
  run.prepared(nextClick, "new-job");
  assert.equal(run.take("new-inputs", "new-job"), true);
});

test("reloads and known failures never automatically authorize a paid retry", () => {
  const run = new EditingAutomaticRun();
  const clicked = run.start("inputs");
  run.prepared(clicked, "job");
  run.cancel();
  assert.equal(run.take("inputs", "job"), false);
  assert.equal(new EditingAutomaticRun().take("inputs", "job"), false);
});
