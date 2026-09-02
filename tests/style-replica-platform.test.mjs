import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../components/style-replica-workspace.tsx", import.meta.url),
  "utf8",
);

test("style replica recognizes JD Global Purchase product links", () => {
  assert.match(
    source,
    /matches\("jd\.com"\)\s*\|\|\s*matches\("3\.cn"\)\s*\|\|\s*matches\("npcitem\.jd\.hk"\)/,
  );
});

test("style replica recognizes Pinduoduo product links", () => {
  assert.match(
    source,
    /matches\("pinduoduo\.com"\) \|\| matches\("yangkeduo\.com"\)/,
  );
  assert.match(source, /platform: "pinduoduo"/);
});
