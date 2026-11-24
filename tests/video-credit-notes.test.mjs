import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/credit-notes.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { costNote } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("unconfigured prices say so instead of inventing a number", () => {
  assert.deepEqual(costNote(["lipsync"], {}), { text: "价格待定", credits: null, insufficient: false });
  assert.equal(costNote(["lipsync"], { lipsync: null }, { available: 120, enforced: true }).text, "价格待定 · 可用 120 积分");
});

test("a priced action shows the estimate and the balance", () => {
  assert.equal(costNote(["lipsync"], { lipsync: 30 }, { available: 1200, enforced: true }).text, "预计 30 积分 · 可用 1,200 积分");
});

test("two-step charges are shown as one total up front", () => {
  const note = costNote(["avatar_motion", "avatar_register"], { avatar_motion: 20, avatar_register: 50 });
  assert.equal(note.text, "共需 70 积分（分 2 步扣）");
  assert.equal(note.credits, 70);
  assert.equal(costNote(["avatar_motion", "avatar_register"], { avatar_motion: 20 }).credits, null);
});

test("insufficient only when billing is enforced", () => {
  assert.equal(costNote(["voice_clone"], { voice_clone: 50 }, { available: 10, enforced: true }).insufficient, true);
  assert.equal(costNote(["voice_clone"], { voice_clone: 50 }, { available: 10, enforced: false }).insufficient, false);
});
