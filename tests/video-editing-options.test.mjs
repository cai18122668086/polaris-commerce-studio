import assert from "node:assert/strict";
import test from "node:test";
import { matchesReferenceScript, referenceScript } from "../features/video-studio/editing-options.ts";

test("reference changes invalidate old transcript choices while empty text preserves legacy input", () => {
  assert.equal(referenceScript(" \n "), undefined);
  assert.equal(matchesReferenceScript({}, " \n "), true);
  assert.equal(matchesReferenceScript({ reference_script: "先上传产品图" }, "先上传产品图  "), true);
  assert.equal(matchesReferenceScript({ reference_script: "先上传产品图" }, "再拉取参考商品"), false);
  assert.equal(matchesReferenceScript({}, "新参考稿"), false);
});

test("music tiers read 轻 / 标准 / 明显 in order and validate saved values", async () => {
  const { editingMusicLabels, editingMusicHints, isEditingMusicPreference } = await import("../features/video-studio/editing-options.ts");
  assert.deepEqual(Object.keys(editingMusicLabels), ["lower", "template", "raise", "off"]);
  assert.deepEqual(Object.keys(editingMusicHints), Object.keys(editingMusicLabels));
  assert.equal(isEditingMusicPreference("raise"), true);
  assert.equal(isEditingMusicPreference("loud"), false);
  assert.equal(isEditingMusicPreference(undefined), false);
});
