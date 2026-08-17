import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const utf8 = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("help center search, category filters, anchors, and FAQ controls are functional", async () => {
  const page = await utf8("app/help/page.tsx");

  assert.match(page, /value=\{query\}/);
  assert.match(page, /onChange=\{\(event\) => setQuery\(event\.target\.value\)\}/);
  assert.match(page, /event\.metaKey \|\| event\.ctrlKey/);
  assert.match(page, /filteredTopics/);
  assert.match(page, /filteredFaqs/);
  assert.match(page, /setCategory\(item\.id\)/);
  assert.match(page, /aria-pressed=\{category === item\.id\}/);
  assert.match(page, /href="#quick-start"/);
  assert.match(page, /href="#all-features"/);
  assert.match(page, /href="#guides"/);
  assert.match(page, /href="#faq"/);
  assert.match(page, /href="#support"/);
  assert.match(page, /aria-expanded=\{open\}/);
  assert.match(page, /没有找到完全匹配的内容/);
});

test("help center renders the live feature registry instead of a copied feature list", async () => {
  const page = await utf8("app/help/page.tsx");

  assert.match(page, /import \{ FEATURE_GROUPS \} from "@\/lib\/feature-registry"/);
  assert.match(page, /FEATURE_GROUPS\.map/);
  assert.match(page, /group\.features\.map/);
  assert.match(page, /feature\.route/);
  assert.match(page, /feature\.inputHint/);
  assert.match(page, /feature\.outputHint/);
});

test("help center states the final 30-day retention rules and real support channel", async () => {
  const [page, content] = await Promise.all([
    utf8("app/help/page.tsx"),
    utf8("lib/help-center-content.ts"),
  ]);
  const combined = `${page}\n${content}`;

  assert.match(combined, /用户上传素材从上传成功起保存 30 天/);
  assert.match(combined, /生成图片从创建成功起保存 30 天/);
  assert.match(combined, /终态任务记录，从任务结束起保存 30 天/);
  assert.match(combined, /草稿从创建起保存 30 天/);
  assert.match(combined, /到期后相关内容不可恢复/);
  assert.match(combined, /1474953130@qq\.com/);
  assert.match(page, /mailto:/);
  assert.doesNotMatch(combined, /篇指南/);
  assert.doesNotMatch(combined, /平均 5 分钟/);
  assert.doesNotMatch(combined, /联系在线支持/);
});

test("mobile primary navigation includes a direct help-center entry", async () => {
  const [registry, navigation] = await Promise.all([
    utf8("lib/navigation-registry.ts"),
    utf8("components/top-navigation.tsx"),
  ]);

  assert.match(registry, /MOBILE_PRIMARY_NAVIGATION_LINKS/);
  assert.match(registry, /\{ label: "帮助中心", href: "\/help" \}/);
  assert.match(navigation, /primaryLinks=\{MOBILE_PRIMARY_NAVIGATION_LINKS\}/);
});
