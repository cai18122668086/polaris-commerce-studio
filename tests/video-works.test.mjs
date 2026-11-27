import assert from "node:assert/strict";
import test from "node:test";
import {
  firstSentence, countChars, defaultCoverText, splitTopics, itemProgress, itemCard, editCard, talkCard,
  mergeWorkCards, filterWorkCards, batchOptions, neighbour, TITLE_LIMITS,
} from "../features/video-studio/works.ts";

const item = (over = {}) => ({
  id: "i1", batch_id: "b1", position: 0, created_at: "2026-11-28T02:00:00Z", version: 3,
  publish_title: "夏天必备的冰丝凉席", publish_body: "睡得凉快 #好物推荐", script_text: "今天推荐一款凉席。它很凉快。",
  generation_task_id: "g1", editing_task_id: "e1", cover_asset_id: "c1", stage: "done", status: "succeeded", ...over,
});

test("old works without a title fall back to the first sentence of the script", () => {
  assert.equal(firstSentence("今天推荐一款凉席。它很凉快。"), "今天推荐一款凉席");
  assert.equal(firstSentence("  \n "), "");
  assert.equal(firstSentence("一".repeat(40), 28), "一".repeat(28) + "…");
  const card = itemCard(item({ publish_title: "", cover_asset_id: null }));
  assert.equal(card.title, "今天推荐一款凉席");
  assert.equal(card.titleIsFallback, true);
  assert.equal(card.coverId, null);
  assert.equal(itemCard(item({ publish_title: "", script_text: "" })).title, "未命名作品");
  const talk = talkCard({ id: "g9", kind: "lipsync", status: "completed", created_at: "2026-11-01T00:00:00Z", video_url: "/v", snapshot: { draft: { name: "未命名视频", text: "大家好，我是小林。" } } });
  assert.equal(talk.title, "大家好，我是小林");
  assert.equal(editCard({ task_id: "e9", project_id: "p", project_title: "未命名项目", created_at: "2026-11-01T00:00:00Z", final: { url: "/f" } }).title, "未命名作品");
});

test("progress badges follow the work item stage", () => {
  assert.deepEqual(itemProgress({ stage: "talking", status: "running" }), { label: "口播生成中", tone: "running" });
  assert.deepEqual(itemProgress({ stage: "editing", status: "queued" }), { label: "剪辑中", tone: "running" });
  assert.deepEqual(itemProgress({ stage: "editing", status: "failed" }), { label: "剪辑未完成", tone: "failed" });
  assert.deepEqual(itemProgress({ stage: "finishing", status: "pending" }), { label: "待成片", tone: "waiting" });
  assert.equal(itemProgress({ stage: "done", status: "succeeded" }), null);
});

test("cover text drops topics and emoji; counts are per character", () => {
  assert.equal(defaultCoverText("夏天必备😀 冰丝凉席 #好物推荐 #夏天"), "夏天必备 冰丝凉席");
  assert.equal(countChars("凉席😀"), 3);
  assert.equal(TITLE_LIMITS.xiaohongshu, 20);
  assert.deepEqual(splitTopics("睡得凉快 #好物推荐 #夏天"), [
    { text: "睡得凉快 ", topic: false }, { text: "#好物推荐", topic: true }, { text: " ", topic: false }, { text: "#夏天", topic: true },
  ]);
});

test("the grid merges items with legacy works without duplicates, newest first", () => {
  const items = [item(), item({ id: "i2", created_at: "2026-11-28T03:00:00Z", editing_task_id: null, generation_task_id: "g2", stage: "editing", status: "running", cover_asset_id: null })];
  const edits = [
    { task_id: "e1", project_id: "p1", project_title: "旧项目", created_at: "2026-11-27T00:00:00Z", final: { url: "/e1" } },
    { task_id: "e5", project_id: "p5", project_title: "老剪辑", created_at: "2026-11-20T00:00:00Z", final: { url: "/e5" } },
  ];
  const jobs = [
    { id: "g2", kind: "lipsync", status: "completed", created_at: "2026-11-28T01:00:00Z" },
    { id: "g7", kind: "lipsync", status: "running", created_at: "2026-11-28T04:00:00Z", snapshot: { draft: { text: "新的一条口播。" } } },
    { id: "h1", kind: "h3_template", status: "completed", created_at: "2026-11-28T05:00:00Z" },
  ];
  const cards = mergeWorkCards(items, edits, jobs);
  assert.deepEqual(cards.map(card => card.key), ["talk:g7", "item:i2", "item:i1", "edit:e5"]);
  assert.deepEqual(cards[0].progress, { label: "口播生成中", tone: "running" });
  assert.equal(cards.at(-1).videoUrl, "/e5");
});

test("filters by batch, time and keyword; batch options list each batch once", () => {
  const cards = mergeWorkCards([item(), item({ id: "i2", batch_id: "b2", created_at: "2026-11-01T00:00:00Z", publish_title: "防晒霜测评" })], [], []);
  const now = Date.parse("2026-11-28T12:00:00Z");
  assert.deepEqual(filterWorkCards(cards, { batch: "b2" }).map(c => c.itemId), ["i2"]);
  assert.deepEqual(filterWorkCards(cards, { range: "7d", now }).map(c => c.itemId), ["i1"]);
  assert.deepEqual(filterWorkCards(cards, { keyword: "防晒" }).map(c => c.itemId), ["i2"]);
  assert.deepEqual(batchOptions(cards).map(b => [b.id, b.count]), [["b1", 1], ["b2", 1]]);
});

test("arrow keys move between neighbours and stop at the ends", () => {
  const cards = mergeWorkCards([item(), item({ id: "i2", created_at: "2026-11-27T00:00:00Z" })], [], []);
  assert.equal(neighbour(cards, "item:i1", 1).key, "item:i2");
  assert.equal(neighbour(cards, "item:i2", 1), null);
  assert.equal(neighbour(cards, "item:i1", -1), null);
});

test("items still in 口播 never ask for a video; finished ones do", () => {
  assert.equal(itemCard(item({ stage: "talking", status: "running" })).hasVideo, false);
  assert.equal(itemCard(item({ stage: "talking", status: "succeeded" })).hasVideo, true);
  assert.equal(itemCard(item({ stage: "editing", status: "running" })).hasVideo, true);
  assert.equal(talkCard({ id: "g", kind: "lipsync", status: "running", created_at: "2026-11-28T00:00:00Z" }).hasVideo, false);
});

import { posterPath } from "../features/video-studio/works.ts";

test("works without a cover get a server-cut poster whenever a video exists", () => {
  const ws = "ws1";
  assert.equal(posterPath(ws, itemCard(item({ cover_asset_id: null }))), "/api/v1/video-studio/workspaces/ws1/work-posters/editing/e1");
  assert.equal(posterPath(ws, itemCard(item({ editing_task_id: null, stage: "editing", status: "pending" }))), "/api/v1/video-studio/workspaces/ws1/work-posters/generation/g1");
  assert.equal(posterPath(ws, itemCard(item({ editing_task_id: null, stage: "talking", status: "running" }))), null);
  assert.equal(posterPath(ws, editCard({ task_id: "e9", project_id: "p", project_title: "x", created_at: "2026-11-01T00:00:00Z", final: { url: "/f" } })), "/api/v1/video-studio/workspaces/ws1/work-posters/editing/e9");
  assert.equal(posterPath(ws, talkCard({ id: "g7", kind: "lipsync", status: "running", created_at: "2026-11-28T00:00:00Z" })), null);
});
