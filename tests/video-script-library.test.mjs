import assert from "node:assert/strict";
import test from "node:test";
import {
  bodySummary, displayTitle, editChanged, hashtags, needsFill, pageState, scriptStats,
  titleWarning, toggle, togglePage, MAX_SELECTED,
} from "../features/video-studio/script-library-format.ts";

const A = "6f1c2a3e-0000-4000-8000-000000000001";
const B = "6f1c2a3e-0000-4000-8000-000000000002";
const C = "6f1c2a3e-0000-4000-8000-000000000003";

test("old entries without a title show the script's first sentence", () => {
  assert.equal(displayTitle({ publish_title: "", script: "冬天手干怎么办？试试这支。" }), "冬天手干怎么办");
  assert.equal(displayTitle({ publish_title: "  ", script: "" }), "未命名文案");
  assert.equal(displayTitle({ publish_title: "手干星人看过来", script: "x" }), "手干星人看过来");
  assert.ok(displayTitle({ publish_title: "", script: "一".repeat(40) }).endsWith("…"));
});

test("script length and estimated speaking time", () => {
  assert.deepEqual(scriptStats(""), { chars: 0, seconds: 0, label: "还没有口播稿" });
  const s = scriptStats("冬天手干，试试这支护手霜！".repeat(10));
  assert.equal(s.chars, 110);
  assert.equal(s.seconds, 23);
  assert.equal(s.label, "110 字 · 约 23 秒");
  assert.match(scriptStats("字".repeat(400)).label, /约 1 分 23 秒/);
});

test("body summary drops hashtags; tags are listed once", () => {
  const body = "冬天手一干就起皮，试了这支。\n\n#护手霜 #冬季护手 #护手霜";
  assert.equal(bodySummary(body), "冬天手一干就起皮，试了这支。");
  assert.deepEqual(hashtags(body), ["#护手霜", "#冬季护手"]);
});

test("title limits follow the platform", () => {
  const t = "冬天手干到起皮的姐妹一定要试试这支樱花香护手霜";
  assert.equal(titleWarning(t, "xiaohongshu"), "小红书标题最多 20 字，现在 23 字");
  assert.equal(titleWarning(t, "douyin"), "");
  assert.equal(titleWarning(t, ""), "");
});

test("multi-select: single toggle, select all on this page, keep other pages, at most 50", () => {
  assert.equal(Array.from({ length: 60 }, (_, i) => `id-${i}`).reduce(toggle, []).length, MAX_SELECTED);
  let selected = toggle([], A);
  selected = toggle(selected, B);
  assert.deepEqual(selected, [A, B]);
  assert.deepEqual(toggle(selected, A), [B]);
  const page = [A, C];
  assert.equal(pageState(selected, page), "some");
  selected = togglePage(selected, page);
  assert.deepEqual(selected, [A, B, C]);
  assert.equal(pageState(selected, page), "all");
  assert.deepEqual(togglePage(selected, page), [B]);
  assert.equal(pageState([], []), "none");
});

test("an edit is a change only when a part differs after trimming", () => {
  const entry = { publish_title: "标题", publish_body: "正文 #a #b #c", script: "口播。" };
  assert.equal(editChanged(entry, { publish_title: " 标题 ", publish_body: "正文 #a #b #c", script: "口播。\n" }), false);
  assert.equal(editChanged(entry, { ...entry, script: "改了。" }), true);
});

test("only an entry with just a script offers 补写标题和正文", () => {
  assert.equal(needsFill({ publish_title: "", publish_body: "", script: "冬天手干怎么办？" }), true);
  assert.equal(needsFill({ publish_title: "有标题", publish_body: "", script: "x" }), false);
  assert.equal(needsFill({ publish_title: "", publish_body: "", script: "  " }), false);
});
