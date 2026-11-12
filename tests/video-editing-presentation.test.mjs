import assert from "node:assert/strict";
import test from "node:test";
import { editingMessage, editingTemplateName, editingFieldName, editingEffectName, editingMusicName, editingPlanningAction } from "../features/video-studio/editing-presentation.ts";

test("system diagnostics never replace the user-facing recovery message", () => {
  for (const message of ["EDITING_PLAN_CONTRACT_INVALID", "参数 /content/title 超限", "CX-G04 素材不满足", "任务 ca9230a8-3516-4520-9293-f6deec4d415b 未完成", "字节 869825b413ba62338d4f2b4690bf71d39ab6536be74333d5632c492fc7e3298f 已变化"]) {
    assert.equal(editingMessage(message, "请补充素材后重试"), "请补充素材后重试");
  }
  assert.equal(editingMessage("模型结果尚未确认，请勿重复提交以免重复计费。", "重试"), "模型结果尚未确认，请勿重复提交以免重复计费。");
  assert.equal(editingMessage("请上传 9:16 竖屏，至少 3 张图片。", "重试"), "请上传 9:16 竖屏，至少 3 张图片。");
});

test("pending and uncertain submissions never offer another paid action", () => {
  const prepared = { execution_available: true, available_template_group_count: 16 };
  assert.equal(editingPlanningAction(prepared), "generate");
  assert.equal(editingPlanningAction(prepared, { status: "running", call_state: "intent_saved" }), "wait");
  assert.equal(editingPlanningAction(prepared, { status: "failed", call_state: "intent_saved" }), "blocked");
  assert.equal(editingPlanningAction(prepared, { status: "completed", call_state: "response_saved" }), "preview");
  assert.equal(editingPlanningAction(prepared, { status: "failed", call_state: "response_saved" }), "prepare");
});

test("missing template conditions block billing and new inputs start with free preparation", () => {
  assert.equal(editingPlanningAction(), "prepare");
  assert.equal(editingPlanningAction({ execution_available: false }), "blocked");
  assert.equal(editingPlanningAction({ execution_available: true, available_template_group_count: 0 }), "blocked");
  assert.equal(editingPlanningAction({ execution_available: true, available_template_group_count: 1 }), "generate");
  assert.equal(editingPlanningAction({ execution_available: true, available_template_group_count: 16, template_style_blockers: ["需要三张图片"] }), "blocked");
});

test("editing controls describe the task while retaining native IDs as values", () => {
  assert.equal(editingTemplateName("azl-panels-v1", "阿哲多素材板式"), "杂志多格");
  assert.equal(editingFieldName("/content/rows/0/text", "强调文字 1"), "强调文字 1");
  assert.equal(editingEffectName("AH-S09 · 标题与说明", 0), "标题与说明");
  assert.equal(editingMusicName("bgm-b5035a43098ee293.wav", 2), "配乐 3");
  assert.equal(editingMusicName("Moonlit Road.mp3"), "Moonlit Road");
});
