import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const utf8 = (file) => readFile(path.join(root, file), "utf8");

test("all new standalone feature routes render the shared commerce workspace", async () => {
  const routes = {
    "app/workspace/reference-remix/page.tsx": "reference-remix",
    "app/workspace/creative-image/page.tsx": "creative-image",
    "app/workspace/amazon-visual-suite/page.tsx": "amazon-visual-suite",
  };
  for (const [file, featureId] of Object.entries(routes)) {
    const source = await utf8(file);
    assert.match(source, /CommerceSkillWorkspace/);
    assert.match(source, new RegExp(`featureId="${featureId}"`));
  }
});

test("standalone workspaces submit the exact backend job families", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  for (const jobType of [
    "reference_remix",
    "creative_image",
    "amazon_visual_suite",
  ]) {
    assert.match(workspace, new RegExp(`type: "${jobType}"`));
  }
  assert.match(workspace, /product_asset_ids: selections\.product/);
  assert.match(workspace, /reference_asset_ids: selections\.reference/);
  assert.match(workspace, /competitor_asset_ids: selections\.competitor/);
  assert.match(workspace, /white_background_product_asset_ids: selections\.whiteBackground/);
  assert.match(workspace, /detail_asset_ids: selections\.detail/);
  assert.match(workspace, /package_asset_ids: selections\.package/);
  assert.match(workspace, /scene_asset_ids: selections\.scene/);
  assert.match(workspace, /brand_asset_ids: selections\.brand/);
});

test("creative image defaults to four and remains bounded at four", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  assert.match(workspace, /featureId === "creative-image" \? 4 : 1/);
  assert.match(workspace, /image_count: Math\.min\(4, imageCount\)/);
  assert.match(workspace, /\[1, 2, 3, 4\]/);
});

test("Amazon fixed pack delegates all 21 JobItems to the backend", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  const amazonPlatforms = workspace.slice(
    workspace.indexOf("const amazonPlatforms"),
    workspace.indexOf("const creativeDirections"),
  );
  const amazonBody = workspace.slice(
    workspace.indexOf('type: "amazon_visual_suite"'),
    workspace.indexOf("const submit = async"),
  );
  assert.match(workspace, /isAmazon \? 21 : imageCount/);
  assert.match(workspace, /固定 21 个 JobItem 由后端创建/);
  assert.match(amazonPlatforms, /value: "amazon-us"/);
  assert.doesNotMatch(amazonPlatforms, /tmall|jd|douyin|xiaohongshu|generic/);
  assert.match(workspace, /isAmazon \? amazonPlatforms : platforms/);
  assert.doesNotMatch(amazonBody, /image_count/);
  assert.doesNotMatch(amazonBody, /item_key|MAIN-01|SECONDARY-01|A-DESKTOP-01/);
});

test("new workspaces are runtime gated and never fabricate output", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  const runtime = await utf8("features/runtime/api/runtime.ts");
  assert.match(workspace, /resolveRuntimeCapability/);
  assert.match(workspace, /workflow\.canSubmit/);
  assert.match(workspace, /disabled=\{!canSubmit\}/);
  assert.match(workspace, /selectJobResultAssets\(job\.data\)/);
  assert.match(runtime, /execution === "mock"/);
  assert.match(runtime, /canSubmit: true/);
  assert.match(runtime, /REAL_PROVIDER_NOT_REGISTERED|真实 Provider 未接入/);
  assert.doesNotMatch(workspace, /data:image|placeholder.*asset|mock.*image/i);
});

test("public navigation uses registry route matching instead of local-edit fallback", async () => {
  const toolRegistry = await utf8("lib/tool-registry.ts");
  const sidebar = await utf8("components/tool-sidebar.tsx");
  const navigation = await utf8("components/top-navigation.tsx");
  const directory = await utf8("components/tool-directory.tsx");

  assert.match(toolRegistry, /FEATURE_GROUPS\.map/);
  assert.match(sidebar, /getFeatureByRoute\(pathname\)/);
  assert.match(sidebar, /currentFeature\?\.jobType/);
  assert.match(sidebar, /currentFeature\?\.route \?\? "\/tools"/);
  assert.doesNotMatch(sidebar, /pathname\.includes\("detail-pack"\) \? "detail_pack" : "local_edit"/);
  assert.match(navigation, /href: "\/tools"/);
  assert.doesNotMatch(navigation, /\/\#tools/);
  assert.match(directory, /FEATURE_REGISTRY\.filter/);
});

test("detail workspace submits the selected market and only auto-starts domestic", async () => {
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  assert.match(detail, /market_region: marketRegion/);
  assert.match(detail, /auto_start_after_plan: marketRegion === "domestic"/);
  assert.doesNotMatch(detail, /market_region: "international" as const/);
  assert.match(detail, /selectRegion\("domestic"\).*disabled=\{Boolean\(jobId\)\}/);
  assert.match(detail, /selectRegion\("international"\).*disabled=\{Boolean\(jobId\)\}/);
});
