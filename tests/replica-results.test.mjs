import assert from "node:assert/strict";
import test from "node:test";
import { firstMissingReplicaOrdinal } from "../lib/replica/results.ts";

const items = [{ id: "first", ordinal: 0 }, { id: "second", ordinal: 1 }];
const output = id => ({ direction: "output", is_deliverable: true, job_item_id: id });

test("a delivered first image leaves retry on the second screen", () => {
  assert.equal(firstMissingReplicaOrdinal(items, [output("first")]), 1);
});
test("an out-of-order second image keeps retry on the first screen", () => {
  assert.equal(firstMissingReplicaOrdinal(items, [output("second")]), 0);
});
test("all delivered screens need no retry action", () => {
  assert.equal(firstMissingReplicaOrdinal(items, items.map(item => output(item.id))), undefined);
});
test("input, auxiliary and unrelated outputs cannot hide missing images", () => {
  assert.equal(firstMissingReplicaOrdinal(items, [
    { ...output("first"), direction: "input" },
    { ...output("first"), is_deliverable: false }, output("unrelated"),
  ]), 0);
});
test("the first missing ordinal is stable when records are unordered", () => {
  assert.equal(firstMissingReplicaOrdinal([...items].reverse(), []), 0);
});
test("empty results do not invent a retry target", () => {
  assert.equal(firstMissingReplicaOrdinal([], []), undefined);
});
