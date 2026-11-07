import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/generation-progress.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { generationProgress, elapsedLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

test("long waits keep the original task and backup stages stay in video generation", () => {
  const slow = generationProgress({ status: "running", kind: "lipsync", stage: "lipsync_generating", lipsync_routing: { long_wait: true } });
  assert.equal(slow.title, "生成耗时较长，继续查询原任务");
  assert.equal(slow.active, true);
  assert.equal(slow.step, 2);
  for (const stage of ["backup_avatar_preparing", "backup_lipsync_submitting", "backup_lipsync_generating"]) {
    const backup = generationProgress({ status: "running", kind: "lipsync", stage });
    assert.equal(backup.step, 2);
    assert.match(backup.title, /备用/);
  }
});

test("video stage feedback follows real stages and never claims early completion", () => {
  const job = { status: "running", kind: "lipsync" };
  const stages = ["tts_submitting", "preparing_forward_template", "lipsync_generating", "downloading_video"];
  const progress = stages.map(stage => generationProgress({ ...job, stage }));
  assert.deepEqual(progress.map(state => state.step), [0, 1, 2, 3]);
  assert.ok(progress.every(state => state.active && !state.done && state.width < 100));
  assert.equal(generationProgress({ ...job, stage: "completed", status: "completed" }).width, 100);
});

test("failed and uncertain jobs stop motion; avatar review is separate from completion", () => {
  for (const status of ["failed", "unknown", "rejected"]) {
    const state = generationProgress({ status, kind: "lipsync", stage: "lipsync_generating" });
    assert.equal(state.active, false);
    assert.equal(state.stopped, true);
  }
  const review = generationProgress({ status: "awaiting_review", kind: "h3_template", stage: "awaiting_review" });
  assert.equal(review.review, true);
  assert.equal(review.done, false);
  assert.equal(elapsedLabel(125), "2 分 5 秒");
});

test("a polling timeout waits for the original result without implying failure or completion", () => {
  for (const [kind, stage, step] of [["lipsync", "lipsync_generating", 2], ["h3_template", "h3_generating", 1]]) {
    const state = generationProgress({ status: "awaiting_resume", kind, stage });
    assert.equal(state.waiting, true);
    assert.equal(state.waitingForResult, true);
    assert.equal(state.stopped, false);
    assert.equal(state.active, false);
    assert.equal(state.done, false);
    assert.equal(state.step, step);
    assert.equal(state.title, "生成耗时较长，等待结果");
    assert.equal(state.resumeLabel, "继续查询结果");
    assert.ok(state.width < 100);
  }
});

test("unfinished media preparation retains a processing action instead of a result query", () => {
  const state = generationProgress({ status: "awaiting_resume", kind: "lipsync", stage: "uploading_audio" });
  assert.equal(state.waiting, true);
  assert.equal(state.waitingForResult, false);
  assert.equal(state.resumeLabel, "继续处理");
  const failed = generationProgress({ status: "failed", kind: "lipsync", stage: "lipsync_generating" });
  assert.equal(failed.waitingForResult, false);
  assert.equal(failed.stopped, true);
});

const uiCompiled = await build({
  stdin: { contents: `
    import { createElement } from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    import { GenerationProgress, GenerationImageStatus } from "./components/video-studio/generation-progress";
    import { GenerationWorkCard } from "./components/video-studio/generation-work-card";
    export function render(job, resuming = false) {
      return renderToStaticMarkup(createElement("div", null,
        createElement(GenerationProgress, { job }),
        createElement(GenerationImageStatus, { job }),
        createElement(GenerationWorkCard, { job, avatar: { name: "测试形象" }, resuming, onPreview() {}, onResume() {} })
      ));
    }
  `, resolveDir: process.cwd(), loader: "ts" },
  bundle: true, write: false, outfile: "progress-test.mjs", format: "esm", platform: "node", loader: { ".css": "empty", ".module.css": "empty" }, logLevel: "silent",
  banner: { js: 'import { createRequire } from "node:module"; const require = createRequire(process.cwd() + "/package.json");' },
  packages: "bundle", define: { "process.env.NODE_ENV": '"production"' },
});
const { render } = await import(`data:text/javascript;base64,${Buffer.from(uiCompiled.outputFiles[0].text).toString("base64")}`);
const waitingJob = { id: "original-task", kind: "lipsync", status: "awaiting_resume", stage: "lipsync_generating", can_resume: true, created_at: "2026-11-06T09:42:36Z" };

test("waiting UI uses a clock, keeps the current step, and describes querying the original task", () => {
  const html = render(waitingJob);
  assert.match(html, /data-state="waiting"/);
  assert.match(html, /lucide-clock/);
  assert.doesNotMatch(html, /lucide-circle-alert/);
  assert.match(html, /data-state="current"/);
  assert.match(html, /暂未收到生成结果/);
  assert.match(html, /等待生成结果/);
  assert.match(html, /继续查询结果/);
  assert.doesNotMatch(html, /已保存到你的账号/);
});

test("query actions disable during the request and real failures retain their warning", () => {
  assert.match(render(waitingJob, true), /<button[^>]*disabled=""[^>]*>正在查询…<\/button>/);
  const failed = render({ ...waitingJob, status: "failed", can_resume: false });
  assert.match(failed, /data-state="stopped"/);
  assert.match(failed, /lucide-circle-alert/);
  assert.doesNotMatch(failed, /继续查询结果/);
});
