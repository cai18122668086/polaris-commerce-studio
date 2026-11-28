import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  allocate, allocationNote, allocationText, creditTotal, estimateMinutes, estimateText, groupByPlatform, lanesOf,
  parseCount, requestPlatforms, searchCount, stepCount, storeBody, togglePlatform, DEFAULT_COUNT, MAX_COUNT,
} from "../features/video-studio/auto-writing-plan.ts";

test("平台多选：按勾选顺序，至少留一个", () => {
  assert.deepEqual(togglePlatform(["douyin"], "xiaohongshu"), ["douyin", "xiaohongshu"]);
  assert.deepEqual(togglePlatform(["xiaohongshu"], "douyin"), ["xiaohongshu", "douyin"]);
  assert.deepEqual(togglePlatform(["douyin", "xiaohongshu"], "douyin"), ["xiaohongshu"]);
  assert.deepEqual(togglePlatform(["douyin"], "douyin"), ["douyin"]);
});

test("条数：1–10 的整数，默认 3，步进器不越界", () => {
  assert.equal(DEFAULT_COUNT, 3);
  assert.equal(parseCount("3"), 3);
  assert.equal(parseCount(" 10 "), 10);
  for (const bad of ["0", "11", "", "2.5", "-1", "三", "100"]) assert.equal(parseCount(bad), null, bad);
  assert.equal(stepCount(10, 1), MAX_COUNT);
  assert.equal(stepCount(1, -1), 1);
  assert.equal(stepCount(null, 1), 4);
});

test("分配预览与后端同一规则：平分，单数多出的给先勾选的平台", () => {
  const cases = [
    [1, ["douyin"], { douyin: 1 }, "抖音 1 条"],
    [3, ["douyin"], { douyin: 3 }, "抖音 3 条"],
    [10, ["xiaohongshu"], { xiaohongshu: 10 }, "小红书 10 条"],
    [1, ["douyin", "xiaohongshu"], { douyin: 1, xiaohongshu: 0 }, "抖音 1 条 · 小红书 0 条"],
    [2, ["douyin", "xiaohongshu"], { douyin: 1, xiaohongshu: 1 }, "抖音 1 条 · 小红书 1 条"],
    [3, ["douyin", "xiaohongshu"], { douyin: 2, xiaohongshu: 1 }, "抖音 2 条 · 小红书 1 条"],
    [3, ["xiaohongshu", "douyin"], { xiaohongshu: 2, douyin: 1 }, "小红书 2 条 · 抖音 1 条"],
    [10, ["douyin", "xiaohongshu"], { douyin: 5, xiaohongshu: 5 }, "抖音 5 条 · 小红书 5 条"],
  ];
  for (const [count, platforms, split, text] of cases) {
    assert.deepEqual(allocate(count, platforms), split);
    assert.equal(allocationText(count, platforms), text);
    assert.equal(Object.values(split).reduce((a, b) => a + b, 0), count);
  }
  assert.match(allocationNote(1, ["douyin", "xiaohongshu"]), /只给先勾选的抖音写/);
  assert.match(allocationNote(3, ["xiaohongshu", "douyin"]), /多出的 1 条给先勾选的小红书/);
  assert.equal(allocationNote(4, ["douyin", "xiaohongshu"]), "");
  assert.equal(allocationNote(3, ["douyin"]), "");
});

test("预计耗时：单平台 3 条与以前一样 3–5 分钟，条数多了变长", () => {
  assert.equal(estimateText(3, ["douyin"]), "大约 3–5 分钟");
  assert.deepEqual(estimateMinutes(1, ["douyin"]), [3, 5]);
  assert.deepEqual(estimateMinutes(6, ["douyin", "xiaohongshu"]), [3, 5]);
  assert.deepEqual(estimateMinutes(10, ["douyin"]), [6, 11]);
  assert.ok(estimateMinutes(10, ["douyin"])[1] > estimateMinutes(4, ["douyin"])[1]);
});

test("积分：价格为空不出数（页面显示灰度不扣），有价格按搜索次数和条数算", () => {
  assert.equal(creditTotal(3, 1, { search: null, write: null }), null);
  assert.equal(creditTotal(3, 1, { search: 10, write: undefined }), null);
  assert.equal(creditTotal(3, 1, { search: 10, write: 2 }), 10 + 8 + 6);
  assert.equal(searchCount(3, ["douyin", "xiaohongshu"], "护手霜"), 2);
  assert.equal(searchCount(1, ["douyin", "xiaohongshu"], "护手霜"), 1);
  assert.equal(searchCount(3, ["douyin", "xiaohongshu"], "https://v.douyin.com/x/"), 1);
});

test("结果按平台分组；旧运行没有 platform 时算作请求的平台", () => {
  const drafts = [
    { key: "douyin-v1", platform: "douyin" }, { key: "douyin-v2", platform: "douyin" }, { key: "xiaohongshu-v1", platform: "xiaohongshu" },
  ];
  const groups = groupByPlatform(drafts, ["douyin", "xiaohongshu"]);
  assert.deepEqual(groups.map(g => [g.platform, g.drafts.length]), [["douyin", 2], ["xiaohongshu", 1]]);
  const old = groupByPlatform([{ key: "v1" }, { key: "v2" }, { key: "v3" }], requestPlatforms({ platform: "xiaohongshu" }));
  assert.deepEqual(old.map(g => [g.platform, g.drafts.length]), [["xiaohongshu", 3]]);
  assert.deepEqual(requestPlatforms({ platform: "douyin", platforms: ["xiaohongshu", "douyin"] }), ["xiaohongshu", "douyin"]);
  assert.deepEqual(requestPlatforms(undefined), ["douyin"]);
});

test("对标线：两个平台各一条，否则就是结果本身", () => {
  const single = { search_task_id: "s", benchmarks: [{ reference_id: "r", platform_id: "p", reason: "" }] };
  assert.deepEqual(lanesOf(single).map(l => [l.platform, l.search_task_id]), [[null, "s"]]);
  const two = { lanes: { douyin: { search_task_id: "a", status: "completed" }, xiaohongshu: { search_task_id: "b", status: "failed", message: "没有找到" } } };
  assert.deepEqual(lanesOf(two).map(l => [l.platform, l.search_task_id, l.status]), [["douyin", "a", "completed"], ["xiaohongshu", "b", "failed"]]);
});

test("旧版本「存入文案库」：按文稿 id 存、带平台，页面上有按钮并保留补写", () => {
  const body = storeBody({ document_id: "doc-1", platform: "xiaohongshu" }, { publish_title: " 标题 ", publish_body: "", script: " 口播稿。 " }, "req-1");
  assert.deepEqual(body, { request_id: "req-1", writing_document_id: "doc-1", source: "auto_writing", platform: "xiaohongshu", publish_title: "标题", publish_body: "", script: "口播稿。" });
  const page = readFileSync(new URL("../components/video-studio/auto-writing.tsx", import.meta.url), "utf8");
  assert.match(page, /\{!item && <button[^>]*onClick=\{\(\) => void store\(\)\}>\{storing \? "正在存入…" : "存入文案库"\}<\/button>\}/);
  assert.match(page, /legacy=\{legacy \? <>/); // 补写标题和正文仍在
  assert.match(page, /storeRequests\.current\.get\(d\.key\) \|\| crypto\.randomUUID\(\)/); // 同一版重复点击同一个请求
  assert.match(page, /platform: platforms\[0\], platforms, count/); // 旧字段 platform 照发
  assert.match(page, /\{AUTO_PLATFORM_LABEL\[group\.platform\]\} · \{group\.drafts\.length\} 条/);
});
