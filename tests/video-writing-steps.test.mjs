import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/writing-steps.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { WRITING_STEPS, assistantModeFor, completedSteps, suggestedStep } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const empty = { references: 0, productFacts: "", draftText: "", savedTexts: [] };

test("five steps in the agreed order", () => {
  assert.deepEqual(WRITING_STEPS.map(step => step.label), ["找对标", "提取拆解", "产品事实", "生成改写", "定稿"]);
  assert.deepEqual(WRITING_STEPS.map(step => step.index), [1, 2, 3, 4, 5]);
});

test("each step drives the matching assistant tool", () => {
  assert.equal(assistantModeFor("benchmark"), "benchmark");
  assert.equal(assistantModeFor("analyze"), "extract");
  assert.equal(assistantModeFor("rewrite"), "rewrite");
  assert.equal(assistantModeFor("rewrite", true), "create");
  assert.equal(assistantModeFor("facts"), undefined);
  assert.equal(assistantModeFor("final"), undefined);
});

test("a new project starts at benchmark search", () => {
  assert.equal(completedSteps(empty).size, 0);
  assert.equal(suggestedStep(empty), "benchmark");
});

test("a saved reference marks search and analysis, facts come next", () => {
  const progress = { ...empty, references: 1 };
  assert.deepEqual([...completedSteps(progress)].sort(), ["analyze", "benchmark"]);
  assert.equal(suggestedStep(progress), "facts");
});

test("whitespace-only facts do not count", () => {
  assert.equal(completedSteps({ ...empty, productFacts: "  \n" }).has("facts"), false);
});

test("a draft lands on the final step; final is done only once that exact text is in the library", () => {
  const progress = { references: 1, productFacts: "品牌：极光", draftText: "定稿文案", savedTexts: [] };
  assert.equal(suggestedStep(progress), "final");
  assert.equal(completedSteps(progress).has("final"), false);
  assert.equal(completedSteps({ ...progress, savedTexts: ["旧文案"] }).has("final"), false);
  assert.equal(completedSteps({ ...progress, savedTexts: ["定稿文案"] }).has("final"), true);
});

test("an original draft without references still reaches the final step", () => {
  const progress = { ...empty, draftText: "原创文案" };
  assert.equal(suggestedStep(progress), "final");
  assert.equal(completedSteps(progress).has("benchmark"), false);
});
