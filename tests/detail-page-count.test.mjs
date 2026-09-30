import assert from "node:assert/strict";
import test from "node:test";
import { parseDetailPageCount } from "../lib/detail-page-count.ts";

test("detail count accepts every legal integer without rounding invalid input", () => {
  for (let count = 1; count <= 12; count++) assert.equal(parseDetailPageCount(String(count)), count);
  for (const input of ["", "0", "-1", "1.5", "3.0", "abc", "13", "1e1", " 3 "]) {
    assert.equal(parseDetailPageCount(input), undefined, input);
  }
});
