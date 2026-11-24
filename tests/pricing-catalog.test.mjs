import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CREDIT_PACKS, MEMBERSHIP_PLANS, WELCOME_CREDITS, WELCOME_CREDITS_VALIDITY_DAYS, yuan } from "../lib/pricing-catalog.ts";

const products = readFileSync(new URL("../backend/app/credit_products.py", import.meta.url), "utf8");
const welcome = readFileSync(new URL("../backend/app/welcome_credits.py", import.meta.url), "utf8");
const landing = readFileSync(new URL("../components/ember-landing.tsx", import.meta.url), "utf8");

function tuples(pattern) {
  return [...products.matchAll(pattern)].map((match) => match.slice(1));
}

test("首页会员价目与后端 credit_products.py 完全一致", () => {
  const backend = tuples(/\("(light|pro|team)", "([^"]+)", (\d+), (\d+), (\d+)\)/g)
    .map(([id, name, credits, monthly, annual]) => ({ id, name, monthlyFen: +monthly, annualFen: +annual, monthlyCredits: +credits }));
  assert.equal(backend.length, 3);
  assert.deepEqual(MEMBERSHIP_PLANS.map((plan) => ({ ...plan })), backend);
});

test("首页积分包价目与后端 credit_products.py 完全一致", () => {
  const validity = Number(/PRODUCTS\[product_id\] = Product\(\s*product_id, name, price, credits, "pack", validity_months=(\d+)/.exec(products)?.[1]);
  const backend = tuples(/\("(pack_\w+)", "([^"]+)", (\d+), (\d+)\)/g)
    .map(([id, name, price, credits]) => ({ id, name, amountFen: +price, credits: +credits, validityMonths: validity }));
  assert.equal(backend.length, 3);
  assert.deepEqual(CREDIT_PACKS.map((pack) => ({ ...pack })), backend);
});

test("新用户赠送积分与后端 welcome_credits.py 一致", () => {
  assert.equal(WELCOME_CREDITS, Number(/^WELCOME_CREDITS = (\d+)$/m.exec(welcome)?.[1]));
  assert.equal(WELCOME_CREDITS_VALIDITY_DAYS, Number(/^VALIDITY_DAYS = (\d+)$/m.exec(welcome)?.[1]));
});

test("元金额格式化", () => {
  assert.equal(yuan(9900), "99");
  assert.equal(yuan(2990), "29.9");
  assert.equal(yuan(94800), "948");
  assert.equal(yuan(1999), "19.99");
});

test("首页价格区不再写死价格，也不宣传尚未上线的能力", () => {
  assert.match(landing, /MEMBERSHIP_PLANS/);
  assert.match(landing, /CREDIT_PACKS/);
  for (const claim of ["1,200 积分", "多人协作", "品牌素材库", "发票", "优先排队"]) {
    assert.ok(!landing.includes(claim), `首页仍包含「${claim}」`);
  }
});
