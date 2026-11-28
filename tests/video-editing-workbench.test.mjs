import assert from "node:assert/strict";
import test from "node:test";
import { changeSummary, revisingTask, segmentRows } from "../features/video-studio/editing-workbench.ts";

const beats = [
  { id: "b1", text: "先说结论", group_id: "T001", source_only_available: true },
  { id: "b2", text: "三个卖点", group_id: "T002", source_only_available: true, dependency_blocker: "原库字体无法核验" },
  { id: "b3", text: "结尾", group_id: "Z-M00", source_only_available: false },
];
const none = { music: "keep", musicTrackId: "", segments: [], effects: [], highlights: [], images: [] };

test("rows number segments and surface unresolved dependency problems to the user", () => {
  const rows = segmentRows(beats, none, new Set(["b1"]));
  assert.deepEqual(rows.map(r => r.index), [1, 2, 3]);
  assert.equal(rows[1].blocker, "原库字体无法核验");
  assert.equal(rows[0].layoutFailed, true);
  assert.equal(rows[2].kept, true);
  assert.deepEqual(rows[0].changes, []);
});

test("keeping the source or swapping the effect clears the blocker", () => {
  assert.equal(segmentRows(beats, { ...none, segments: ["b2"] })[1].blocker, undefined);
  assert.equal(segmentRows(beats, { ...none, effects: [{ beat_id: "b2", group_id: "T009" }] })[1].blocker, undefined);
});

test("a kept segment reports only 保留原画面, other edits list each kind", () => {
  const rows = segmentRows(beats, { ...none, segments: ["b1"], effects: [{ beat_id: "b1", group_id: "x" }, { beat_id: "b2", group_id: "y" }], highlights: [{ beat_id: "b2" }], images: [{ beat_id: "b2" }] });
  assert.deepEqual(rows[0].changes, ["保留原画面"]);
  assert.deepEqual(rows[1].changes, ["换动效", "改强调词", "换配图"]);
});

test("summary counts changed segments and the music tier", () => {
  assert.equal(changeSummary(beats, none), "");
  assert.equal(changeSummary(beats, { ...none, segments: ["b1"], music: "lower" }), "已调整 1 段 · 配乐 · 轻");
  assert.equal(changeSummary(beats, { ...none, music: "off", musicTrackId: "bgm-0123456789abcdef" }), "关闭配乐");
  assert.equal(changeSummary(beats, { ...none, music: "raise", musicTrackId: "bgm-0123456789abcdef" }), "配乐 · 明显 · 更换配乐曲目");
});

test("the subtitle entry targets exactly the version being revised", () => {
  const tasks = [{ id: "a", options: { mode: "native_plan" } }, { id: "b", options: { mode: "suite_plan" } }];
  assert.deepEqual(revisingTask(tasks, { taskId: "b" }), { id: "b", options: { mode: "suite_plan" } });
  assert.equal(revisingTask(tasks, { taskId: "gone" }), undefined);
  assert.equal(revisingTask(tasks, undefined), undefined);
});

test("a muted segment shows as changed but keeps its motion", () => {
  const beats = [{ id: "a", text: "开场", group_id: "T001", source_only_available: true, sound_mute_available: true }];
  const base = { music: "keep", musicTrackId: "", segments: [], effects: [], highlights: [], images: [] };
  const [row] = segmentRows(beats, { ...base, muted: ["a"] });
  assert.deepEqual(row.changes, ["关音效"]);
  assert.equal(row.kept, false);
  const [kept] = segmentRows(beats, { ...base, segments: ["a"], muted: ["a"] });
  assert.deepEqual(kept.changes, ["保留原画面"]);
  assert.deepEqual(segmentRows(beats, base)[0].changes, []);
});
