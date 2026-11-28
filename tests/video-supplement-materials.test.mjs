import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({
  entryPoints: ["features/video-studio/supplement-materials.ts"],
  bundle: true,
  write: false,
  format: "esm",
  platform: "node",
  logLevel: "silent",
});
const m = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const items = [
  { id: "w1", project_id: "p1", script_text: "持久保湿72小时。以前要涂三层，现在一瓶搞定。", supports_images: true, supports_mg: true },
  { id: "w2", project_id: "p2", script_text: "好皮肤是养出来的。", supports_images: true, supports_mg: true },
];

test("default is no supplement: nothing is sent for any work item", () => {
  assert.deepEqual(m.DEFAULT_SUPPLEMENT, { mode: "none", sources: {}, items: {}, pending: 0 });
  assert.deepEqual(m.supplementForWorkItem(m.DEFAULT_SUPPLEMENT, "w1"), { material_ids: [] });
  assert.equal(m.supplementSummary(m.DEFAULT_SUPPLEMENT), "不加素材");
});

test("materials stay per work item and follow source switches", () => {
  let v = m.setMode(m.DEFAULT_SUPPLEMENT, "custom");
  v = m.toggleSource(v, "mine", true);
  v = m.toggleSource(v, "stock", true);
  v = m.setSourceMaterials(v, "w1", "mine", ["a", "b", "a"]);
  v = m.setSourceMaterials(v, "w1", "stock", ["s1"]);
  v = m.setSourceMaterials(v, "w2", "stock", ["s2"]);
  assert.deepEqual(m.supplementForWorkItem(v, "w1"), { material_ids: ["a", "b", "s1"] });
  assert.deepEqual(m.supplementForWorkItem(v, "w2"), { material_ids: ["s2"] });
  v = m.toggleSource(v, "stock", false);
  assert.deepEqual(m.supplementForWorkItem(v, "w1").material_ids, ["a", "b"]);
  assert.deepEqual(m.supplementForWorkItem(v, "w2").material_ids, []);
  // Switching back to "none" sends nothing but keeps the picks for later.
  const none = m.setMode(v, "none");
  assert.deepEqual(m.supplementForWorkItem(none, "w1"), { material_ids: [] });
  assert.deepEqual(m.supplementForWorkItem(m.setMode(none, "custom"), "w1").material_ids, ["a", "b"]);
});

test("MG is sent only when chosen, with the chosen style", () => {
  let v = m.toggleSource(m.setMode(m.DEFAULT_SUPPLEMENT, "custom"), "mg", true);
  assert.deepEqual(m.supplementForWorkItem(v, "w1"), { material_ids: [], supplement: { mg: { style: "paper" } } });
  v = m.setMgStyle(v, "ink");
  assert.equal(m.supplementForWorkItem(v, "w2").supplement.mg.style, "ink");
  assert.match(m.supplementSummary(v), /MG 动效（墨白）/);
});

test("manual pins are dropped with their material and cleared by auto placement", () => {
  let v = m.toggleSource(m.setMode(m.DEFAULT_SUPPLEMENT, "custom"), "mine", true);
  v = m.setSourceMaterials(v, "w1", "mine", ["a", "b"]);
  v = m.setPlacement(v, "manual");
  v = m.setPin(v, "w1", "a", 1);
  v = m.setPin(v, "w1", "b", 0);
  assert.deepEqual(v.items.w1.pins, { a: 1, b: 0 });
  v = m.setSourceMaterials(v, "w1", "mine", ["b"]);
  assert.deepEqual(v.items.w1.pins, { b: 0 });
  v = m.setPlacement(v, "auto");
  assert.deepEqual(v.items.w1.pins, {});
});

test("unavailable sources and unsupported templates are explained, not hidden", () => {
  const states = [
    { key: "mine", available: true, reason: null, price: "免费" },
    { key: "stock", available: false, reason: "暂未开通", price: "免费" },
    { key: "ai_image", available: true, reason: null, price: "7 积分/张", credits_per_image: 7, max_images: 6 },
    { key: "mg", available: true, reason: null, price: "免费" },
  ];
  assert.equal(m.sourceBlocker("stock", items, states), "暂未开通");
  assert.equal(m.sourceBlocker("mine", items, states), null);
  const apple = items.map(item => ({ ...item, supports_mg: false, supports_images: false }));
  assert.match(m.sourceBlocker("mg", apple, states), /不支持 MG/);
  assert.match(m.sourceBlocker("mine", apple, states), /没有配图位置/);
  const noScript = items.map(item => ({ ...item, script_text: " " }));
  assert.match(m.sourceBlocker("ai_image", noScript, states), /需要口播稿/);
  assert.equal(m.sourceBlocker("mine", noScript, states), null);
});

test("pending blocks generation and cost/licence copy is plain Chinese", () => {
  const v = m.setPending(m.DEFAULT_SUPPLEMENT, 3);
  assert.equal(v.pending, 3);
  assert.equal(m.setPending(v, 3), v);
  assert.equal(m.aiCost(3, 7), "3 张 × 7 积分 = 21 积分");
  assert.equal(m.aiCost(0, 7), "不生成");
  assert.equal(m.licenceLine({ provider: "pixabay", author: "Lee", license: "Pixabay Content License" }), "Pixabay · 作者 Lee · Pixabay Content License");
  assert.deepEqual(m.splitSentences("第一句。第二句！\n第三句"), ["第一句。", "第二句！", "第三句"]);
});

test("panel copy avoids internal terms and new colours avoid blue/purple", () => {
  const panel = readFileSync("components/video-studio/supplement-materials-panel.tsx", "utf8");
  const visible = [...panel.matchAll(/>([^<>{}]*[一-鿿][^<>{}]*)</g)].map(match => match[1]).join(" ");
  for (const word of ["bundle", "planning", "contract", "task_id", "token", "provenance"]) assert.ok(!visible.includes(word), word);
  const css = readFileSync("components/video-studio/supplement-materials.module.css", "utf8") + panel;
  for (const hex of css.match(/#[0-9a-fA-F]{6}\b/g) ?? []) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    if (!d || d / max <= 0.25) continue;
    let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = (h * 60 + 360) % 360;
    assert.ok(h < 190 || h > 300, `${hex} is blue/purple`);
  }
});

test("MG is a whole-batch setting and the panel says so", () => {
  const panel = readFileSync("components/video-studio/supplement-materials-panel.tsx", "utf8");
  assert.match(panel, /MG 动效按整批设置：本批全部/);
  let v = m.toggleSource(m.setMode(m.DEFAULT_SUPPLEMENT, "custom"), "mg", true);
  assert.deepEqual(m.supplementForWorkItem(v, "w1").supplement, m.supplementForWorkItem(v, "w2").supplement);
});
