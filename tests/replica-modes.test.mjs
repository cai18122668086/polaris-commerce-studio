import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_REPLICA_METHOD, REPLICA_MODE_CHOICES, REPLICA_MODE_VERSION, replicaCreditsFor, replicaDraftMethod, replicaSpeedFor } from "../lib/replica/modes.ts";

test("new work starts with recommended style imitation and uses the matching workflow and tariff", () => {
  assert.equal(DEFAULT_REPLICA_METHOD, "style");
  const style = REPLICA_MODE_CHOICES.find(option => option.value === "style");
  const exact = REPLICA_MODE_CHOICES.find(option => option.value === "exact");
  assert.equal(style.label, "风格模仿");
  assert.equal(style.recommended, true);
  assert.match(style.description, /5 分钟.*功能强大/);
  assert.equal(exact.label, "一比一复刻");
  assert.match(exact.description, /40 分钟.*一模一样/);
  for (const option of REPLICA_MODE_CHOICES) assert.equal(replicaCreditsFor(option.value), option.price);
  assert.equal(replicaSpeedFor("style"), "fast");
  assert.equal(replicaSpeedFor("exact"), "standard");
});

test("unsubmitted old drafts adopt the recommendation while current explicit choices survive reload", () => {
  assert.equal(replicaDraftMethod({}), "style");
  assert.equal(replicaDraftMethod({ replicationMethod: "exact" }), "style");
  assert.equal(replicaDraftMethod({ replicaModeVersion: REPLICA_MODE_VERSION, replicationMethod: "exact" }), "exact");
  assert.equal(replicaDraftMethod({ replicaModeVersion: REPLICA_MODE_VERSION, replicationMethod: "style" }), "style");
});
