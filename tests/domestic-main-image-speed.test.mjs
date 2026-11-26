import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { mainImageSpeed, mainImageSpeedSettings } from "../lib/domestic-main-image-speed.ts";

test("main image has a single version: new tasks always use the one-pass workflow", () => {
  const workspace = readFileSync(new URL("../components/domestic-main-image-workspace.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(workspace, /name="main-image-speed"/);
  assert.match(workspace, /const speed = "native_fast" as const;/);
  assert.match(workspace, /mainImageSpeedSettings\(speed\)/);
});
test("legacy tasks are still restored with the version they were created with", () => {
  for (const value of [undefined, null, "standard", "fast", "parallel_v20", {}, true]) assert.equal(mainImageSpeed(value), "standard");
  assert.equal(mainImageSpeed("native_fast"), "native_fast");
  const legacy = { product_name: "商品", auto_start_after_plan: true };
  assert.deepEqual({ ...legacy, ...mainImageSpeedSettings("standard") }, legacy);
  assert.deepEqual(mainImageSpeedSettings("native_fast"), { main_image_speed: "native_fast" });
});
