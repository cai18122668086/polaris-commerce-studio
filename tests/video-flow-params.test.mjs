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


import { parseBatchParam, parseItemParam, parseFlowParams, editingHref, finishHref, worksHref, stepHref } from "../features/video-studio/flow-params.ts";

test("?batch= carries one batch from 口播 to 剪辑 to 成片 to 我的作品", () => {
  const batch = "b6f1c2a3-0000-4000-8000-00000000000b";
  assert.equal(editingHref(batch), `/video-studio/editing?batch=${batch}`);
  assert.equal(finishHref({ batch }), `/video-studio/finish?batch=${batch}`);
  assert.equal(worksHref(batch), `/video-studio/works?batch=${batch}`);
  assert.equal(worksHref(), "/video-studio/works");
  for (const href of [editingHref(batch), finishHref({ batch }), worksHref(batch)]) {
    assert.equal(parseBatchParam(new URL(href, "https://example.test").searchParams), batch);
  }
});

test("a single finished work re-enters 成片 with ?item=; batch wins when both are known", () => {
  assert.equal(finishHref({ item: "item-7" }), "/video-studio/finish?item=item-7");
  assert.equal(finishHref({ batch: "b-1", item: "item-7" }), "/video-studio/finish?batch=b-1");
  assert.equal(parseItemParam(new URLSearchParams("item=item-7")), "item-7");
});

test("junk batch or item ids are dropped, never echoed into links", () => {
  assert.equal(parseBatchParam("<script>"), null);
  assert.equal(parseBatchParam(new URLSearchParams("batch=")), null);
  assert.equal(parseItemParam("a".repeat(41)), null);
  assert.equal(editingHref("bad id"), "/video-studio/editing");
});

test("the step bar keeps the flow context on every step", () => {
  const params = new URLSearchParams(`scripts=${A},${B}&batch=b-1&project=p-1`);
  const context = parseFlowParams(params);
  assert.deepEqual(context, { batch: "b-1", item: null, scripts: [A, B], project: "p-1" });
  assert.equal(stepHref("writing", context), "/video-studio/writing?project=p-1");
  assert.equal(stepHref("voice", context), `/video-studio/create?scripts=${A},${B}&batch=b-1&project=p-1`);
  assert.equal(stepHref("editing", context), "/video-studio/editing?batch=b-1&project=p-1");
  assert.equal(stepHref("finish", context), "/video-studio/finish?batch=b-1");
  assert.equal(stepHref("finish", {}), "/video-studio/finish");
});
