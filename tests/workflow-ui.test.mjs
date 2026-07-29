import assert from "node:assert/strict";
import test from "node:test";

import {
  assertEditableMask,
  createBinaryMask,
  mapDisplayPointToRaster,
} from "../lib/mask/mask-utils.ts";
import {
  canRetryJob,
  selectJobResultAssets,
} from "../lib/jobs/results.ts";

test("display coordinates map to original raster pixels", () => {
  assert.deepEqual(
    mapDisplayPointToRaster(
      260,
      145,
      { left: 10, top: 20, width: 500, height: 250 },
      { width: 2000, height: 1000 },
    ),
    { x: 1000, y: 500 },
  );
  assert.deepEqual(
    mapDisplayPointToRaster(
      -100,
      900,
      { left: 10, top: 20, width: 500, height: 250 },
      { width: 2000, height: 1000 },
    ),
    { x: 0, y: 1000 },
  );
});

test("mask export data is binary black/white with opaque alpha", () => {
  const binary = createBinaryMask(
    new Uint8ClampedArray([
      124, 58, 237, 0,
      124, 58, 237, 1,
      124, 58, 237, 128,
    ]),
    3,
    1,
  );
  assert.deepEqual(
    [...binary.data],
    [
      0, 0, 0, 255,
      255, 255, 255, 255,
      255, 255, 255, 255,
    ],
  );
  assert.equal(binary.selectedPixels, 2);
});

test("empty and full-image masks are rejected", () => {
  assert.throws(
    () => assertEditableMask({ selectedPixels: 0, totalPixels: 4 }),
    /选区为空/,
  );
  assert.throws(
    () => assertEditableMask({ selectedPixels: 4, totalPixels: 4 }),
    /不能授权整张图片/,
  );
  assert.doesNotThrow(() =>
    assertEditableMask({ selectedPixels: 2, totalPixels: 4 }),
  );
});

test("only deliverable output assets become visible results", () => {
  const results = selectJobResultAssets({
    assets: [
      { asset_id: "input", direction: "input", is_deliverable: false, ordinal: 0 },
      { asset_id: "hidden", direction: "output", is_deliverable: false, ordinal: 1 },
      { asset_id: "second", direction: "output", is_deliverable: true, ordinal: 2 },
      { asset_id: "first", direction: "output", is_deliverable: true, ordinal: 1 },
    ],
  });
  assert.deepEqual(results.map((asset) => asset.asset_id), ["first", "second"]);
});

test("retry visibility follows allowed_actions only", () => {
  assert.equal(canRetryJob({ allowed_actions: [] }), false);
  assert.equal(canRetryJob({ allowed_actions: ["retry"] }), true);
  assert.equal(canRetryJob(undefined), false);
});
