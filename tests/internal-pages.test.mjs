import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { DISALLOWED_PATHS, PUBLIC_SITEMAP_ROUTES } from "../lib/site-seo.ts";

const root = new URL("..", import.meta.url).pathname;
const read = (file) => readFileSync(path.join(root, file), "utf8");

function sources(directory) {
  return readdirSync(path.join(root, directory)).flatMap((name) => {
    const file = path.join(directory, name);
    if (statSync(path.join(root, file)).isDirectory()) return sources(file);
    return /\.(ts|tsx)$/.test(name) ? [file] : [];
  });
}

test("真实商品爬虫页只对管理员开放", () => {
  const page = read("app/commerce-crawler/page.tsx");
  assert.match(page, /<AdminGate><CommerceCrawlerWorkspace \/><\/AdminGate>/);
  assert.match(read("components/admin/admin-gate.tsx"), /access\.data\?\.can_manage/);
});

test("爬虫入口只出现在管理员导航里，不进普通导航和工具目录", () => {
  const linking = ["app", "components", "features", "lib"].flatMap(sources)
    .filter((file) => file !== "lib/site-seo.ts" && read(file).includes('"/commerce-crawler"'));
  assert.deepEqual(linking, ["components/admin/admin-navigation.tsx"]);
});

test("内部页面不进站点地图，并禁止搜索引擎抓取", () => {
  for (const internal of ["/admin", "/commerce-crawler", "/diagnostics/"]) {
    assert.ok(DISALLOWED_PATHS.includes(internal), internal);
    assert.ok(!PUBLIC_SITEMAP_ROUTES.some((route) => route.path.startsWith(internal.replace(/\/$/, ""))), internal);
  }
});
