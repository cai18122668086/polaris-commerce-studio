import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/viral-facts.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { BASE, asked, buildFacts, slotKey } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const slots = [
  { id: "product", category: "product", label: "产品名", question: "你的产品叫什么？" },
  { id: "pain_result", category: "story", label: "痛点后果", question: "用错会怎样？" },
];

test("slot ids are what the writer sees; only a clash with a fixed field is prefixed", () => {
  assert.equal(slotKey("pain_result"), "pain_result");
  assert.equal(slotKey("product"), "slot-product");
});

test("a fixed question the teardown already asks is not asked twice", () => {
  const product = BASE.find(item => item.id === "product");
  const me = BASE.find(item => item.id === "me");
  assert.equal(asked(slots, product), true);
  assert.equal(asked(slots, me), false);
  assert.equal(asked([{ label: "我的身份" }], me), true);
});

test("only answered facts are usable; blanks stay unknown with no value", () => {
  const facts = buildFacts(slots, { "slot-product": " 小熊护手霜 ", me: "美甲师", pain_result: "" }, "竞品A\n\n竞品A\n第一", ["price"]);
  const byId = Object.fromEntries(facts.facts.map(f => [f.id, f]));
  assert.deepEqual(Object.keys(byId), ["slot-product", "pain_result", "me", "points", "story"]);
  assert.equal(byId["slot-product"].value, "小熊护手霜");
  assert.equal(byId["slot-product"].status, "user_declared");
  assert.equal(byId.pain_result.status, "unknown");
  assert.equal(byId.pain_result.value, null);
  assert.deepEqual(facts.forbidden_terms, ["竞品A", "第一"]);
  assert.deepEqual(facts.restricted_claims, ["price"]);
});
