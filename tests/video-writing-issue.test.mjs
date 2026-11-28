import assert from "node:assert/strict";
import test from "node:test";
import { writingIssueMessage } from "../features/video-studio/writing-issue.ts";

test("the failure names the replacement or sentence that was rejected", () => {
  assert.match(writingIssueMessage({ kind: "replacement_ungrounded", index: 0, text: "这个牌子的护手霜 → 樱花香护手霜（测试示例）" }), /第 1 处事实替换「这个牌子的护手霜 → 樱花香护手霜（测试示例）」/);
  assert.match(writingIssueMessage({ kind: "numeric_claim", index: 2, text: "一次买两瓶更划算。" }), /第 3 句「一次买两瓶更划算。」/);
  assert.match(writingIssueMessage({ kind: "section_order", index: 1, text: "论证一：包装观感与送礼适配" }), /「论证一：包装观感与送礼适配」这一段/);
});

test("old results without details keep the general message", () => {
  assert.equal(writingIssueMessage(undefined), "上次写稿未通过检查，请核对原文和事实后重试。");
  assert.equal(writingIssueMessage({ kind: "something_new", index: 0, text: "x" }), "上次写稿未通过检查，请核对原文和事实后重试。");
  assert.ok(writingIssueMessage({ kind: "numeric_claim", index: 0, text: "长".repeat(80) }).includes("…"));
});
