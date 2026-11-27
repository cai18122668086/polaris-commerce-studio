import assert from "node:assert/strict";
import test from "node:test";
import { parseScriptsParam, voiceHref, MAX_SCRIPTS } from "../features/video-studio/flow-params.ts";

const A = "6f1c2a3e-0000-4000-8000-000000000001";
const B = "6f1c2a3e-0000-4000-8000-000000000002";
const C = "6f1c2a3e-0000-4000-8000-000000000003";

test("three chosen entries go to the voice page as ?scripts= in the chosen order", () => {
  const href = voiceHref([B, A, C]);
  assert.equal(href, `/video-studio/create?scripts=${B},${A},${C}`);
  const url = new URL(href, "https://example.test");
  assert.deepEqual(parseScriptsParam(url.searchParams), [B, A, C]);
  assert.equal(voiceHref([A], "proj-1"), `/video-studio/create?scripts=${A}&project=proj-1`);
  assert.equal(voiceHref([]), "/video-studio/create");
});

test("the voice page ignores junk, repeats and anything past 50 ids", () => {
  assert.deepEqual(parseScriptsParam(` ${A},,${A},<script>,${B} `), [A, B]);
  assert.deepEqual(parseScriptsParam(null), []);
  const many = Array.from({ length: 70 }, (_, i) => `id-${i}`).join(",");
  assert.equal(parseScriptsParam(many).length, MAX_SCRIPTS);
});

