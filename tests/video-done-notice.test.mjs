import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/done-notice.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { busyPhase, justFinished, noticeTitle } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);
const b = (id, ...items) => ({ id, items: items.map(([stage, status]) => ({ stage, status })) });

test("批次在跑什么", () => {
  assert.equal(busyPhase(b("x", ["talking", "running"], ["talking", "succeeded"])), "talking");
  assert.equal(busyPhase(b("x", ["editing", "queued"], ["finishing", "pending"])), "editing");
  assert.equal(busyPhase(b("x", ["editing", "pending"], ["finishing", "pending"])), null);
  assert.equal(busyPhase(b("x", ["talking", "failed"], ["done", "succeeded"])), null);
});

test("之前在跑、现在跑完才提醒；第一次看到的不算", () => {
  const first = justFinished({}, [b("a", ["talking", "running"]), b("c", ["done", "succeeded"])]);
  assert.deepEqual(first.finished, []);
  const second = justFinished(first.phases, [b("a", ["talking", "succeeded"]), b("c", ["done", "succeeded"])]);
  assert.deepEqual(second.finished, ["talking"]);
  const editing = justFinished({ a: "editing" }, [b("a", ["finishing", "pending"])]);
  assert.deepEqual(editing.finished, ["editing"]);
  // 口播跑完直接进剪辑（有自动剪的情况）也算口播完成
  assert.deepEqual(justFinished({ a: "talking" }, [b("a", ["editing", "running"])]).finished, ["talking"]);
  assert.deepEqual(justFinished({ a: "editing" }, [b("a", ["editing", "running"])]).finished, []);
});

test("标签标题", () => {
  assert.equal(noticeTitle(["talking"], "视频空间 - 极光商绘"), "（口播已完成）视频空间 - 极光商绘");
  assert.equal(noticeTitle(["editing"], "（口播已完成）视频空间"), "（剪辑已完成）视频空间");
  assert.equal(noticeTitle(["editing", "talking"], "视频空间"), "（一批视频已完成）视频空间");
});
