import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/credit-notes.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { billableLabel, costNote, creditPhrase, isPriced, pricesConfigured, whenPriced, FREE_TRIAL_TEXT, UNPRICED_TEXT } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("价格为空：统一显示「灰度测试期间不扣积分」", () => {
  assert.equal(FREE_TRIAL_TEXT, "灰度测试期间不扣积分");
  assert.equal(UNPRICED_TEXT, FREE_TRIAL_TEXT);
  assert.deepEqual(costNote(["lipsync"], {}), { text: "灰度测试期间不扣积分", credits: null, insufficient: false });
  assert.equal(costNote(["lipsync"], { lipsync: null }, { available: 120, enforced: true }).text, "灰度测试期间不扣积分 · 可用 120 积分");
  assert.equal(costNote(["lipsync"], {}, { available: 0, enforced: true }).insufficient, false);
  assert.equal(billableLabel("生成预览", null), "生成预览 · 不扣积分");
  assert.equal(billableLabel("生成预览", undefined), "生成预览 · 不扣积分");
  assert.equal(creditPhrase(null, { per: "张", failureFree: true }), "灰度测试期间不扣积分");
  assert.equal(whenPriced(null, "失败的不扣积分"), "");
  for (const text of [costNote(["cover_generate"], {}).text, billableLabel("x", null), creditPhrase(undefined)]) {
    assert.doesNotMatch(text, /按实际|计费|失败不扣|价格待定/);
  }
});

test("价格是否配置：由价格表驱动", () => {
  assert.equal(pricesConfigured({}), false);
  assert.equal(pricesConfigured({ lipsync: null }), false);
  assert.equal(pricesConfigured({ lipsync: 30 }), true);
  assert.equal(pricesConfigured({ lipsync: 0 }), true);
  assert.equal(pricesConfigured({ lipsync: 30 }, ["lipsync"]), true);
  assert.equal(pricesConfigured({ lipsync: 30 }, ["lipsync", "editing_render"]), false);
  assert.equal(pricesConfigured({ lipsync: 30 }, []), false);
  assert.equal(isPriced(0), true);
  assert.equal(isPriced(Number.NaN), false);
  assert.equal(isPriced(null), false);
});

test("有价格：显示具体积分", () => {
  assert.equal(billableLabel("生成预览", 20), "生成预览 · 20 积分");
  assert.equal(billableLabel("确认加入", 1200), "确认加入 · 1,200 积分");
  assert.equal(billableLabel("生成预览", 0), "生成预览 · 0 积分");
  assert.equal(creditPhrase(7, { per: "张", failureFree: true }), "7 积分/张，失败不扣");
  assert.equal(creditPhrase(1500), "1,500 积分");
  assert.equal(whenPriced(7, "失败的不扣积分"), "失败的不扣积分");
  assert.equal(costNote(["lipsync"], { lipsync: 30 }, { available: 1200, enforced: true }).text, "预计 30 积分 · 可用 1,200 积分");
});

test("two-step charges are shown as one total up front", () => {
  const note = costNote(["avatar_motion", "avatar_register"], { avatar_motion: 20, avatar_register: 50 });
  assert.equal(note.text, "共需 70 积分（分 2 步扣）");
  assert.equal(note.credits, 70);
  const partial = costNote(["avatar_motion", "avatar_register"], { avatar_motion: 20 });
  assert.equal(partial.credits, null);
  assert.equal(partial.text, "灰度测试期间不扣积分");
});

test("insufficient only when billing is enforced", () => {
  assert.equal(costNote(["voice_clone"], { voice_clone: 50 }, { available: 10, enforced: true }).insufficient, true);
  assert.equal(costNote(["voice_clone"], { voice_clone: 50 }, { available: 10, enforced: false }).insufficient, false);
});
