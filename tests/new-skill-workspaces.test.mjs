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

test("creative and reference workspaces preserve the full count and aspect-ratio controls", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  assert.match(workspace, /const \[imageCount, setImageCount\] = useState\(1\)/);
  assert.match(workspace, /image_count: imageCount/);
  assert.doesNotMatch(workspace, /image_count: Math\.min/);
  assert.match(workspace, /Array\.from\(\{ length: 12 \}/);
  assert.match(workspace, /setImageCount\(count\)/);
  assert.match(workspace, /value: "4:5"/);
  assert.match(workspace, /value: "follow-reference"/);
  assert.match(workspace, /featureId === "reference-remix" \? "follow-reference" : "1:1"/);
  for (const size of [
    "1024 × 1024",
    "768 × 1024",
    "1024 × 1280",
    "1024 × 768",
    "576 × 1024",
    "1024 × 576",
  ]) {
    assert.match(workspace, new RegExp(size));
  }
  assert.match(workspace, /严格交付尺寸：\{selectedSizeLabel\}/);
  assert.match(
    workspace,
    /主图 2000 × 2000；副图 1200 × 1600；桌面 A\+ 1464 × 600；移动 A\+ 1600 × 1200/,
  );
});

test("commerce workspaces do not require a guessed product name", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  assert.match(workspace, /product_name: productName\.trim\(\)/);
  assert.doesNotMatch(workspace, /PRODUCT_NAME_NOT_PROVIDED/);
  assert.doesNotMatch(workspace, /amazonProductNameMissing/);
  assert.doesNotMatch(workspace, /Amazon 套图必须填写商品名称/);
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

test("Amazon workflow reviews and confirms the backend 21-page plan", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  const jobApi = await utf8("features/jobs/api/jobs.ts");

  assert.match(workspace, /readAmazonPlanPages\(job\.data\?\.plan\?\.payload\)/);
  assert.match(workspace, /job\.data\?\.status === "awaiting_confirmation"/);
  assert.match(workspace, /确认 21 项页面规划/);
  assert.match(workspace, /amazonPlanPages\.map/);
  assert.match(workspace, /useConfirmPlan\(workspace\?\.id\)/);
  assert.match(workspace, /allowsJobAction\(job\.data\.allowed_actions, "confirm_plan"\)/);
  assert.match(workspace, /revision: job\.data\.plan\.revision/);
  assert.match(workspace, /确认计划并开始生成/);
  assert.match(jobApi, /invalidateQueries/);
  assert.match(jobApi, /status && isActiveJob\(status\) \? 1_500 : false/);
});

test("Amazon distinguishes technical completion from business quality review", async () => {
  const workspace = await utf8("components/commerce-skill-workspace.tsx");
  assert.match(workspace, /readAmazonBusinessQuality/);
  assert.match(workspace, /技术交付完成，业务质量等待人工审核/);
  assert.match(workspace, /技术交付完成，业务质量检查未通过/);
  assert.match(workspace, /不会自动重做/);
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
  assert.match(runtime, /reasonCode: capability\.reason_code/);
  assert.doesNotMatch(workspace, /data:image|placeholder.*asset|mock.*image/i);
});

test("public navigation uses registry route matching instead of local-edit fallback", async () => {
  const toolRegistry = await utf8("lib/tool-registry.ts");
  const sidebar = await utf8("components/tool-sidebar.tsx");
  const navigation = await utf8("components/top-navigation.tsx");
  const navigationRegistry = await utf8("lib/navigation-registry.ts");
  const directory = await utf8("components/tool-directory.tsx");

  assert.match(toolRegistry, /FEATURE_GROUPS\.map/);
  assert.match(sidebar, /getFeatureByRoute\(pathname\)/);
  assert.match(sidebar, /currentFeature\?\.jobType/);
  assert.match(sidebar, /currentFeature\?\.route \?\? "\/tools"/);
  assert.doesNotMatch(sidebar, /pathname\.includes\("detail-pack"\) \? "detail_pack" : "local_edit"/);
  assert.match(navigation, /AI_FEATURES_MENU/);
  assert.match(navigationRegistry, /href: "\/tools"/);
  assert.doesNotMatch(navigation, /\/\#tools/);
  assert.match(directory, /FEATURE_REGISTRY\.map/);
  assert.match(directory, /searchableTools\.filter/);
});

test("detail workspace submits the selected market and only auto-starts domestic", async () => {
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  assert.match(detail, /DOMESTIC_DETAIL_SIZE: MarketplaceImageSize = "1200x1600"/);
  assert.match(detail, /严格交付 \{imageSize\}/);
  assert.match(detail, /\{selectedMarketplace\.name\} · \{imageSize\}/);
  assert.match(detail, /market_region: marketRegion/);
  assert.match(detail, /auto_start_after_plan: marketRegion === "domestic"/);
  assert.doesNotMatch(detail, /market_region: "international" as const/);
  assert.match(detail, /selectRegion\("domestic"\).*disabled=\{Boolean\(jobId\)\}/);
  assert.match(detail, /selectRegion\("international"\).*disabled=\{Boolean\(jobId\)\}/);
});

test("completed detail and Amazon packs expose real attachment and ZIP downloads", async () => {
  const assetApi = await utf8("features/assets/api/assets.ts");
  const jobApi = await utf8("features/jobs/api/jobs.ts");
  const result = await utf8("components/job-result-image.tsx");
  const archive = await utf8("components/job-deliverables-download.tsx");
  const detail = await utf8("app/workspace/detail-pack/page.tsx");
  const commerce = await utf8("components/commerce-skill-workspace.tsx");

  assert.match(assetApi, /disposition: "inline" \| "attachment"/);
  assert.match(result, /getAssetAccessUrl[\s\S]*"attachment"/);
  assert.doesNotMatch(result, /href=\{access\.data\.url\} download/);
  assert.match(jobApi, /jobs\/\{job_id\}\/deliverables\.zip/);
  assert.match(archive, /下载整套 ZIP/);
  assert.match(detail, /JobDeliverablesDownload/);
  assert.match(commerce, /archiveJobId=\{[\s\S]*isAmazon/);
});
