import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (file) => readFile(file, "utf8");

test("Aurora domestic main image keeps the six-page Harness workflow visible", async () => {
  const [page, workspace, registry, navigation] = await Promise.all([
    read("app/workspace/domestic-main-image/page.tsx"),
    read("components/domestic-main-image-workspace.tsx"),
    read("lib/feature-registry.ts"),
    read("lib/navigation-registry.ts"),
  ]);

  assert.match(page, /DomesticMainImageWorkspace/);
  assert.match(workspace, /type: "domestic_main_image"/);
  assert.match(workspace, /product_asset_ids/);
  assert.match(workspace, /确认方案并开始/);
  assert.match(workspace, /固定六张，不增不减/);
  assert.match(workspace, /每页最多自动修复一次/);
  assert.match(registry, /aurora-domestic-ecommerce-main-image/);
  assert.match(registry, /aurora_six_page_reviewed_set/);
  assert.match(navigation, /navigationFeature\("domestic-main-image"/);
});
