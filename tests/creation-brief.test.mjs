import test from "node:test";
import assert from "node:assert/strict";
import { CREATION_BRIEF_KEY, mergeBrief, takeCreationBrief } from "../lib/creation-brief.ts";

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return { getItem: (key) => data.has(key) ? data.get(key) : null, removeItem: (key) => { data.delete(key); }, data };
}

test("创作描述交接一次后从 sessionStorage 删除，不会再次合并", () => {
  const storage = memoryStorage({ [CREATION_BRIEF_KEY]: " 白色身体乳，浴室晨光 " });
  const first = takeCreationBrief(storage);
  assert.equal(first, "白色身体乳，浴室晨光");
  assert.equal(storage.data.has(CREATION_BRIEF_KEY), false);
  assert.equal(takeCreationBrief(storage), undefined);
  assert.equal(mergeBrief("", first), "白色身体乳\n浴室晨光");
});

test("空描述也会被清掉；存储不可用时当作没有描述", () => {
  const storage = memoryStorage({ [CREATION_BRIEF_KEY]: "   " });
  assert.equal(takeCreationBrief(storage), undefined);
  assert.equal(storage.data.has(CREATION_BRIEF_KEY), false);
  assert.equal(takeCreationBrief({ getItem() { throw new Error("blocked"); }, removeItem() {} }), undefined);
});
