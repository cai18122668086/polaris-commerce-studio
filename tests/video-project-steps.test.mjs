import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/project-steps.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { projectSteps, voiceStage, editingStage } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const states = steps => steps.map(step => `${step.label}:${step.state}${step.note ? "/" + step.note : ""}`).join(" ");

test("a new project starts on the writing step with nothing done", () => {
  assert.equal(states(projectSteps({ screen: "writing", hasScript: false, voice: "none", editing: "none" })), "文案:current 口播:todo 剪辑:todo 成片:todo");
});

test("the open page is current while earlier steps show done", () => {
  assert.equal(states(projectSteps({ screen: "editing", hasScript: true, voice: "done", editing: "none" })), "文案:done 口播:done 剪辑:current 成片:todo");
});

test("a preview waiting for confirmation marks the final step as pending", () => {
  assert.equal(states(projectSteps({ screen: "create", hasScript: true, voice: "done", editing: "review" })), "文案:done 口播:current 剪辑:done 成片:todo/待确认");
});

test("voice stage only counts lip-sync jobs of the same project", () => {
  const jobs = [
    { kind: "lipsync", project_id: "other", status: "completed" },
    { kind: "h3_template", project_id: "p1", status: "completed" },
    { kind: "lipsync", project_id: "p1", status: "running" },
  ];
  assert.equal(voiceStage(jobs, "p1"), "running");
  assert.equal(voiceStage([...jobs, { kind: "lipsync", project_id: "p1", status: "completed" }], "p1"), "done");
  assert.equal(voiceStage(jobs, "p2"), "none");
});

test("transcript preparation is not an edit; a final artifact means 成片", () => {
  assert.equal(editingStage([{ status: "completed", options: { mode: "transcript" }, artifacts: [{ role: "transcript" }] }]), "none");
  assert.equal(editingStage([{ status: "running", options: { mode: "suite_plan" }, artifacts: [] }]), "running");
  assert.equal(editingStage([{ status: "awaiting_review", options: { mode: "suite_plan" }, artifacts: [{ role: "preview" }] }]), "review");
  assert.equal(editingStage([{ status: "completed", options: { mode: "native_plan" }, artifacts: [{ role: "final" }] }]), "done");
});

const { batchSteps } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("a batch shows how many of its items are past each step", () => {
  const items = [
    { stage: "finishing", status: "pending" },
    { stage: "editing", status: "running" },
    { stage: "editing", status: "succeeded" },
  ];
  assert.equal(states(batchSteps({ screen: "editing", items })), "文案:done 口播:done 剪辑:current/2/3 成片:todo/待成片");
  assert.equal(states(batchSteps({ screen: "finish", items: items.map(() => ({ stage: "done", status: "succeeded" })) })), "文案:done 口播:done 剪辑:done 成片:current");
  assert.equal(states(batchSteps({ screen: "create", items: [{ stage: "talking", status: "failed" }, { stage: "talking", status: "running" }] })), "文案:done 口播:current/1 条未完成 剪辑:todo 成片:todo");
});

test("the 成片 step opens the finish page", () => {
  const final = projectSteps({ screen: "editing", hasScript: true, voice: "done", editing: "done" }).at(-1);
  assert.equal(final.screen, "finish");
});
