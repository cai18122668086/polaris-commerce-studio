import assert from "node:assert/strict";
import test from "node:test";
import { COMMERCE_ENTRIES, commerceEntryHref } from "../lib/commerce-entrypoints.ts";
import { assetCreationHref, readAssetHandoff } from "../lib/assets/creation-handoff.ts";
import { resolveJobWorkspaceHref } from "../lib/jobs/workspace-link-resolution.ts";
import { FEATURE_REGISTRY } from "../lib/feature-registry.ts";

test("commerce choices each reach an actual distinct workspace and Amazon has one full-suite entry", () => {
  assert.equal(COMMERCE_ENTRIES.length, 4);
  assert.equal(new Set(COMMERCE_ENTRIES.map(e => e.href)).size, 4);
  for (const entry of COMMERCE_ENTRIES) {
    assert.equal(FEATURE_REGISTRY.find(f => f.id === entry.id)?.route, entry.href);
  }
  assert.equal(COMMERCE_ENTRIES.filter(e => e.id.includes("amazon")).length, 1);
  assert.match(COMMERCE_ENTRIES.find(e => e.id === "amazon-visual-suite").output, /21/);
});

test("market choice preserves source identity and order into either detail workspace", () => {
  const href = assetCreationHref("/create", "ws_test", ["asset_first", "asset_second"], "case_original");
  const search = new URL(href, "http://localhost").searchParams;
  assert.equal(search.get("goal"), "detail");
  for (const entry of COMMERCE_ENTRIES.filter(e => e.acceptsHandoff)) {
    const target = new URL(commerceEntryHref(entry, search), "http://localhost");
    assert.equal(target.pathname, entry.href);
    assert.deepEqual(readAssetHandoff(target.searchParams, "ws_test", 8), {
      ids: ["asset_first", "asset_second"], caseId: "case_original",
    });
  }
});

test("saved market determines task continuation while old links remain usable", () => {
  const job = { id: "job_original", type: "detail_pack", configuration: { settings: { market_region: "international" } } };
  assert.equal(resolveJobWorkspaceHref(job, FEATURE_REGISTRY), "/workspace/crossborder-detail?jobId=job_original");
  assert.equal(resolveJobWorkspaceHref({ ...job, configuration: { settings: { market_region: "domestic" } } }, FEATURE_REGISTRY), "/workspace/detail-pack?jobId=job_original");
  assert.equal(resolveJobWorkspaceHref({ ...job, configuration: undefined, display_name: "跨境商品详情图 · 茶杯" }, FEATURE_REGISTRY), "/workspace/crossborder-detail?jobId=job_original");
});
