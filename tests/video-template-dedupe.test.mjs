import assert from "node:assert/strict";
import test from "node:test";
import { isTemplateListed, templateEntry } from "../features/video-studio/editing-presentation.ts";

// 11-28 v3 模板评估：人物出镜里不再有肉眼看不出区别的两个模板。
test("人物出镜 keeps one of each look-alike pair", () => {
  assert.equal(isTemplateListed("bihuo-47-v1"), false); // = 居中字幕
  for (const id of ["presenter-openings-v1", "bihuo-34-v1", "bihuo-36-v1", "bihuo-40-v1", "bihuo-08-v1"]) {
    assert.equal(isTemplateListed(id), true, id);
    assert.equal(templateEntry(id)?.[0], "人物出镜", id);
  }
  // Hidden templates stay renderable and named for projects that already use them.
  assert.equal(templateEntry("bihuo-47-v1")?.[1], "星光商务");
});

test("深青标题 stays hidden until its caption contrast is fixed", () => {
  assert.equal(isTemplateListed("bihuo-24-v1"), false);
  assert.equal(templateEntry("bihuo-24-v1")?.[1], "深青标题");
});

test("快讯直播 stays hidden until long captions can wrap", () => {
  assert.equal(isTemplateListed("bihuo-23-v1"), false);
  assert.equal(templateEntry("bihuo-23-v1")?.[1], "快讯直播");
  // 新闻资讯 still offers its other looks.
  for (const id of ["bihuo-14-v1", "bihuo-28-v1", "bihuo-33-v1"]) assert.equal(isTemplateListed(id), true, id);
});
