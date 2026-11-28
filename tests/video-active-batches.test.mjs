import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

const compiled = await build({ entryPoints: ["features/video-studio/active-batches.ts"], bundle: true, write: false, format: "esm", platform: "node", logLevel: "silent" });
const { activeBatchRow, activeBatchRows, batchDate } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`);

const now = new Date("2026-11-28T08:00:00Z");
const batch = (id, items, created_at = "2026-11-28T06:05:00Z") => ({ id, created_at, items: items.map(([stage, status]) => ({ stage, status })) });

test("停在口播：口播 x/N，继续去口播", () => {
  const row = activeBatchRow(batch("a", [["talking", "running"], ["talking", "succeeded"], ["talking", "queued"]]), now);
  assert.deepEqual(row, { id: "a", date: "今天 14:05", total: 3, where: "口播 1/3", detail: "口播生成中", step: "voice" });
});

test("停在剪辑：口播都好了还没剪 → 待剪辑；剪辑中有剪完的 → 可以先去成片", () => {
  assert.equal(activeBatchRow(batch("b", [["talking", "succeeded"], ["talking", "succeeded"], ["editing", "pending"]]), now).where, "待剪辑 3 条");
  assert.equal(activeBatchRow(batch("b", [["talking", "succeeded"], ["editing", "pending"]]), now).step, "editing");
  const running = activeBatchRow(batch("c", [["editing", "running"], ["editing", "queued"], ["finishing", "pending"]]), now);
  assert.equal(running.where, "剪辑 1/3");
  assert.equal(running.detail, "剪辑中 · 1 条可以先去成片");
  assert.equal(running.step, "finish");
  assert.equal(activeBatchRow(batch("c", [["editing", "running"], ["editing", "queued"]]), now).step, "editing");
});

test("停在成片：待成片 N 条，继续去成片", () => {
  const row = activeBatchRow(batch("d", [["finishing", "pending"], ["finishing", "pending"], ["done", "succeeded"]]), now);
  assert.equal(row.where, "待成片 2 条");
  assert.equal(row.detail, "已完成 1 条");
  assert.equal(row.step, "finish");
});

test("全部做完、空批次、全部删除的不显示", () => {
  assert.equal(activeBatchRow(batch("e", [["done", "succeeded"], ["done", "succeeded"]]), now), null);
  assert.equal(activeBatchRow(batch("f", []), now), null);
  assert.equal(activeBatchRow({ id: "g", created_at: now.toISOString(), items: [{ stage: "talking", status: "failed", deleted_at: "2026-11-28T07:00:00Z" }] }, now), null);
});

test("只剩失败的：写清几条未完成，回到失败的那一步", () => {
  const row = activeBatchRow(batch("h", [["talking", "failed"], ["done", "succeeded"]]), now);
  assert.equal(row.where, "1 条未完成");
  assert.equal(row.step, "voice");
  const mixed = activeBatchRow(batch("i", [["talking", "failed"], ["finishing", "pending"]]), now);
  assert.equal(mixed.where, "待成片 1 条");
  assert.equal(mixed.detail, "1 条未完成");
});

test("多批：新的在前、只留进行中的、最多 3 行", () => {
  const rows = activeBatchRows([
    batch("1", [["talking", "running"]]), batch("2", [["done", "succeeded"]]), batch("3", [["finishing", "pending"]]),
    batch("4", [["editing", "pending"]]), batch("5", [["editing", "running"]]),
  ], 3, now);
  assert.deepEqual(rows.map(row => row.id), ["1", "3", "4"]);
});

test("日期按北京时间，跨天写月日", () => {
  assert.equal(batchDate("2026-11-27T17:53:09Z", now), "11月28日 01:53".replace("11月28日", "今天"));
  assert.equal(batchDate("2026-11-26T03:00:00Z", now), "11月26日 11:00");
  assert.equal(batchDate("bad", now), "");
});
