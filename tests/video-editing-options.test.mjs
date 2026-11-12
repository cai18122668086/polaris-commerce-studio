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
