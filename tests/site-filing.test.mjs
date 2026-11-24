import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ICP_LOOKUP_URL, SITE_OPERATOR, siteFiling } from "../lib/site-filing.ts";

test("备案号未配置时不显示，只保留运营主体", () => {
  assert.deepEqual(siteFiling({}), { operator: SITE_OPERATOR, icp: null, psb: null });
  assert.deepEqual(siteFiling({ icp: "  ", psb: "" }), { operator: SITE_OPERATOR, icp: null, psb: null });
});

test("ICP 备案号链接到工信部备案查询，公网安备号链接到公安备案查询", () => {
  const filing = siteFiling({ icp: " 粤ICP备2026000000号-1 ", psb: "粤公网安备44520002000000号" });
  assert.deepEqual(filing.icp, { number: "粤ICP备2026000000号-1", href: ICP_LOOKUP_URL });
  assert.equal(ICP_LOOKUP_URL, "https://beian.miit.gov.cn/");
  assert.equal(filing.psb.number, "粤公网安备44520002000000号");
  assert.match(filing.psb.href, /^https:\/\/beian\.mps\.gov\.cn\/.*44520002000000$/);
});

test("运营主体与用户协议一致，页脚统一称“用户协议”", () => {
  assert.ok(readFileSync(new URL("../app/legal/terms/page.tsx", import.meta.url), "utf8").includes(`运营主体：${SITE_OPERATOR}`));
  for (const file of ["../components/ember-landing.tsx", "../components/home-showcase.tsx"]) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.ok(!source.includes("服务条款"), file);
    assert.match(source, /<Link href="\/legal\/terms">用户协议<\/Link>/);
    assert.match(source, /<SiteFilingLine/);
  }
});
