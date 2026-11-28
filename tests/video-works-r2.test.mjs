import assert from "node:assert/strict";
import test from "node:test";
import { filterPublished, itemGroup, mergeWorkCards, splitWorkCards, unfinishedState, workCounts } from "../features/video-studio/works.ts";

const item = (id, over = {}) => ({
  id, batch_id: "b1", position: 0, created_at: "2026-11-28T02:00:00Z", version: 1,
  publish_title: `标题${id}`, publish_body: "", script_text: "", generation_task_id: `g${id}`, editing_task_id: `e${id}`, cover_asset_id: null,
  stage: "done", status: "succeeded", ...over,
});
const edit = (id, created_at) => ({ task_id: id, project_id: "p", project_title: "旧作品", created_at, final: { url: `/v/${id}.mp4` } });

test("分组与后端 group_of 同一口径", () => {
  assert.equal(itemGroup({ stage: "talking", status: "running" }), "active");
  assert.equal(itemGroup({ stage: "editing", status: "queued" }), "active");
  assert.equal(itemGroup({ stage: "talking", status: "failed" }), "failed");
  assert.equal(itemGroup({ stage: "editing", status: "canceled" }), "failed");
  assert.equal(itemGroup({ stage: "done", status: "succeeded" }), "done");
  assert.equal(itemGroup({ stage: "finishing", status: "pending" }), "finishing");
  assert.equal(itemGroup({ stage: "talking", status: "succeeded" }), "other");
  assert.equal(itemGroup({ stage: "editing", status: "pending" }), "other");
});

test("B1：网格只放有可播放视频的；失败/未完成/生成中放到下方；删除的不出现", () => {
  const cards = mergeWorkCards([
    item("1"), item("2", { stage: "finishing", status: "pending" }), item("3", { stage: "talking", status: "failed", editing_task_id: null }),
    item("4", { stage: "talking", status: "running", editing_task_id: null }), item("5", { stage: "talking", status: "succeeded", editing_task_id: null }),
    item("6", { deleted_at: "2026-11-28T03:00:00Z" }),
  ], [], []);
  const split = splitWorkCards(cards);
  assert.deepEqual(split.grid.map(card => card.itemId).sort(), ["1", "2"]);
  assert.deepEqual(split.running.map(card => card.itemId), ["4"]);
  assert.deepEqual(split.unfinished.map(card => card.itemId).sort(), ["3", "5"]);
  assert.ok(!cards.some(card => card.itemId === "6"));
  assert.ok(!split.grid.some(card => card.progress?.label === "口播未完成"));
});

test("删除的条目引用的旧剪辑也不会以旧卡片冒出来", () => {
  const cards = mergeWorkCards([item("6", { deleted_at: "2026-11-28T03:00:00Z" })], [edit("e6", "2026-11-28T02:00:00Z")], []);
  assert.equal(cards.length, 0);
});

test("计数与网格一致：作品 / 待成片 / 生成中 / 未完成", () => {
  const cards = mergeWorkCards([item("1"), item("2", { stage: "finishing", status: "pending" })], [edit("x", "2026-11-20T00:00:00Z")], []);
  assert.deepEqual(workCounts({ total: 6, active: 1, failed: 2, done: 1, finishing: 1, other: 1 }, cards), { works: 2, finishing: 1, running: 1, unfinished: 3 });
  assert.deepEqual(workCounts(undefined, cards), { works: 2, finishing: 1, running: 0, unfinished: 0 });
});

test("B2：作品条目还没翻完时，比已加载最早一条还早的旧剪辑先不出", () => {
  const items = [item("1", { created_at: "2026-11-28T02:00:00Z" })];
  const edits = [edit("new", "2026-11-28T05:00:00Z"), edit("old", "2026-11-01T00:00:00Z")];
  assert.deepEqual(mergeWorkCards(items, edits, [], { itemsComplete: false }).map(card => card.key), ["edit:new", "item:1"]);
  assert.deepEqual(mergeWorkCards(items, edits, [], { itemsComplete: true }).map(card => card.key), ["edit:new", "item:1", "edit:old"]);
});

test("未完成区：失败的能重试和删，生成中的不能删", () => {
  assert.deepEqual(unfinishedState({ group: "failed", stage: "talking" }), { label: "口播没有生成成功", retry: "talking", step: "voice", deletable: true });
  assert.deepEqual(unfinishedState({ group: "failed", stage: "editing" }), { label: "剪辑没有成功", retry: "editing", step: "editing", deletable: true });
  assert.equal(unfinishedState({ group: "active", stage: "editing" }).deletable, false);
  assert.deepEqual(unfinishedState({ group: "other", stage: "talking" }), { label: "口播已完成，还没剪辑", retry: null, step: "editing", deletable: true });
});

test("C10：按已发布筛选", () => {
  const cards = mergeWorkCards([item("1", { published_at: "2026-11-28T04:00:00Z" }), item("2")], [], []);
  assert.deepEqual(filterPublished(cards, "published").map(card => card.itemId), ["1"]);
  assert.deepEqual(filterPublished(cards, "unpublished").map(card => card.itemId), ["2"]);
  assert.equal(filterPublished(cards, "all").length, 2);
});
